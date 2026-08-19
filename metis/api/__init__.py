"""Optional local FastAPI server for Metis (install the ``api`` extra)."""
try:
    from .server import app, create_app
    __all__ = ["app", "create_app"]
except ImportError:  # the optional `api` extra (FastAPI) is not installed
    __all__ = []
