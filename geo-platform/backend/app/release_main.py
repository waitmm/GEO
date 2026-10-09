from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api.release_catalog import router as catalog_router
from app.core.config import get_settings
from app.core.release_database import release_engine
from app.core.release_worker_lifecycle import worker_status
from app.core.release_access import install_access, require_project_access
from app.modules.single_prompt_v2.release_api import router as single_prompt_router
from app.modules.single_prompt_v2.observation_api import router as observation_router
from app.release_schema import validate_release_database


settings = get_settings()


def create_release_app(*, validate_on_startup: bool = True) -> FastAPI:
    app = FastAPI(title=f"{settings.app_name} 1.0")
    app.state.release_database_status = None
    install_access(app, settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        if validate_on_startup:
            app.state.release_database_status = validate_release_database(release_engine)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "mode": "release_1_0_first_slice", "worker": worker_status(release_engine)}

    @app.get("/api/release/status", dependencies=[Depends(require_project_access)])
    def release_status() -> dict:
        return app.state.release_database_status or validate_release_database(release_engine)

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def private_robots():
        return "User-agent: *\nDisallow: /\n"

    for router in (catalog_router, single_prompt_router, observation_router):
        app.include_router(router, dependencies=[Depends(require_project_access)])

    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str, request: Request):
            if full_path not in {"", "index.html"}:
                raise HTTPException(status_code=404, detail="Release route not found")
            index_path = frontend_dist / "index.html"
            return FileResponse(str(index_path)) if index_path.exists() else {"detail": "Frontend not found"}

    return app


app = create_release_app()
