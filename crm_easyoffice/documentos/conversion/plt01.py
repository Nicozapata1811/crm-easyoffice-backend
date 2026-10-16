"""Turn Easy Office's PLT-01 Word template into a docxtpl template.

Easy Office keeps its contracts as Word files with mail-merge fields
(``«RAZON_SOCIAL»``) and, after anonymisation, plain-text markers
(``«EO_REP_RUT»``). This converter runs once per template version: every
field and marker becomes a Jinja tag in its own run, keeping the run's
formatting, and the converted file is what VersionPlantilla stores. Rendering
needs no knowledge of the template's layout.

It also fixes what a mail merge cannot do:

- OB-01: the service rows repeat per contracted service (``{%tr for %}``)
  instead of three fixed rows, and PRIMERO lists every service.
- OB-02: the SII unit and the municipality come from the branch instead of
  the text "UNIDAD DE SAN ANTONIO «COMUNA_SUCURSAL»".
- The two ID-card placeholders become the front and back images.
- Tracked changes left in the template are accepted.

Every edit asserts the exact runs it expects and fails on template drift,
so a new version from Easy Office is never converted silently wrong.
"""

from __future__ import annotations

import re

from . import ooxml

# Merge field → context path. Each printed value has exactly one source;
# documentos.plt01.contexto builds the context with these paths.
CAMPOS = {
    "FOLIO": "folio",
    "FECHA_DE_INICIO": "fecha_inicio",
    "DURACIÓN": "duracion",
    "VENCIMIENTO": "vencimiento",
    "BANCOLINK": "bancolink",
    "SUCURSAL": "sucursal.direccion",
    "COMUNA_SUCURSAL": "sucursal.comuna",
    "REGIÓN_SUCURSAL": "sucursal.region",
    "ROL_PROPIEDAD": "sucursal.rol",
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

# Plain-text markers left by the anonymisation.
MARCADORES = {
    "EO_REPRESENTANTE": "eo.representante",
    "EO_REP_NACIONALIDAD": "eo.nacionalidad",
    "EO_REP_ESTADO_CIVIL": "eo.estado_civil",
    "EO_REP_PROFESION": "eo.profesion",
    "EO_REP_RUT": "eo.rut",
    "AUTORIZANTE_RAZON_SOCIAL": "autorizante.razon_social",
    "AUTORIZANTE_RUT": "autorizante.rut",
    "AUTORIZANTE_REPRESENTANTE": "autorizante.representante",
    "AUTORIZANTE_REP_NACIONALIDAD": "autorizante.nacionalidad",
    "AUTORIZANTE_REP_ESTADO_CIVIL": "autorizante.estado_civil",
    "AUTORIZANTE_REP_PROFESION": "autorizante.profesion",
    "AUTORIZANTE_REP_RUT": "autorizante.rut_representante",
}

IMAGENES = ["cedula_anverso", "cedula_reverso"]
PLACEHOLDER_IMAGEN = "[IMAGEN DEL DOCUMENTO DE IDENTIDAD DEL AUTORIZANTE"
SERVICIO_N = re.compile(r"(SERVICIO|PRECIO_Ss|CICLO_PAGO_Ss|DESCRIPCIÓN_Ss)_(\d)")


def _tag(expresion: str, rpr: str = "") -> str:
    return ooxml.make_run(expresion, rpr)


def _campo_servicio(nombre: str) -> str | None:
    if match := SERVICIO_N.fullmatch(nombre):
        return CAMPOS_SERVICIO[match.group(1)]
    return None


def _fila_tag(tag: str) -> str:
    # docxtpl replaces the whole row holding a {%tr %} tag with the tag.
    return f"<w:tr><w:tc><w:p>{_tag(tag)}</w:p></w:tc></w:tr>"


def _aceptar_revisiones(doc: str) -> str:
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


def _filas_servicio(doc: str) -> str:
    """OB-01: one row per contracted service, in the prices table and Anexo 1."""
    edits = []
    for tabla in ooxml.TBL_RE.finditer(doc):
        filas = [
            fila
            for fila in ooxml.ROW_RE.finditer(tabla.group(0))
            if any(_campo_servicio(c.name) for c in ooxml.fields(fila.group(0)))
        ]
        if not filas:
            continue

        def etiqueta(campo: ooxml.Field) -> str | None:
            clave = _campo_servicio(campo.name)
            return _tag(f"{{{{ s.{clave} }}}}", campo.rpr) if clave else None

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


def _primero(doc: str) -> str:
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
        [(servicio_2.start, servicio_2.end, _tag(resto, servicio_2.rpr))],
    )
    fin_resto = servicio_2.start + len(_tag(resto, servicio_2.rpr))
    texto = ooxml.drop_runs_after(texto, fin_resto, [" "])
    texto = ooxml.drop_runs_before(texto, servicio_2.start, [";", " "])
    return doc[: parrafo.start()] + texto + doc[parrafo.end() :]


