"""Signals other apps observe; this app never imports them.

``documento_requerido`` is sent, after the transaction commits, with
``tramite`` whenever a case needs its document (re)generated. ``documentos``
listens and generates it in Celery.
"""

from django.dispatch import Signal

documento_requerido = Signal()
