from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Numeric features
    age: int = Field(..., ge=18, le=100)
    campaign: int = Field(..., ge=1)
    previous: int = Field(..., ge=0)
    pdays_contacted: int = Field(..., ge=0, le=1)
    emp_var_rate: float
    cons_price_idx: float
    cons_conf_idx: float
    euribor3m: float
    nr_employed: float

    # Categorical features
    job: str
    marital: str
    education: str
    default: str
    housing: str
    loan: str
    contact: str
    month: str
    day_of_week: str
    poutcome: str


class PredictionResponse(BaseModel):
    prediction_id: str
    label: Literal["subscribed", "not_subscribed"]
    probability: float
    model_version: str
    threshold: float
