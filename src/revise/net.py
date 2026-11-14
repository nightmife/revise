"""Accès à Internet (HTTPS) avec des certificats qui marchent partout.

Dans l'application empaquetée pour Mac, Python ne trouve pas les certificats du système :
toute connexion HTTPS échoue. On utilise donc ceux du paquet `certifi`, livrés avec l'application."""

from __future__ import annotations

import ssl
import urllib.request
from functools import cache


@cache
def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except (ImportError, OSError):
        return ssl.create_default_context()


def urlopen(req, timeout: float):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())


def reason(e: BaseException) -> str:
    """Cause courte d'une erreur réseau, à montrer à l'utilisateur."""
    return str(getattr(e, "reason", None) or e)
