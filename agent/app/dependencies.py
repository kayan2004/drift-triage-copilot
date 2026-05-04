from typing import Annotated

import anthropic
import redis.asyncio as aioredis
from fastapi import Depends, Request
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import Settings, get_settings


def get_settings_dep() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


async def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


async def get_checkpointer(request: Request) -> AsyncPostgresSaver:
    return request.app.state.checkpointer


async def get_graph(request: Request):  # type: ignore[return]
    return request.app.state.graph


async def get_llm(request: Request) -> anthropic.AsyncAnthropic:
    return request.app.state.llm


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
CheckpointerDep = Annotated[AsyncPostgresSaver, Depends(get_checkpointer)]
GraphDep = Annotated[object, Depends(get_graph)]
LLMDep = Annotated[anthropic.AsyncAnthropic, Depends(get_llm)]
