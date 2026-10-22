"""Who, from where and through which channel: the context the triggers read.

The audit triggers (AD-08) read three transaction-local settings:
``app.usuario_id``, ``app.ip`` and ``app.origen``. They are set with
``set_config(..., true)``, the parameterised form of ``SET LOCAL``, so they
end with the transaction and can never reach the next request on a reused
connection.

They cannot be set by a middleware up front: ``ATOMIC_REQUESTS`` wraps only
the view, so a middleware runs outside the request's transaction, where
``SET LOCAL`` does nothing. Instead, a wrapper installed on every database
connection sets them right before the first write of each transaction, from
the context of the code running then:

- ``AuditoriaMiddleware`` makes each request the context. The user is read
  at write time, so a DRF-authenticated user and the user who has just
  logged in are both the right one.
- Celery tasks run under the ``sistema`` context (``core.apps``).
- With no context at all (management commands, migrations), nothing is set,
  and the triggers record the change as ``sistema`` with no user.

A write outside any transaction (autocommit) cannot carry ``SET LOCAL``, so
it is recorded with no user: never with someone else's.
"""

from __future__ import annotations

import ipaddress
import re
from contextlib import contextmanager
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings

from crm_easyoffice.core.models import RegistroAuditoria

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator

    from django.db.backends.base.base import BaseDatabaseWrapper
    from django.http import HttpRequest

Origen = RegistroAuditoria.Origen

SET_CONTEXTO = (
    "SELECT set_config('app.usuario_id', %s, true),"
    " set_config('app.ip', %s, true),"
    " set_config('app.origen', %s, true)"
)
# Statements that may change rows. A WITH may be a read; at worst it costs
# one set_config.
ESCRITURA = re.compile(r"^\s*(INSERT|UPDATE|DELETE|MERGE|WITH|COPY)\b", re.IGNORECASE)

# What the settings hold when nothing was set: the triggers read it as
# ``sistema`` with no user.
SIN_CONTEXTO = ("", "", "")


@dataclass(frozen=True)
class Valores:
    usuario_id: int | None
    ip: str | None
    origen: str

    def como_parametros(self) -> tuple[str, str, str]:
        if self == SISTEMA:
            # What the triggers assume when nothing is set: no query needed.
            return SIN_CONTEXTO
        usuario = "" if self.usuario_id is None else str(self.usuario_id)
        return (usuario, self.ip or "", self.origen)


@dataclass(eq=False)
class Contexto:
    """The source of the audit values for the code running now.

    Compared by identity: a new request is a new context, even for the same
    user, so its first write sets the values again.
    """

    request: HttpRequest | None = None
    origen: str = Origen.SISTEMA

    def valores(self) -> Valores:
        if self.request is None:
            return Valores(None, None, self.origen)
        user = getattr(self.request, "user", None)
        usuario_id = user.pk if user is not None and user.is_authenticated else None
        return Valores(usuario_id, ip_de(self.request), origen_de(self.request, user))


SISTEMA = Valores(None, None, Origen.SISTEMA)

_contexto: ContextVar[Contexto | None] = ContextVar("contexto_auditoria", default=None)


def contexto_actual() -> Contexto | None:
    return _contexto.get()


def valores_actuales() -> Valores:
    """The values an event written now must carry (``sistema`` by default)."""
    contexto = _contexto.get()
    return contexto.valores() if contexto else SISTEMA


@contextmanager
def contexto_auditoria(contexto: Contexto) -> Iterator[Contexto]:
    token = _contexto.set(contexto)
    try:
        yield contexto
    finally:
        _contexto.reset(token)


def ip_de(request: HttpRequest) -> str | None:
    # ASSUMPTION: pending validation with Easy Office. Behind the production
    # proxy the client address may arrive in X-Forwarded-For; which header to
    # trust depends on the hosting, still undecided (TA-09).
    direccion = request.META.get("REMOTE_ADDR", "")
    try:
        return str(ipaddress.ip_address(direccion))
    except ValueError:
        return None


