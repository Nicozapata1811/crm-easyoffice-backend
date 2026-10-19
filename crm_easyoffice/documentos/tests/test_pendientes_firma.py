"""Documents waiting for a signature (RF-14). Every value here is synthetic."""

from __future__ import annotations

from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from crm_easyoffice.documentos.models import Documento
from crm_easyoffice.documentos.services import contar_pendientes_de_firma
from crm_easyoffice.documentos.tests.factories import documento_generado
from crm_easyoffice.tramites.services import COMPLETADO
from crm_easyoffice.tramites.services import FALTA_INFORMACION
from crm_easyoffice.tramites.services import FIRMA
from crm_easyoffice.tramites.services import INICIADO
from crm_easyoffice.tramites.services import PENDIENTE
from crm_easyoffice.tramites.services import REVISION_BORRADOR
from crm_easyoffice.tramites.tests.factories import tramite_con_historia

pytestmark = pytest.mark.django_db

SANTIAGO = ZoneInfo("America/Santiago")
REFERENCIA = date(2026, 9, 30)


def el(dia: int, hora: int = 10) -> datetime:
    return datetime(2026, 9, dia, hora, tzinfo=SANTIAGO)


def en_firma_desde(dia: int, *despues):
    return tramite_con_historia(
        (el(1), INICIADO, None),
        (el(dia), PENDIENTE, FIRMA),
        *despues,
    )


def test_counts_only_the_latest_version_of_each_case():
    tramite = en_firma_desde(12)
    documento_generado(tramite, 1, el(5), estado=Documento.Estado.REEMPLAZADO)
    documento_generado(tramite, 2, el(11))

    assert contar_pendientes_de_firma(REFERENCIA) == 1


def test_a_signed_document_no_longer_waits():
    tramite = en_firma_desde(12, (el(20), COMPLETADO, None))
    documento_generado(
        tramite,
        1,
        el(11),
        estado=Documento.Estado.FIRMADO,
        firmado_en=el(20),
    )

    assert contar_pendientes_de_firma(REFERENCIA) == 0


def test_a_document_signed_after_the_reference_date_was_waiting_then():
    octubre = datetime(2026, 10, 3, 10, tzinfo=SANTIAGO)
    tramite = en_firma_desde(12, (octubre, COMPLETADO, None))
    documento_generado(
        tramite,
        1,
        el(11),
        estado=Documento.Estado.FIRMADO,
        firmado_en=octubre,
    )

    assert contar_pendientes_de_firma(REFERENCIA) == 1
    assert contar_pendientes_de_firma(date(2026, 10, 3)) == 0


def test_a_case_waiting_for_information_is_not_waiting_for_a_signature():
    # Regeneration failed: the earlier version is still "generado".
    tramite = en_firma_desde(
        12,
        (el(15), PENDIENTE, FALTA_INFORMACION),
    )
    documento_generado(tramite, 1, el(11))

    assert contar_pendientes_de_firma(REFERENCIA) == 0


def test_a_draft_under_review_is_not_waiting_for_a_signature():
    tramite = tramite_con_historia(
        (el(1), INICIADO, None),
        (el(2), PENDIENTE, REVISION_BORRADOR),
    )
    documento_generado(tramite, 1, el(2))

    assert contar_pendientes_de_firma(REFERENCIA) == 0
