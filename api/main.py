"""FastAPI application entrypoint for the clinical knowledge admin console."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes.admin import router as admin_router
from core.config import get_settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "admin" / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Consola de conocimiento clínico",
        description="Administración hot-reload de la base RAG postoperatoria.",
        version="0.1.0",
    )
    app.include_router(admin_router, prefix="/admin")
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="admin-ui")
    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
