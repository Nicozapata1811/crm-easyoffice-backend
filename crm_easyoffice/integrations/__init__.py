"""Adapters for external services, behind interfaces this project owns.

Responsibility
    Defines the ``SignatureProvider`` and ``PaymentProvider`` contracts and
    their implementations. The signature provider's credentials are not
    available yet and the payment provider has not been chosen, so the only
    implementations here are simulated ones satisfying the same contract.

Dependencies
    May depend on: ``core``.
    Must not depend on: ``clientes``, ``inmuebles``, ``tramites``,
    ``documentos``, ``migracion``. This app is an adapter layer; the domain
    depends on it, not the other way round.

Note
    Provider SDKs are never imported outside this app. That rule is what makes
    the provider replaceable once the company decides.
"""
