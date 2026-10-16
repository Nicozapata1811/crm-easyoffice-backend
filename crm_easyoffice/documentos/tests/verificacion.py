"""Checks every generated PLT-01 must pass (ported from the PLT-01 spike)."""

from __future__ import annotations

import re

from crm_easyoffice.documentos.conversion import ooxml

PARTES_XML = re.compile(r"word/(document|header\d|footer\d|footnotes|endnotes)\.xml")
FILAS_TABLA_COMPLEMENTARIA = 15


def normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def documento(docx: bytes) -> str:
    return ooxml.read_docx(docx)["word/document.xml"].decode()


def texto(docx: bytes) -> str:
    return normalizar(ooxml.text(documento(docx)))


def restos(docx: bytes) -> list[str]:
    """Merge fields, «MARKERS», Jinja tags or placeholders left in any part."""
    encontrados = []
    for nombre, contenido in ooxml.read_docx(docx).items():
        if not PARTES_XML.fullmatch(nombre):
            continue
        xml = contenido.decode()
        visible = ooxml.text(xml)
        encontrados += re.findall(r"«[^»]*»", visible)
        encontrados += re.findall(r"\{[{%].*?[%}]\}", visible)
        encontrados += ["MERGEFIELD"] * xml.count("MERGEFIELD")
        encontrados += ["[IMAGEN"] * visible.count("[IMAGEN")
    return encontrados


def filas_por_tabla(docx: bytes) -> list[int]:
    return [len(ooxml.ROW_RE.findall(t)) for t in ooxml.TBL_RE.findall(documento(docx))]


def clausula_primero(docx: bytes) -> str:
    parrafo = ooxml.paragraph_containing(documento(docx), "En virtud del presente")
    return normalizar(ooxml.text(parrafo.group(0)))


def imagenes_resueltas(docx: bytes) -> list[str]:
    """The media part each embedded image points at."""
    partes = ooxml.read_docx(docx)
    rels = partes["word/_rels/document.xml.rels"].decode()
    destinos = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels))
    destinos |= {
        k: v for v, k in re.findall(r'Target="([^"]+)"[^>]*Id="([^"]+)"', rels)
    }
    embebidas = re.findall(r'r:embed="([^"]+)"', documento(docx))
    return [
        f"word/{destinos[rid]}"
        for rid in embebidas
        if rid in destinos and f"word/{destinos[rid]}" in partes
    ]


def espacios_de_nombres(xml: str) -> set[str]:
    raiz = ooxml.root_tag(xml)
    return set(re.findall(r'(xmlns:\w+="[^"]*"|mc:Ignorable="[^"]*")', raiz))
