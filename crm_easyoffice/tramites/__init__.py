"""Case types, cases and the state machine that governs them.

Responsibility
    Owns ``TipoTramite`` (configuration describing a kind of service) and
    ``Tramite`` (one case for one client), together with the table of allowed
    state transitions. Transitions are data, not conditionals scattered
    through views.

Dependencies
    May depend on: ``core``, ``clientes``, ``inmuebles``, ``configuracion``,
    ``contratos`` and ``ventas``: a case links the contract and the sale it
    produced (MD-10), which stay unaware of cases. It reacts to a paid sale
    through ``ventas.services.venta_pagada``.
    Must not depend on: ``documentos``. This direction is deliberate and stated
    in CLAUDE.md: ``documentos`` may depend on ``tramites``, never the reverse.
    A case must be able to exist and advance before any document is emitted.
"""
