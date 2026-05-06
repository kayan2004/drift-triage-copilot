"""Snapshot trajectory tests for the LangGraph supervisor.

LLM calls are fully mocked — no API key required.
No checkpointer used in tests — routing logic doesn't need persistence.
Redis enqueue is mocked — no Redis required.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.errors import GraphInterrupt

from app.graph.graph import build_graph
from app.schemas.webhook import DriftWebhookPayload

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _make_llm_mock(fixture: dict) -> MagicMock:
    """Return an AsyncAnthropic-like mock that serves fixture responses in order."""
    responses = [
        fixture["triage_llm_response"],
        fixture["action_llm_response"],
        fixture["comms_llm_response"],
    ]
    call_count = {"n": 0}

    async def fake_create(**kwargs):  # noqa: ARG001
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        content_text = json.dumps(responses[idx])
        msg = MagicMock()
        msg.content = [MagicMock(text=content_text)]
        return msg

    client = MagicMock()
    client.messages.create = fake_create
    return client


def _make_state_and_config(fixture: dict, llm_mock: MagicMock) -> tuple[dict, dict]:
    event = DriftWebhookPayload(**fixture["input_event"])
    redis_mock = AsyncMock()
    redis_mock.sadd = AsyncMock(return_value=1)
    redis_mock.expire = AsyncMock(return_value=True)
    redis_mock.lpush = AsyncMock(return_value=1)
    state = {
        "drift_event": event,
        "triage_result": None,
        "action_decision": None,
        "hil_approved": False,
        "hil_token": None,
        "comms_result": None,
        "investigation_id": event.event_id,
        "messages": [],
    }
    # Singletons go in config["configurable"] — not in state — so they are never
    # serialized by the checkpointer (even though tests run without one).
    config = {
        "configurable": {
            "llm_client": llm_mock,
            "redis_client": redis_mock,
        }
    }
    return state, config


async def _run_graph_collect(fixture: dict) -> dict:
    """Run graph without checkpointer, collect state updates, return merged state."""
    builder = build_graph()
    graph = builder.compile()  # no checkpointer — routing logic doesn't need persistence

    llm_mock = _make_llm_mock(fixture)
    state, config = _make_state_and_config(fixture, llm_mock)

    collected: dict = dict(state)
    with patch("app.graph.triage_agent.fetch_drift_report", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"severity": state["drift_event"].severity}
        try:
            async for chunk in graph.astream(state, config=config):
                for node_output in chunk.values():
                    if isinstance(node_output, dict):
                        collected.update(node_output)
        except GraphInterrupt:
            pass  # expected for HIL path — state captured up to interrupt

    return collected


@pytest.mark.asyncio
async def test_critical_drift_routes_to_hil() -> None:
    """Critical severity: triage → action → INTERRUPT for HIL. Never skips triage."""
    fixture = _load("critical_drift")
    state = await _run_graph_collect(fixture)

    assert state.get("triage_result") is not None, "triage must run"
    assert state.get("action_decision") is not None, "action must run"

    action = state["action_decision"]
    assert action.requires_human_approval is True, "critical action must require HIL"
    assert action.chosen_action == fixture["expected"]["chosen_action"]
    assert state.get("triage_result").urgency == fixture["expected"]["triage_urgency"]
    # comms should NOT have run — graph interrupted at HIL
    assert state.get("comms_result") is None, "comms must not run before HIL approval"


@pytest.mark.asyncio
async def test_warn_drift_auto_dispatches_without_hil() -> None:
    """Warn severity: triage → action (no HIL) → comms → END."""
    fixture = _load("warn_drift")
    state = await _run_graph_collect(fixture)

    assert state.get("triage_result") is not None
    assert state.get("action_decision") is not None

    action = state["action_decision"]
    assert action.requires_human_approval is False, "warn action must not require HIL"
    assert action.chosen_action == fixture["expected"]["chosen_action"]
    assert state.get("comms_result") is not None, "comms must complete for non-HIL path"


@pytest.mark.asyncio
async def test_ok_drift_resolves_immediately() -> None:
    """Ok severity: triage → monitor_only action → comms → END. No queue job."""
    fixture = _load("ok_drift")
    state = await _run_graph_collect(fixture)

    assert state.get("triage_result") is not None
    assert state.get("action_decision") is not None

    action = state["action_decision"]
    assert action.chosen_action == "monitor_only"
    assert action.requires_human_approval is False
    assert action.queue_job_id is None, "monitor_only must not enqueue a job"
    assert state.get("comms_result") is not None
    assert state["comms_result"].investigation_status == "resolved"


@pytest.mark.asyncio
async def test_supervisor_always_runs_triage_first() -> None:
    """Supervisor must route to triage_agent before action_agent on a fresh event."""
    fixture = _load("critical_drift")
    builder = build_graph()
    graph = builder.compile()  # no checkpointer

    call_order: list[str] = []

    async def recording_create(**kwargs):  # noqa: ARG001
        content = (kwargs.get("messages") or [{}])[-1].get("content", "")
        if "PSI" in content or "Chi2" in content or "drift" in content.lower():
            call_order.append("triage")
            return MagicMock(content=[MagicMock(text=json.dumps(fixture["triage_llm_response"]))])
        call_order.append("action_or_comms")
        return MagicMock(content=[MagicMock(text=json.dumps(fixture["action_llm_response"]))])

    llm_mock = MagicMock()
    llm_mock.messages.create = recording_create
    state, config = _make_state_and_config(fixture, llm_mock)

    with patch("app.graph.triage_agent.fetch_drift_report", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {}
        try:
            async for _ in graph.astream(state, config=config):
                pass
        except GraphInterrupt:
            pass

    assert len(call_order) >= 1, "at least one LLM call must happen"
    assert call_order[0] == "triage", "triage must be called before action"
