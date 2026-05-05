from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings as _get_settings
from app.services.model_loader import ModelBundle


def get_settings() -> Settings:
    return _get_settings()


def get_model(request: Request) -> ModelBundle:
    return request.app.state.model_bundle


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    async with request.app.state.session_factory() as session:
        yield session
