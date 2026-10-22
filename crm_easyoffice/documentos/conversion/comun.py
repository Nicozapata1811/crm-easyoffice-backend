"""Conversion steps shared by Easy Office's service contracts (PLT-01, PLT-02).

Both templates come from the same contract base: the same parties clause, the
same two service tables, the same PRIMERO and the same two ID-card
placeholders. What only one template has stays in its own module.

Every edit asserts the exact runs it expects and fails on template drift.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import ooxml

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable

# Merge fields both templates carry → context path. Each printed value has
# exactly one source; documentos.comun builds these parts of the context.
CAMPOS_COMUNES = {
    "FOLIO": "folio",
    "FECHA_DE_INICIO": "fecha_inicio",
    "VENCIMIENTO": "vencimiento",
    "BANCOLINK": "bancolink",
    "SUCURSAL": "sucursal.direccion",
    "COMUNA_SUCURSAL": "sucursal.comuna",
    "REGIÓN_SUCURSAL": "sucursal.region",
    "RAZON_SOCIAL": "empresa.razon_social",
    "RUT": "empresa.rut",
    "GIRO_PRINCIPAL": "empresa.giro",
    "REPRESENTANTE_LEGAL": "representante.nombre",
    "RUT_REP_LEGAL": "representante.rut",
    "DOMIC_REP_LEGAL": "representante.domicilio",
    "COMUNA_REP_LEGAL": "representante.comuna",
    "REGIÓN_REP_LEGAL": "representante.region",
    "FECHA_ESCRITURAESTATUTO_ACTUALIZADO": "personeria.fecha",
    "SITIONOTARÍA": "personeria.sitio",
    "MAIL": "aviso.mail",
    "CELULAR_8_DIGITOS": "aviso.celular",
    # Only PRIMERO is left once the service rows are converted.
    "SERVICIO_1": "servicios[0].nombre",
}

# Fields of each service row; the suffix (_1, _2, _3) is the row.
CAMPOS_SERVICIO = {
    "SERVICIO": "nombre",
    "PRECIO_Ss": "precio",
    "CICLO_PAGO_Ss": "ciclo",
    "DESCRIPCIÓN_Ss": "descripcion",
}

# Easy Office's representative, a plain-text marker left by the anonymisation.
MARCADORES_EO = {
    "EO_REPRESENTANTE": "eo.representante",
    "EO_REP_NACIONALIDAD": "eo.nacionalidad",
    "EO_REP_ESTADO_CIVIL": "eo.estado_civil",
    "EO_REP_PROFESION": "eo.profesion",
    "EO_REP_RUT": "eo.rut",
}

IMAGENES = ["cedula_anverso", "cedula_reverso"]
PLACEHOLDER_IMAGEN = "[IMAGEN DEL DOCUMENTO DE IDENTIDAD DEL AUTORIZANTE"
SERVICIO_N = re.compile(r"(SERVICIO|PRECIO_Ss|CICLO_PAGO_Ss|DESCRIPCIÓN_Ss)_(\d)")


def tag(expresion: str, rpr: str = "") -> str:
    return ooxml.make_run(expresion, rpr)


def _campo_servicio(nombre: str) -> str | None:
    if match := SERVICIO_N.fullmatch(nombre):
        return CAMPOS_SERVICIO[match.group(1)]
    return None


def _fila_tag(etiqueta: str) -> str:
    # docxtpl replaces the whole row holding a {%tr %} tag with the tag.
    return f"<w:tr><w:tc><w:p>{tag(etiqueta)}</w:p></w:tc></w:tr>"


def aceptar_revisiones(doc: str) -> str:
    """Accept the template's tracked changes: drop deletions, keep insertions.

    Word hides them when exporting, LibreOffice prints revision bars: a
    generated contract must carry none.
    """
    doc = re.sub(r"<w:del [^>]*[^/]>.*?</w:del>", "", doc, flags=re.S)
    doc = re.sub(r"<w:ins [^>]*[^/]>(.*?)</w:ins>", r"\1", doc, flags=re.S)
    if re.search(r"<w:(ins|del|moveFrom|moveTo)[ >/]|<w:\w+PrChange[ >]", doc):
        msg = "template drift: a tracked change could not be accepted"
        raise ValueError(msg)
    return doc


def filas_servicio(doc: str) -> str:
    """OB-01: one row per contracted service, in the prices table and Anexo 1.

    Empty rows left after the service rows (PLT-02's prices table has two)
    go too: the table holds exactly the contracted services.
    """
    edits = []
    for tabla in ooxml.TBL_RE.finditer(doc):
        todas = list(ooxml.ROW_RE.finditer(tabla.group(0)))
        filas = [
            fila
            for fila in todas
            if any(_campo_servicio(c.name) for c in ooxml.fields(fila.group(0)))
        ]
        if not filas:
            continue
        for fila in todas[todas.index(filas[-1]) + 1 :]:
            if ooxml.text(fila.group(0)).strip() or "MERGEFIELD" in fila.group(0):
                break
            filas.append(fila)

        def etiqueta(campo: ooxml.Field) -> str | None:
            clave = _campo_servicio(campo.name)
            return tag(f"{{{{ s.{clave} }}}}", campo.rpr) if clave else None

        fila = ooxml.replace_fields(filas[0].group(0), etiqueta)
        nuevas = (
            _fila_tag("{%tr for s in servicios %}") + fila + _fila_tag("{%tr endfor %}")
        )
        base = tabla.start()
        edits.append((base + filas[0].start(), base + filas[-1].end(), nuevas))
    if len(edits) != 2:  # noqa: PLR2004
        msg = f"template drift: expected 2 service tables, found {len(edits)}"
        raise ValueError(msg)
    return ooxml.splice(doc, edits)


def primero(doc: str) -> str:
    """OB-01 in PRIMERO: the located service, then every other one.

    The template reads "…región «REGIÓN_SUCURSAL»; «SERVICIO_2»  y en las…",
    with "; " and the two spaces in runs of their own.
    """
    parrafo = ooxml.paragraph_containing(doc, "En virtud del presente")
    texto = parrafo.group(0)
    servicio_2 = next(f for f in ooxml.fields(texto) if f.name == "SERVICIO_2")
    resto = "{% for s in servicios[1:] %}; {{ s.nombre }}{% endfor %}"
    texto = ooxml.splice(
        texto,
        [(servicio_2.start, servicio_2.end, tag(resto, servicio_2.rpr))],
    )
    fin_resto = servicio_2.start + len(tag(resto, servicio_2.rpr))
    texto = ooxml.drop_runs_after(texto, fin_resto, [" "])
    texto = ooxml.drop_runs_before(texto, servicio_2.start, [";", " "])
    return doc[: parrafo.start()] + texto + doc[parrafo.end() :]


def campos(mapa: dict[str, str]) -> Callable[[str], str]:
    """Every merge field becomes its context path, keeping the run's format."""

    def paso(doc: str) -> str:
        def etiqueta(campo: ooxml.Field) -> str:
            return tag(f"{{{{ {mapa[campo.name]} }}}}", campo.rpr)

        return ooxml.replace_fields(doc, etiqueta)

    return paso


def marcadores(mapa: dict[str, str]) -> Callable[[str], str]:
    """Every «MARKER» left by the anonymisation becomes its context path."""

    def paso(doc: str) -> str:
        def etiqueta(match: re.Match) -> str:
            return f"{{{{ {mapa[match.group(1)]} }}}}"

        return re.sub(r"«([A-Z_]+)»", etiqueta, doc)

    return paso


def imagenes(doc: str) -> str:
    """The two ID-card placeholders become the front and back images."""
    marcas = [
        m for m in ooxml.runs(doc) if PLACEHOLDER_IMAGEN in ooxml.run_text(m.group(0))
    ]
    if len(marcas) != len(IMAGENES):
        msg = f"template drift: expected {len(IMAGENES)} image placeholders"
        raise ValueError(msg)
    edits = [
        (m.start(), m.end(), tag(f"{{{{ {nombre} }}}}"))
        for m, nombre in zip(marcas, IMAGENES, strict=True)
    ]
    return ooxml.splice(doc, edits)


def convertir(origen: bytes, pasos: Iterable[Callable[[str], str]]) -> bytes:
    """Run the conversion steps on the template's body; nothing may be left.

    Raises:
        ValueError: The template does not have the expected structure.
        KeyError: A merge field or marker has no source in its map.
    """
    parts = ooxml.read_docx(origen)
    doc = parts["word/document.xml"].decode()
    for paso in pasos:
        doc = paso(doc)
    if "MERGEFIELD" in doc or re.search(r"«[^»]*»", ooxml.text(doc)):
        msg = "template drift: a merge field or marker was left unconverted"
        raise ValueError(msg)
    parts["word/document.xml"] = doc.encode()
    return ooxml.write_docx(parts)
