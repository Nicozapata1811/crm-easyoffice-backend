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

The steps PLT-02 shares live in conversion.comun.
"""

from __future__ import annotations

from . import comun
from . import ooxml

# Merge field → context path; documentos.plt01.contexto builds the context.
CAMPOS = {
    **comun.CAMPOS_COMUNES,
    "DURACIÓN": "duracion",
    "ROL_PROPIEDAD": "sucursal.rol",
}

# Plain-text markers left by the anonymisation. The authoriser is a company
# acting through its representative.
MARCADORES = {
    **comun.MARCADORES_EO,
    "AUTORIZANTE_RAZON_SOCIAL": "autorizante.razon_social",
    "AUTORIZANTE_RUT": "autorizante.rut",
    "AUTORIZANTE_REPRESENTANTE": "autorizante.representante",
    "AUTORIZANTE_REP_NACIONALIDAD": "autorizante.nacionalidad",
    "AUTORIZANTE_REP_ESTADO_CIVIL": "autorizante.estado_civil",
    "AUTORIZANTE_REP_PROFESION": "autorizante.profesion",
    "AUTORIZANTE_REP_RUT": "autorizante.rut_representante",
}


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
            (
                unidad.start,
                unidad.end,
                comun.tag("{{ sucursal.unidad_sii }}", unidad.rpr),
            ),
            (
                municipalidad.start,
                municipalidad.end,
                comun.tag("{{ sucursal.municipalidad }}", municipalidad.rpr),
            ),
        ],
    )
    texto = ooxml.drop_runs_before(texto, unidad.start, [" SAN ANTONIO", " "])
    texto = ooxml.set_run_text(texto, ", UNIDAD DE", ", ")
    return doc[: parrafo.start()] + texto + doc[parrafo.end() :]


def convertir(origen: bytes) -> bytes:
    """The docxtpl template for an anonymised PLT-01 Word file.

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
            _unidad_sii,
            comun.campos(CAMPOS),
            comun.marcadores(MARCADORES),
            comun.imagenes,
        ],
    )
