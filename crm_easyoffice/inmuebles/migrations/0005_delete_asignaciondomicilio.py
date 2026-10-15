from django.db import migrations


def ensure_no_assignments(apps, schema_editor):
    # Occupancy now comes from contracted services (contratos.services
    # .ocupantes). Existing assignments cannot be turned into contracts
    # automatically, so refuse to drop them silently.
    AsignacionDomicilio = apps.get_model("inmuebles", "AsignacionDomicilio")
    if AsignacionDomicilio.objects.exists():
        msg = (
            "inmuebles.AsignacionDomicilio still has rows. Record them as "
            "contracts (HU-60) or delete them deliberately before migrating."
        )
        raise RuntimeError(msg)


class Migration(migrations.Migration):
    dependencies = [("inmuebles", "0004_permisos_autorizante")]

    operations = [
        migrations.RunPython(ensure_no_assignments, migrations.RunPython.noop),
        migrations.DeleteModel(name="AsignacionDomicilio"),
    ]
