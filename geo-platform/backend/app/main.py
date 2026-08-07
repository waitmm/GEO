from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.api.v0 import router
from app.core.config import get_settings
from app.core.database import init_db
from app.modules.analytics.api import router as analytics_router
from app.modules.monitoring.api import router as monitoring_router
from app.modules.optimization.api import router as optimization_router


settings = get_settings()
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(router)
app.include_router(monitoring_router)
app.include_router(analytics_router)
app.include_router(optimization_router)

# 托管前端构建产物（SPA 模式）
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str, request: Request):
        index_path = FRONTEND_DIST / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"detail": "Frontend not found"}
else:
    @app.get("/")
    async def no_frontend():
        return {"message": "Frontend not built. Run: cd frontend && npm run build"}
