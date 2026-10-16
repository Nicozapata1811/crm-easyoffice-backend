"""Adapters for external services, behind interfaces this project owns.

Responsibility
    Defines the ``SignatureProvider``, ``PaymentProvider`` and ``PdfConverter``
    contracts and their implementations. The signature provider's credentials
    are not available yet and the payment provider has not been chosen, so
    simulated implementations satisfy the same contracts. PDF conversion uses
    Gotenberg (LibreOffice in its own container).

Dependencies
    May depend on: ``core``.
    Must not depend on: ``clientes``, ``inmuebles``, ``tramites``,
    ``documentos``, ``migracion``. This app is an adapter layer; the domain
    depends on it, not the other way round.

Note
    Provider SDKs are never imported outside this app. That rule is what makes
    the provider replaceable once the company decides.
"""
