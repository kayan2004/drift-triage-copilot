"""Demo-only route — clears investigations and LangGraph checkpoints."""
from typing import Any

import structlog
from fastapi import APIRouter, Request
from sqlalchemy import text

log = structlog.get_logger()
router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/reset", status_code=200)
async def reset_demo(request: Request) -> dict[str, Any]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        await session.execute(text("DELETE FROM investigations"))
        # Clear LangGraph checkpoint tables so threads don't resume stale state
        await session.execute(text("DELETE FROM checkpoint_writes"))
        await session.execute(text("DELETE FROM checkpoint_blobs"))
        await session.execute(text("DELETE FROM checkpoints"))
        await session.commit()

    log.info("demo.reset", tables=["investigations", "checkpoints"])
    return {"status": "ok", "cleared": ["investigations", "checkpoints"]}
