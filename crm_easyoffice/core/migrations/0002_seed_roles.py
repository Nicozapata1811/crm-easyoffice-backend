from django.contrib.auth.management import create_permissions
from django.db import migrations
from django.db.models import Q

ADMINISTRADOR = "Administrador"
EJECUTIVO = "Ejecutivo"
APPS_WITH_PERMISSIONS = ("auth", "core", "users", "clientes", "inmuebles")


def ensure_permissions(apps):
    # Permissions are normally created post_migrate, too late for a fresh
    # database; the stub app configs need models_module set to be processed.
    for label in APPS_WITH_PERMISSIONS:
        app_config = apps.get_app_config(label)
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None


def seed_roles(apps, schema_editor):
    ensure_permissions(apps)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    administrador, _ = Group.objects.get_or_create(name=ADMINISTRADOR)
    administrador.permissions.add(
        *Permission.objects.filter(
            Q(content_type__app_label__in=["clientes", "inmuebles"])
            | Q(content_type__app_label="users", content_type__model="user")
            | Q(content_type__app_label="auth", content_type__model="group")
            | Q(content_type__app_label="core", codename="view_dashboard"),
        ),
    )

    # ASSUMPTION: pending validation with Easy Office. RN-32 does not say
    # whether an Ejecutivo sees the dashboard or edits offices; both are withheld.
    ejecutivo, _ = Group.objects.get_or_create(name=EJECUTIVO)
    ejecutivo.permissions.add(
        *Permission.objects.filter(
            Q(
                content_type__app_label="clientes",
                codename__regex=r"^(add|change|view)_",
            )
            | Q(content_type__app_label="inmuebles", codename__startswith="view_"),
        ),
    )


def unseed_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=[ADMINISTRADOR, EJECUTIVO]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "__latest__"),
        ("contenttypes", "__latest__"),
        ("core", "0001_initial"),
        ("users", "0001_initial"),
        ("clientes", "0001_initial"),
        ("inmuebles", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_roles, unseed_roles),
    ]
