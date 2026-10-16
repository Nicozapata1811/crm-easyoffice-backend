"""Template files committed with the code.

``PLT-01_origen.docx`` is the anonymised template from the evidence repository
(13_plantillas), unchanged; Easy Office authorised publishing it (ACTA-002,
TA-11) and it carries only Easy Office's corporate data. ``PLT-01_v1.docx`` is
its conversion (``manage.py convertir_plt01``), loaded as version 1 by the
migrations. The backend never reads the evidence repository at runtime.
"""

from __future__ import annotations

from pathlib import Path

CARPETA = Path(__file__).resolve().parent / "plantillas_semilla"
ORIGEN_PLT01 = CARPETA / "PLT-01_origen.docx"
PLANTILLA_PLT01 = CARPETA / "PLT-01_v1.docx"
