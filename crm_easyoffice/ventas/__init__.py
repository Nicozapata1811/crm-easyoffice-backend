"""Sales and online payment.

Responsibility
    Owns the price list (``Servicio``), the sales a client makes, every
    payment attempt sent to the provider, the transactions it confirms and the
    log of webhooks received (HU-38, HU-39, HU-40, HU-57).

Dependencies
    May depend on: ``core``, ``clientes``, ``integrations``.
    Nothing depends on ``ventas``.
"""
