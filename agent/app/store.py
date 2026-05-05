"""DB-backed investigation store.

Same interface as the old in-memory store — callers don't change.
Survives agent restarts because state lives in Postgres.
"""
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Investigation
from app.schemas.hil import InvestigationDetail, InvestigationSummary
from app.schemas.webhook import DriftWebhookPayload

log = structlog.get_logger()


class InvestigationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    async def create(
        self, event: DriftWebhookPayload, investigation_id: str
    ) -> InvestigationDetail:
        now = datetime.now(UTC)
        row = Investigation(
            investigation_id=investigation_id,
            event_id=event.event_id,
            severity=event.severity,
            model_name=event.model_name,
            model_version=event.model_version,
            status="open",
            started_at=now,
            updated_at=now,
        )
        async with self._factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _to_detail(row)

    async def get(self, investigation_id: str) -> InvestigationDetail | None:
        async with self._factory() as session:
            row = await session.get(Investigation, investigation_id)
        return _to_detail(row) if row else None

    async def update_status(
        self,
        investigation_id: str,
        status: str,
        triage_summary: str | None = None,
        proposed_action: str | None = None,
        hil_token: str | None = None,
        messages: list[dict] | None = None,  # noqa: ARG002 — kept for API compat
    ) -> None:
        values: dict = {"status": status, "updated_at": datetime.now(UTC)}
        if triage_summary is not None:
            values["triage_summary"] = triage_summary
        if proposed_action is not None:
            values["proposed_action"] = proposed_action
        if hil_token is not None:
            values["hil_token"] = hil_token

        async with self._factory() as session:
            await session.execute(
                update(Investigation)
                .where(Investigation.investigation_id == investigation_id)
                .values(**values)
            )
            await session.commit()

        log.info(
            "store.updated",
            investigation_id=investigation_id,
            status=status,
        )

    async def list_all(self, status: str | None = None) -> list[InvestigationSummary]:
        async with self._factory() as session:
            stmt = select(Investigation).order_by(Investigation.started_at.desc())
            if status:
                stmt = stmt.where(Investigation.status == status)
            result = await session.execute(stmt)
            rows = result.scalars().all()
        return [_to_summary(r) for r in rows]


def _to_summary(row: Investigation) -> InvestigationSummary:
    return InvestigationSummary(
        investigation_id=row.investigation_id,
        event_id=row.event_id,
        severity=row.severity,  # type: ignore[arg-type]
        model_name=row.model_name,
        model_version=row.model_version,
        status=row.status,  # type: ignore[arg-type]
        started_at=row.started_at,
        updated_at=row.updated_at,
        triage_summary=row.triage_summary,
        proposed_action=row.proposed_action,
    )


def _to_detail(row: Investigation) -> InvestigationDetail:
    return InvestigationDetail(
        **_to_summary(row).model_dump(),
        hil_token=row.hil_token,
    )
