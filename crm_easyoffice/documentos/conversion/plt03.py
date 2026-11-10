"""Turn Easy Office's PLT-03 Word template into a docxtpl template.

PLT-03 is a vehicle lease between the vehicle's owner and the client
company; Easy Office is not a party (OB-06). It has no merge fields: the
values are ``[MARKERS]`` typed in the text, each inside one run, and the
signature table ends in ``Label: ____`` blanks. Only those placeholders
change; the legal text stays as Easy Office wrote it.

The two bare lines of the signature table stay: they are where each party
signs.
"""

from __future__ import annotations

from . import comun

# [MARKER] → context path; documentos.plt03.contexto builds the context.
# ASSUMPTION: pending validation with Easy Office. [COMUNA] appears in the
# heading and in the domicile clause and is one value.
MARCADORES = {
    "COMUNA": "comuna",
    "FECHA": "fecha",
    "NOMBRE COMPLETO DEL PROPIETARIO": "arrendador.nombre",
    "RUT": "arrendador.rut",
    "DOMICILIO": "arrendador.domicilio",
    "RAZÓN SOCIAL DE LA EMPRESA": "empresa.razon_social",
    "RUT EMPRESA": "empresa.rut",
    "NOMBRE REPRESENTANTE": "representante.nombre",
    "RUT REPRESENTANTE": "representante.rut",
    "DOMICILIO EMPRESA": "empresa.domicilio",
    "MARCA": "vehiculo.marca",
    "MODELO": "vehiculo.modelo",
    "AÑO": "vehiculo.anio",
    "PATENTE": "vehiculo.patente",
    "COLOR": "vehiculo.color",
    "VIN": "vehiculo.vin",
    "PLAZO": "plazo",
    "FECHA INICIO": "fecha_inicio",
    "FECHA TÉRMINO": "fecha_termino",
    "MONTO": "renta",
    "MONTO EN PALABRAS": "renta_letras",
    "X": "dia_pago",
    "TRANSFERENCIA BANCARIA / OTRO MEDIO": "medio_pago",
}

# The signature table's blanks, in order: the lessor's column, then the
# lessee's, row by row.
FIRMAS = [
    ("Nombre", "arrendador.nombre"),
    ("Razón Social", "empresa.razon_social"),
    ("RUT", "arrendador.rut"),
    ("RUT", "empresa.rut"),
    ("Representante", "representante.nombre"),
    ("RUT representante", "representante.rut"),
]

# What must not survive: a [MARKER] or a labelled blank.
RESTOS = [r"\[[^\]]*\]", r": _+"]


def convertir(origen: bytes) -> bytes:
    """PLT-03 as Easy Office wrote it → the docxtpl template for version 1.

    Raises:
        ValueError: The template does not have the expected structure.
        KeyError: A marker has no source in ``MARCADORES``.
    """
    return comun.convertir(
        origen,
        [comun.corchetes(MARCADORES), comun.rotulos(FIRMAS)],
        RESTOS,
    )