def origen_de(request: HttpRequest, user: Any) -> str:
    ruta = request.path_info
    if ruta.startswith(f"/{settings.ADMIN_URL}"):
        return Origen.ADMIN
    if ruta.startswith("/api/portal/"):
        return Origen.PORTAL
    if ruta.startswith("/api/pagos/"):
        # Payment webhooks and the provider's return: nobody's action.
        return Origen.SISTEMA
    if (
        ruta.startswith("/api/auth/")
        and user is not None
        and user.is_authenticated
        and hasattr(user, "cuenta_cliente")
    ):
        return Origen.PORTAL
    return Origen.API


@dataclass
class _Aplicado:
    """What was set, in which open atomic blocks, for which context."""

    bloques: list[Any] = field(default_factory=list)
    contexto: Contexto | None = None
    parametros: tuple[str, str, str] = SIN_CONTEXTO


class AplicadorContexto:
    """``execute_wrapper`` that sets the audit context before a write.

    One per connection. Before a write inside a transaction it compares what
    the transaction holds with what the current context wants, and sets the
    values when they differ, at most once per transaction and context.
    """

    def __init__(self, connection: BaseDatabaseWrapper) -> None:
        self.connection = connection
        self.aplicado: _Aplicado | None = None

    def __call__(
        self,
        execute: Callable[..., Any],
        sql: Any,
        params: Any,
        many: bool,  # noqa: FBT001
        context: dict[str, Any],
    ) -> Any:
        if not self.connection.in_atomic_block:
            # Autocommit: any earlier transaction has ended with its settings.
            self.aplicado = None
        elif isinstance(sql, str) and ESCRITURA.match(sql):
            self._preparar(context)
        return execute(sql, params, many, context)

    def _preparar(self, context: dict[str, Any]) -> None:
        contexto = _contexto.get()
        deseado = contexto.valores().como_parametros() if contexto else SIN_CONTEXTO
        bloques = list(self.connection.atomic_blocks)
        actual = self._actual(bloques, contexto)
        if actual == deseado:
            return
        self.fijar(context["cursor"], deseado)
        self.aplicado = _Aplicado(bloques, contexto, deseado)

    @staticmethod
    def fijar(cursor: Any, parametros: tuple[str, str, str]) -> None:
        # On the driver cursor: the wrapped executor may be executemany.
        cursor.cursor.execute(SET_CONTEXTO, parametros)

    def _actual(self, bloques: list[Any], contexto: Contexto | None) -> Any:
        """What the transaction holds now, or None when it is unknown."""
        aplicado = self.aplicado
        if aplicado is None or not bloques or not aplicado.bloques:
            return SIN_CONTEXTO
        if aplicado.bloques[0] is not bloques[0]:
            # Another outermost block: a new transaction, nothing set yet.
            return SIN_CONTEXTO
        sigue_abierto = len(aplicado.bloques) <= len(bloques) and all(
            a is b for a, b in zip(aplicado.bloques, bloques, strict=False)
        )
        if sigue_abierto and aplicado.contexto is contexto:
            return aplicado.parametros
        # The block where the values were set has closed: released (they
        # remain) or rolled back (they are gone). Or the context changed and
        # the same atomic object may be a later transaction. Set them again.
        return None


def instalar_aplicador(connection: BaseDatabaseWrapper, **kwargs: Any) -> None:
    """``connection_created`` receiver: one wrapper per connection."""
    if any(isinstance(w, AplicadorContexto) for w in connection.execute_wrappers):
        return
    connection.execute_wrappers.append(AplicadorContexto(connection))


# A Celery task is nobody's action, even when it runs eagerly inside a
# request (tests): its changes are recorded as ``sistema``.
_tareas: dict[str, Token[Contexto | None]] = {}


def al_iniciar_tarea(task_id: str, **kwargs: Any) -> None:
    _tareas[task_id] = _contexto.set(Contexto(origen=Origen.SISTEMA))


def al_terminar_tarea(task_id: str, **kwargs: Any) -> None:
    token = _tareas.pop(task_id, None)
    if token is not None:
        _contexto.reset(token)
