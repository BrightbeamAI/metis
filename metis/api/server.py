"""Local FastAPI server. Run: ``uvicorn metis.api.server:app``. Optional component."""
from __future__ import annotations


def create_app():
    from fastapi import FastAPI

    from .routes import router

    application = FastAPI(
        title="Metis",
        description="Governed tacit fragment capture, local-first, CHAP-aligned. "
                    "Tacit memory is exposed only through condition-aware governance gates.",
        version="0.1.0")
    application.include_router(router)
    return application


app = create_app()
