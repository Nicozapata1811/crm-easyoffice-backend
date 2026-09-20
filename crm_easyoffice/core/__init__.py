"""Cross-cutting foundations: users, roles, permissions and the audit log.

Responsibility
    Owns authentication and authorisation primitives, the role and permission
    model, and the append-only audit log that records who changed what and
    when.

Dependencies
    May depend on: nothing. ``core`` is the base of the dependency graph and
    every other app is allowed to depend on it.
    Must not depend on: any other app in this project. A dependency pointing
    out of ``core`` means the concept belongs in the app that owns it.
"""
