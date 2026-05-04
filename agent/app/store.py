"""In-memory investigation store.

Holds investigation state between the webhook that starts a thread and the
HIL endpoints that resume it.  Replaced by a real DB in a later phase.
"""

import asyncio
from datetime import datetime, timezone

from app.schemas.hil import InvestigationDetail, InvestigationSummary
from app.schemas.webhook import DriftWebhookPayload


class InvestigationStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._store: dict[str, InvestigationDetail] = {}

    async def create(self, event: DriftWebhookPayload, investigation_id: str) -> InvestigationDetail:
        now = datetime.now(timezone.utc)
        detail = InvestigationDetail(
            investigation_id=investigation_id,
            event_id=event.event_id,
            severity=event.severity,
            model_name=event.model_name,
            model_version=event.model_version,
            status="open",
            started_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._store[investigation_id] = detail
        return detail

    async def get(self, investigation_id: str) -> InvestigationDetail | None:
        return self._store.get(investigation_id)

    async def update_status(
        self,
        investigation_id: str,
        status: str,
        triage_summary: str | None = None,
        proposed_action: str | None = None,
        hil_token: str | None = None,
        messages: list[dict] | None = None,
    ) -> None:
        async with self._lock:
            detail = self._store.get(investigation_id)
            if detail is None:
                return
            updates: dict = {"status": status, "updated_at": datetime.now(timezone.utc)}
            if triage_summary is not None:
                updates["triage_summary"] = triage_summary
            if proposed_action is not None:
                updates["proposed_action"] = proposed_action
            if hil_token is not None:
                updates["hil_token"] = hil_token
            if messages is not None:
                updates["messages"] = detail.messages + messages
            self._store[investigation_id] = detail.model_copy(update=updates)

    async def list_all(self, status: str | None = None) -> list[InvestigationSummary]:
        async with self._lock:
            items = list(self._store.values())
        if status:
            items = [i for i in items if i.status == status]
        return [InvestigationSummary(**i.model_dump()) for i in items]
