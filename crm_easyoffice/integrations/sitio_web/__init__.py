"""Inbound adapters for submissions from Easy Office's public website.

Each source posts its own payload shape. An adapter maps it onto the canonical
field names of ``ProspectoEntrante``; validation and storage are shared and
live in the ``prospectos`` app.
"""
