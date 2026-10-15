from decimal import Decimal

from django.db import migrations

# Payment cycles offered by Easy Office's contract form.
CICLOS = [
    ("unico", "Único", None, 1),
    ("mensual", "Mensual", 1, 2),
    ("trimestral", "Trimestral", 3, 3),
    ("semestral", "Semestral", 6, 4),
    ("anual", "Anual", 12, 5),
]

# Services, prices and descriptions copied word for word from Easy Office's
# contract form (catalogue sheet). Spacing and punctuation are theirs.
DESCRIPCION_DOMICILIO = (
    "*Domicilio. Tributario, postal y comercial *Recepción de correspondencia "
    "fiscal *Escaneo de 1 página diaria de correspondencia fiscal no "
    "acumulable, sin costo *Uso 1 hora semanal de estación de trabajo "
    "*Inicio de actividades"
)
DESCRIPCION_CREACION = (
    "*Constitución empresa en un día, hasta 3 socios  *Obtención de rut  "
    "*Domicilio tributario x 3 meses  * Inicio de actividad ante el SII  "
    "*Inscripción factura electrónica  * Gestión conjunta solicitud cuenta "
    "emprendedor BancoEstado"
)
DESCRIPCION_WEB_MAIL = "*Servicio web mail corporativo 1 GB + dominio x 1 año"

# Every price stays unconfirmed: whether it includes VAT is open (RN-44 says
# yes, the contract annex says "más I.V.A.").
SERVICIOS = [
    {
        "codigo": "domicilio-tributario",
        "nombre": "Domicilio tributario",
        "descripcion": DESCRIPCION_DOMICILIO,
        "precio_base": Decimal(59990),
        "ciclo": "anual",
        # Already sold in the portal; stays there.
        "se_vende_en_portal": True,
        "activo": True,
    },
    {
        "codigo": "creacion-empresas",
        "nombre": "Creación de empresas",
        "descripcion": DESCRIPCION_CREACION,
        "precio_base": Decimal(49990),
        "ciclo": "unico",
        # Company incorporation is out of the MVP portal scope.
        "se_vende_en_portal": False,
        "activo": True,
    },
    {
        "codigo": "web-mail-dominio",
        "nombre": "Web mail + dominio",
        "descripcion": DESCRIPCION_WEB_MAIL,
        "precio_base": Decimal(14990),
        # ASSUMPTION: pending validation with Easy Office. Annual, inferred
        # from "x 1 año" in its description.
        "ciclo": "anual",
        "se_vende_en_portal": False,
        "activo": True,
    },
    {
        # ASSUMPTION: pending validation with Easy Office. The form gives no
        # price, description or cycle, so the service stays inactive until
        # Easy Office provides them.
        "codigo": "contabilidad",
        "nombre": "Contabilidad",
        "descripcion": "",
        "precio_base": None,
        "ciclo": None,
        "se_vende_en_portal": False,
        "activo": False,
    },
]


def seed(apps, schema_editor):
    CicloPago = apps.get_model("ventas", "CicloPago")
    Servicio = apps.get_model("ventas", "Servicio")

    for codigo, nombre, meses, orden in CICLOS:
        CicloPago.objects.get_or_create(
            codigo=codigo,
            defaults={"nombre": nombre, "meses": meses, "orden": orden},
        )

    for datos in SERVICIOS:
        datos = dict(datos)
        ciclo = datos.pop("ciclo")
        valores = {
            **datos,
            "ciclo_pago_default": CicloPago.objects.get(codigo=ciclo) if ciclo else None,
            "precio_incluye_iva": True,
            "precio_confirmado": False,
        }
        servicio = Servicio.objects.filter(codigo=datos["codigo"]).first()
        if servicio is None:
            Servicio.objects.create(**valores)
        elif not servicio.precio_confirmado:
            # Existing rows are updated, never deleted: past sales keep the
            # price copied into their items (RN-08). A confirmed price is
            # left alone.
            for campo, valor in valores.items():
                setattr(servicio, campo, valor)
            servicio.save()


NUEVOS = ["creacion-empresas", "web-mail-dominio", "contabilidad"]


def unseed(apps, schema_editor):
    # Remove the services this migration added, unless something was sold;
    # otherwise reversing 0006 could not make precio_base required again.
    # domicilio-tributario existed before and keeps its updated values.
    Servicio = apps.get_model("ventas", "Servicio")
    Servicio.objects.filter(codigo__in=NUEVOS, items_vendidos__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("ventas", "0006_ciclopago_servicio_catalogo")]

    operations = [migrations.RunPython(seed, unseed)]
