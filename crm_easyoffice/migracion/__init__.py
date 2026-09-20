"""One-off import pipeline from the company's Excel records into PostgreSQL.

Responsibility
    Reads the spreadsheet the company currently keeps its client records in,
    validates and maps rows onto the domain model, and reports what could not
    be imported.

Dependencies
    May depend on: ``core``, ``clientes``, ``inmuebles``.
    Must not depend on: ``tramites``, ``documentos``. Nothing may depend on
    ``migracion``; it is a leaf and is expected to be retired once the import
    has run.

Note
    The source file holds real client data. It is anonymised before entering
    any environment, and neither the file nor any extract from it is ever
    committed.
"""
