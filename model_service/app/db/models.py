import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Enum as SAEnum, Float, Integer, String, Text
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SeverityEnum(str, enum.Enum):
    ok = "ok"
    warn = "warn"
    critical = "critical"


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    input_features: Mapped[dict] = mapped_column(JSON, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    label: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)


class DriftReport(Base):
    __tablename__ = "drift_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    window_start: Mapped[datetime] = mapped_column(nullable=False)
    window_end: Mapped[datetime] = mapped_column(nullable=False)
    severity: Mapped[SeverityEnum] = mapped_column(
        SAEnum(SeverityEnum, name="severity_enum"), nullable=False
    )
    psi_scores: Mapped[dict] = mapped_column(JSON, nullable=True)
    chi2_scores: Mapped[dict] = mapped_column(JSON, nullable=True)
    output_drift: Mapped[float] = mapped_column(Float, nullable=True)
    raw_report: Mapped[dict] = mapped_column(JSON, nullable=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    alias: Mapped[str | None] = mapped_column(String(64), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    model_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
