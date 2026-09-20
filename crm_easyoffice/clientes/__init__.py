"""Client records: natural persons, companies and legal representation.

Responsibility
    Owns ``Persona``, ``Empresa`` and ``RepresentanteLegal`` as three distinct
    entities. A contract is signed by a company's legal representative, not by
    "the client", and that representation is valid for a defined period.

Dependencies
    May depend on: ``core``.
    Must not depend on: ``tramites``, ``documentos``, ``inmuebles``,
    ``migracion``. A client record is meaningful without any case attached to
    it; the dependency runs the other way.
"""
