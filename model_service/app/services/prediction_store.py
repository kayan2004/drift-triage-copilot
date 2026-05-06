from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Prediction


async def get_recent_predictions(session: AsyncSession, limit: int) -> list[Prediction]:
    result = await session.execute(
        select(Prediction).order_by(Prediction.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
