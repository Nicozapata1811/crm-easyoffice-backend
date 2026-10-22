"""Turn Easy Office's PLT-02 Word template into a docxtpl template.

PLT-02 is PLT-01's contract with a warehouse authorisation instead of the
domicile one: the shared steps live in conversion.comun. What is its own:

- The authoriser is the warehouse's owner, a natural person
  (``«AUTORIZANTE_NOMBRE»``, ``«AUTORIZANTE_RUT»`` is the person's own RUT).
- OB-05: the anonymised template marks the warehouse's address, comuna and
  rol (``«BODEGA_*»``); the term was typed as "DOCE (12) MESES" and
  "(12 MESES)" and becomes the contract's; the region in the warehouse
  sentence comes from the warehouse, not the branch.
- There is no SII-unit paragraph (OB-02 is PLT-01's), no ``DURACIÓN`` field
  and no branch rol.

Every edit asserts the exact runs it expects and fails on template drift.
"""

from __future__ import annotations

from . import comun
from . import ooxml

# Merge field → context path; documentos.plt02.contexto builds the context.
CAMPOS = dict(comun.CAMPOS_COMUNES)

MARCADORES = {
    **comun.MARCADORES_EO,
    "AUTORIZANTE_NOMBRE": "autorizante.nombre",
    "AUTORIZANTE_RUT": "autorizante.rut",
    "AUTORIZANTE_NACIONALIDAD": "autorizante.nacionalidad",
    "AUTORIZANTE_ESTADO_CIVIL": "autorizante.estado_civil",
    "AUTORIZANTE_PROFESION": "autorizante.profesion",
    "BODEGA_DIRECCION": "bodega.direccion",
    "BODEGA_COMUNA": "bodega.comuna",
    "BODEGA_ROL_AVALUO": "bodega.rol",
}

PARRAFO_BODEGA = " VIENEN A AUTO"
PARRAFO_RENOVACION = "LA PRESENTE AUTORIZACIÓN VENCE"


def _reemplazar_runs(texto: str, esperados: list[str], nuevo: str) -> str:
    """Replace the consecutive runs whose texts are ``esperados`` with ``nuevo``.

    Empty runs between them are dropped too, unless they belong to a field.
    """
    llenos = [m for m in ooxml.runs(texto) if ooxml.run_text(m.group(0))]
    textos = [ooxml.run_text(m.group(0)) for m in llenos]
    n = len(esperados)
    inicios = [i for i in range(len(textos) - n + 1) if textos[i : i + n] == esperados]
    if len(inicios) != 1:
        msg = f"template drift: {len(inicios)} places with runs {esperados!r}"
        raise ValueError(msg)
    primero, ultimo = llenos[inicios[0]], llenos[inicios[0] + n - 1]
    tramo = texto[primero.start() : ultimo.end()]
    if "fldChar" in tramo:
        msg = f"template drift: a field sits inside runs {esperados!r}"
        raise ValueError(msg)
    return texto[: primero.start()] + nuevo + texto[ultimo.end() :]


def _rpr(texto: str, contenido: str) -> str:
    """The formatting of the run whose text is ``contenido``."""
    run = next(
        m.group(0) for m in ooxml.runs(texto) if ooxml.run_text(m.group(0)) == contenido
    )
    rpr = ooxml.RPR_RE.search(run)
    return rpr.group(0) if rpr else ""


def _en_parrafo(doc: str, aguja: str, editar) -> str:
    parrafo = ooxml.paragraph_containing(doc, aguja)
    return doc[: parrafo.start()] + editar(parrafo.group(0)) + doc[parrafo.end() :]


def _autorizacion_bodega(doc: str) -> str:
    """OB-05 in the warehouse sentence: the term, and the warehouse's region.

    The term is typed in runs "RIZAR POR DOCE  (12" / ")" / " MESES".
    """

    def editar(texto: str) -> str:
        rpr = _rpr(texto, "RIZAR POR DOCE  (12")
        texto = _reemplazar_runs(
            texto,
            ["RIZAR POR DOCE  (12", ")", " MESES"],
            ooxml.make_run("RIZAR POR ", rpr) + comun.tag("{{ duracion_letras }}", rpr),
        )
        regiones = [f for f in ooxml.fields(texto) if f.name == "REGIÓN_SUCURSAL"]
        if len(regiones) != 1:
            msg = "template drift: expected one region field in the warehouse sentence"
            raise ValueError(msg)
        region = regiones[0]
        return ooxml.splice(
            texto,
            [(region.start, region.end, comun.tag("{{ bodega.region }}", region.rpr))],
        )

    return _en_parrafo(doc, PARRAFO_BODEGA, editar)


def _renovacion(doc: str) -> str:
    """OB-05 in the renewal: "(12 MESES)" is the contract's own term.

    Typed in runs "OR IGUAL PERÍODO (12" / " " / "MESES), SALVO ".
    """

    def editar(texto: str) -> str:
        rpr = _rpr(texto, "OR IGUAL PERÍODO (12")
        return _reemplazar_runs(
            texto,
            ["OR IGUAL PERÍODO (12", " ", "MESES), SALVO "],
            ooxml.make_run("OR IGUAL PERÍODO ", rpr)
            + comun.tag("{{ duracion }}", rpr)
            + ooxml.make_run(", SALVO ", rpr),
        )

    return _en_parrafo(doc, PARRAFO_RENOVACION, editar)


def convertir(origen: bytes) -> bytes:
    """The docxtpl template for an anonymised PLT-02 Word file.

    Raises:
        ValueError: The template does not have the expected structure.
        KeyError: A merge field or marker has no source in CAMPOS/MARCADORES.
    """
    return comun.convertir(
        origen,
        [
            comun.aceptar_revisiones,
            comun.filas_servicio,
            comun.primero,
            _autorizacion_bodega,
            _renovacion,
            comun.campos(CAMPOS),
            comun.marcadores(MARCADORES),
            comun.imagenes,
        ],
    )
