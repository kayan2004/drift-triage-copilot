from pydantic import BaseModel


class ModelVersionInfo(BaseModel):
    version: str
    aliases: list[str]
    run_id: str
    model_hash: str
    training_date: str
    test_auc: float
    test_recall: float
    threshold: float


class PromotionRequest(BaseModel):
    pass
