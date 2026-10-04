"""The multi-user Metis server (install with the ``server`` extra).

Build it with ``create_app``; configure it with ``ServerSettings`` or ``METIS_*`` variables.
"""
from .settings import ServerSettings


def create_app(*args, **kwargs):
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)


__all__ = ["ServerSettings", "create_app"]
