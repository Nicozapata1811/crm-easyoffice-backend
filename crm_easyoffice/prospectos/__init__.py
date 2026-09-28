"""Leads: people who asked about a service before becoming clients.

Responsibility
    Owns ``Prospecto`` and the inbound webhook that creates one from each
    submission of Easy Office's public website forms, de-duplicated, with the
    original payload kept.

Dependencies
    May depend on: ``core``, ``clientes`` (a converted lead links to its
    ``Cliente``), ``tramites`` (the service catalogue), ``integrations``
    (source adapters).
    Must not depend on: ``documentos``, ``migracion``.
"""
