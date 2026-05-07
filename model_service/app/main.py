from contextlib import asynccontextmanager
from typing import Any

import structlog
import structlog.stdlib
from fastapi import FastAPI

from app.config import get_settings
from app.db.session import make_engine, make_session_factory
from app.routes import demo, drift, predict, registry
from app.services.model_loader import load_model_bundle

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    settings = get_settings()
    app.state.settings = settings
    app.state.engine = make_engine(settings)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.model_bundle = await load_model_bundle(settings)
    log.info(
        "model_service.startup",
        model_version=app.state.model_bundle.model_version,
        threshold=app.state.model_bundle.threshold,
    )
    yield
    await app.state.engine.dispose()
    log.info("model_service.shutdown")


app = FastAPI(title="Drift Triage — Model Service", lifespan=lifespan)

app.include_router(predict.router)
app.include_router(registry.router)
app.include_router(drift.router)
app.include_router(demo.router)


@app.get("/health")
async def health() -> dict[str, Any]:
    bundle = app.state.model_bundle
    return {"status": "ok", "model_version": bundle.model_version}
