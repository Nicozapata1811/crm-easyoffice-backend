"""Signals other apps observe; this app never imports them.

``documento_requerido`` is sent, after the transaction commits, with
``tramite`` whenever a case needs its document (re)generated. ``documentos``
listens and generates it in Celery.

``firma_requerida`` is sent, after the transaction commits, with ``tramite``
whenever a case starts waiting for a signature. ``documentos`` listens and,
for an advanced signature, sends the document to the provider in Celery.
"""

from django.dispatch import Signal

documento_requerido = Signal()
firma_requerida = Signal()
