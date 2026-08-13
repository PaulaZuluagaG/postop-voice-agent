"""FastAPI application entrypoint for the clinical knowledge admin console."""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes.admin import router as admin_router
from core.config import Settings, get_settings
from core.paths import project_root
from knowledge.ingest.shared_embedder import warmup_embedding_service

STATIC_DIR = project_root() / "apps" / "admin-ui"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app = FastAPI(
        title="Consola de conocimiento clínico",
        description="Administración hot-reload de la base RAG postoperatoria.",
        version="0.1.0",
    )

    @app.on_event("startup")
    async def warm_ingest_runtime() -> None:
        if not app_settings.ingest_warmup_on_start:
            return
        import asyncio

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, warmup_embedding_service, app_settings)

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
