"""Template files committed with the code.

``PLT-0N_origen.docx`` is the anonymised template from the evidence repository
(13_plantillas), unchanged; Easy Office authorised publishing them (ACTA-002,
TA-11) and they carry only Easy Office's corporate data and markers.
``PLT-0N_v1.docx`` is its conversion (``manage.py convertir_plantilla``),
loaded as version 1 by the migrations. The backend never reads the evidence
repository at runtime.
"""

from __future__ import annotations

from pathlib import Path

CARPETA = Path(__file__).resolve().parent / "plantillas_semilla"
ORIGEN_PLT01 = CARPETA / "PLT-01_origen.docx"
PLANTILLA_PLT01 = CARPETA / "PLT-01_v1.docx"
ORIGEN_PLT02 = CARPETA / "PLT-02_origen.docx"
PLANTILLA_PLT02 = CARPETA / "PLT-02_v1.docx"

# The converted file each seeded template's version 1 loads.
PLANTILLAS = {"PLT-01": PLANTILLA_PLT01, "PLT-02": PLANTILLA_PLT02}
