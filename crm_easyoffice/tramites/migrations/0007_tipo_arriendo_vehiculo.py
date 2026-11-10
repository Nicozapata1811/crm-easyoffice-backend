"""The vehicle lease (PLT-03) as a case type, implemented directly (HU-15).

A person leases their own vehicle to their company, the client. Easy Office
is not a party: the case has no Contrato and no folio (``contrato: false``)
and only the parties sign.
"""

from django.db import migrations

ARRIENDO_VEHICULO = {
    "codigo": "arriendo-vehiculo",
    "nombre": "Arriendo de vehículo",
    "configuracion": {
        "servicio": "arriendo-vehiculo",
        "plantilla": "PLT-03",
        "contrato": False,
        # ASSUMPTION: pending validation with Easy Office. An executive
        # starts it; the client follows it in the portal and pays there.
        "canales": ["backoffice"],
        "tipos_cliente": ["empresa"],
        # Paid online after the draft, at the service's list price plus VAT.
        "requiere_pago": ["backoffice"],
        "precio": "lista",
        "requiere_firma": True,
        "firma": {
            "nivel": "asistida",
            "firmantes": ["arrendador", "cliente_representante"],
        },
    },
}


def seed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    datos = dict(ARRIENDO_VEHICULO)
    TipoTramite.objects.get_or_create(codigo=datos.pop("codigo"), defaults=datos)


def unseed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    TipoTramite.objects.filter(
        codigo=ARRIENDO_VEHICULO["codigo"],
        tramites__isnull=True,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tramites", "0006_firma_asistida"),
        ("ventas", "0018_precio_arriendo_vehiculo"),
        ("documentos", "0006_seed_plt03"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