def _unidad_sii(doc: str) -> str:
    """OB-02: the SII unit and municipality of the authorisation, per branch.

    The fixed text is split in runs ", UNIDAD DE" / " SAN ANTONIO" / " ".
    """
    parrafo = ooxml.paragraph_containing(doc, "ILUSTRE MUNICIPA")
    texto = parrafo.group(0)
    comunas = [f for f in ooxml.fields(texto) if f.name == "COMUNA_SUCURSAL"]
    if len(comunas) != 2:  # noqa: PLR2004
        msg = "template drift in the SII paragraph"
        raise ValueError(msg)
    unidad, municipalidad = comunas
    texto = ooxml.splice(
        texto,
        [
            (unidad.start, unidad.end, _tag("{{ sucursal.unidad_sii }}", unidad.rpr)),
            (
                municipalidad.start,
                municipalidad.end,
                _tag("{{ sucursal.municipalidad }}", municipalidad.rpr),
            ),
        ],
    )
    texto = ooxml.drop_runs_before(texto, unidad.start, [" SAN ANTONIO", " "])
    texto = ooxml.set_run_text(texto, ", UNIDAD DE", ", ")
    return doc[: parrafo.start()] + texto + doc[parrafo.end() :]


def _campos(doc: str) -> str:
    def etiqueta(campo: ooxml.Field) -> str:
        return _tag(f"{{{{ {CAMPOS[campo.name]} }}}}", campo.rpr)

    return ooxml.replace_fields(doc, etiqueta)


def _marcadores(doc: str) -> str:
    def etiqueta(match: re.Match) -> str:
        return f"{{{{ {MARCADORES[match.group(1)]} }}}}"

    return re.sub(r"«([A-Z_]+)»", etiqueta, doc)


def _imagenes(doc: str) -> str:
    marcas = [
        m for m in ooxml.runs(doc) if PLACEHOLDER_IMAGEN in ooxml.run_text(m.group(0))
    ]
    if len(marcas) != len(IMAGENES):
        msg = f"template drift: expected {len(IMAGENES)} image placeholders"
        raise ValueError(msg)
    edits = [
        (m.start(), m.end(), _tag(f"{{{{ {nombre} }}}}"))
        for m, nombre in zip(marcas, IMAGENES, strict=True)
    ]
    return ooxml.splice(doc, edits)


def convertir(origen: bytes) -> bytes:
    """The docxtpl template for an anonymised PLT-01 Word file.

    Raises:
        ValueError: The template does not have the expected structure.
        KeyError: A merge field or marker has no source in CAMPOS/MARCADORES.
    """
    parts = ooxml.read_docx(origen)
    doc = parts["word/document.xml"].decode()
    for paso in (
        _aceptar_revisiones,
        _filas_servicio,
        _primero,
        _unidad_sii,
        _campos,
        _marcadores,
        _imagenes,
    ):
        doc = paso(doc)
    if "MERGEFIELD" in doc or re.search(r"«[^»]*»", ooxml.text(doc)):
        msg = "template drift: a merge field or marker was left unconverted"
        raise ValueError(msg)
    parts["word/document.xml"] = doc.encode()
    return ooxml.write_docx(parts)
