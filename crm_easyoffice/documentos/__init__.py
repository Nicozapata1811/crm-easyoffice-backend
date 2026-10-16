"""Versioned templates, generated documents and their integrity hashes.

Responsibility
    Owns ``PlantillaDocumento`` with immutable versions, and ``Documento``,
    which points at the exact template version it was generated from and
    carries a frozen snapshot of the data used. Also owns the SHA-256 hash of
    the generated file and of the signed file (uploaded by an executive while
    signing is assisted). Generates PLT-01 with docxtpl from a template
    converted once (conversion/), and its PDF through integrations.pdf.

Dependencies
    May depend on: ``core``, ``clientes``, ``inmuebles``, ``configuracion``,
    ``tramites``, ``integrations``. Generation starts when ``tramites`` sends
    ``documento_requerido``.
    Must not depend on: ``migracion``.

Note
    Generation is slow and signing calls an external service. Neither belongs
    in a request cycle; both run as Celery tasks.
"""
