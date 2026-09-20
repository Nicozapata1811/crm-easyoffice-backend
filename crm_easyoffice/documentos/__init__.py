"""Versioned templates, generated documents and their integrity hashes.

Responsibility
    Owns ``PlantillaDocumento`` with immutable versions, and ``Documento``,
    which points at the exact template version it was generated from and
    carries a frozen snapshot of the data used. Also owns the SHA-256 hash of
    the generated file and of the signed file returned by the provider.

Dependencies
    May depend on: ``core``, ``clientes``, ``inmuebles``, ``tramites``,
    ``integrations``.
    Must not depend on: ``migracion``.

Note
    Generation is slow and signing calls an external service. Neither belongs
    in a request cycle; both run as Celery tasks.
"""
