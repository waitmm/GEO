from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.release_catalog import router as catalog_router
from app.core.config import get_settings
from app.core.release_database import ReleaseSessionLocal, release_engine
from app.modules.single_prompt_v2.diagnosis import recover_interrupted_diagnoses
from app.modules.single_prompt_v2.citation_contribution import recover_interrupted_citation_contributions
from app.modules.single_prompt_v2.qualification_critic import recover_interrupted_qualification_critics
from app.modules.single_prompt_v2.release_api import router as single_prompt_router
from app.modules.single_prompt_v2.service import recover_interrupted_analyses
from app.modules.single_prompt_v2.source_preparation import recover_interrupted_source_preparations
from app.release_schema import validate_release_database


settings = get_settings()


def create_release_app(*, validate_on_startup: bool = True) -> FastAPI:
    app = FastAPI(title=f"{settings.app_name} 1.0")
    app.state.release_database_status = None
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
        db = ReleaseSessionLocal()
        try:
            recover_interrupted_analyses(db)
            recover_interrupted_diagnoses(db)
            recover_interrupted_citation_contributions(db)
            recover_interrupted_qualification_critics(db)
            recover_interrupted_source_preparations(db)
        finally:
            db.close()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "mode": "release_1_0_first_slice"}

    @app.get("/api/release/status")
    def release_status() -> dict:
        return app.state.release_database_status or validate_release_database(release_engine)

    app.include_router(catalog_router)
    app.include_router(single_prompt_router)

    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str, request: Request):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Release API route not found")
            index_path = frontend_dist / "index.html"
            return FileResponse(str(index_path)) if index_path.exists() else {"detail": "Frontend not found"}

    return app


app = create_release_app()
