"""Offices and the tax domiciles assigned to them.

Responsibility
    Owns ``Oficina`` with its rol de avaluo (Chilean property tax roll number)
    and address, and the assignment linking a company to the office that serves
    as its registered tax domicile.

Dependencies
    May depend on: ``core``, ``clientes``. The assignment refers to an
    ``Empresa``, so the direction is ``inmuebles`` to ``clientes`` and never
    the reverse.
    Must not depend on: ``tramites``, ``documentos``, ``migracion``.
"""
