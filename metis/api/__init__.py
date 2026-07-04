"""Optional local FastAPI server for Metis (install the ``api`` extra)."""
try:
    from .server import app, create_app
    __all__ = ["app", "create_app"]
except Exception:  # fastapi not installed
    __all__ = []
