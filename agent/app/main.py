from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anthropic
import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import get_settings
from app.db.session import make_engine, make_session_factory
from app.graph.graph import build_graph
from app.routes import investigations, queue, webhooks
from app.store import InvestigationStore

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # Anthropic client — singleton, never instantiated inside graph nodes
    app.state.llm = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value()
    )

    # Redis client
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # SQLAlchemy async engine + session factory for investigations table
    engine = make_engine(settings.agent_database_url)
    app.state.session_factory = make_session_factory(engine)
    app.state.engine = engine

    # LangGraph Postgres checkpointer
    # Uses the raw psycopg connection string (strip asyncpg driver prefix)
    pg_conn_str = settings.agent_database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    checkpointer = AsyncPostgresSaver.from_conn_string(pg_conn_str)
    await checkpointer.setup()
    app.state.checkpointer = checkpointer

    # Build compiled graph with checkpointer
    builder = build_graph()
    app.state.graph = builder.compile(checkpointer=checkpointer)

    # DB-backed investigation store — survives restarts
    app.state.store = InvestigationStore(app.state.session_factory)

    log.info("agent.startup.complete", model_service_url=settings.model_service_url)
    yield

    await app.state.redis.aclose()
    await engine.dispose()
    log.info("agent.shutdown.complete")


app = FastAPI(title="Drift Triage — Agent", lifespan=lifespan)

app.include_router(webhooks.router)
app.include_router(investigations.router)
app.include_router(queue.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
