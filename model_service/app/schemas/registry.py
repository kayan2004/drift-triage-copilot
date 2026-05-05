from datetime import datetime

from pydantic import BaseModel


class ModelVersionInfo(BaseModel):
    model_config = {"from_attributes": True}

    version: str
    alias: str | None
    model_hash: str
    is_active: bool
    registered_at: datetime


class PromotionRequest(BaseModel):
    version: str
