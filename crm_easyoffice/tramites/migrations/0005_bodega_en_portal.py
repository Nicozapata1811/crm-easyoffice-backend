from django.db import migrations

# ``canal`` becomes ``canales``: a case type may be started in several places.
# The bodega is now sold in the portal by plan as well as started by an
# executive, who picks the same plans.
# ASSUMPTION: pending validation with Easy Office. Only a case the client
# files in the portal is paid online (requiere_pago lists the channels); a
# case an executive starts is paid outside the platform, as backoffice
# contracts are today. The bodega plan also pays the domicile line
# (incluido_en_plan), and only company clients may file it.
BODEGA = {
    "planes": True,
    "requiere_pago": ["portal"],
    "canales": ["portal", "backoffice"],
}


def _a_canales(configuracion: dict) -> None:
    canal = configuracion.pop("canal", None)
    configuracion.setdefault("canales", [canal] if canal else [])


def seed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    for tipo in TipoTramite.objects.all():
        _a_canales(tipo.configuracion)
        if tipo.codigo == "bodega":
            tipo.configuracion.update(BODEGA)
            tipo.configuracion.pop("duracion_por_defecto", None)
            for linea in tipo.configuracion.get("lineas", []):
                if linea.get("servicio") == "domicilio-tributario":
                    linea["incluido_en_plan"] = True
        tipo.save(update_fields=["configuracion"])


def unseed(apps, schema_editor):
    TipoTramite = apps.get_model("tramites", "TipoTramite")
    for tipo in TipoTramite.objects.all():
        configuracion = tipo.configuracion
        canales = configuracion.pop("canales", [])
        configuracion["canal"] = canales[-1] if canales else ""
        if tipo.codigo == "bodega":
            configuracion.update(
                {"planes": False, "requiere_pago": False, "duracion_por_defecto": 12},
            )
            for linea in configuracion.get("lineas", []):
                linea.pop("incluido_en_plan", None)
        tipo.save(update_fields=["configuracion"])


class Migration(migrations.Migration):
    dependencies = [
        ("tramites", "0004_tipo_bodega"),
        ("ventas", "0013_seed_planes_bodega"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
