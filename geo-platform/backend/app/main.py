from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v0 import router
from app.core.config import get_settings
from app.core.database import init_db
from app.modules.analytics.api import router as analytics_router
from app.modules.monitoring.api import router as monitoring_router


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
