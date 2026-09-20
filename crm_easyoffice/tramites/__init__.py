"""Case types, cases and the state machine that governs them.

Responsibility
    Owns ``TipoTramite`` (configuration describing a kind of service) and
    ``Tramite`` (one case for one client), together with the table of allowed
    state transitions. Transitions are data, not conditionals scattered
    through views.

Dependencies
    May depend on: ``core``, ``clientes``, ``inmuebles``.
    Must not depend on: ``documentos``. This direction is deliberate and stated
    in CLAUDE.md: ``documentos`` may depend on ``tramites``, never the reverse.
    A case must be able to exist and advance before any document is emitted.
"""
