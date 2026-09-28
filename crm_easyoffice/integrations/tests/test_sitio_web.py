import pytest

from crm_easyoffice.integrations.sitio_web.base import UnknownAdapterError
from crm_easyoffice.integrations.sitio_web.generic import GenericAdapter
from crm_easyoffice.integrations.sitio_web.registry import get_adapter


def test_get_adapter_returns_generic_by_name():
    assert isinstance(get_adapter("generico"), GenericAdapter)


def test_get_adapter_rejects_unknown_name():
    with pytest.raises(UnknownAdapterError):
        get_adapter("elementor")


def test_generic_adapter_maps_fields_and_drops_unknown_ones():
    parsed = GenericAdapter().parse(
        {"nombre": "Ana Prueba", "servicio": "domicilio-tributario", "utm_source": "x"},
    )

    assert parsed == {
        "nombre": "Ana Prueba",
        "servicio_interes": "domicilio-tributario",
    }
