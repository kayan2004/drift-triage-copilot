from pathlib import Path
from typing import Annotated, Any

import structlog
from langgraph.graph import END
from langgraph.types import interrupt
from typing_extensions import TypedDict

from app.schemas.tool_io import ActionDecision, CommsReport, TriageAssessment
from app.schemas.webhook import DriftWebhookPayload

log = structlog.get_logger()


def load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


SUPERVISOR_PROMPT = load_prompt("supervisor")


class InvestigationState(TypedDict):
    drift_event: DriftWebhookPayload
    triage_result: TriageAssessment | None
    action_decision: ActionDecision | None
    hil_approved: bool
    hil_token: str | None
    comms_result: CommsReport | None
    investigation_id: str
    # llm_client and redis_client are passed via config["configurable"] — never in state
    # because AsyncPostgresSaver cannot serialize them.
    messages: Annotated[list[Any], lambda a, b: a + b]


# ---------------------------------------------------------------------------
# Routing logic — pure functions, easy to snapshot-test
# ---------------------------------------------------------------------------

def route_after_supervisor(state: InvestigationState) -> str:
    """Decide next node from current state."""
    if state.get("comms_result") is not None:
        return END

    if state.get("action_decision") is not None:
        action: ActionDecision = state["action_decision"]
        if action.requires_human_approval and not state.get("hil_approved"):
            # Pause — dashboard HIL inbox will resume us
            return "await_hil"
        return "comms_agent"

    if state.get("triage_result") is not None:
        return "action_agent"

    return "triage_agent"


# ---------------------------------------------------------------------------
# Supervisor node
# ---------------------------------------------------------------------------

async def supervisor_node(state: InvestigationState) -> dict:
    log.info(
        "supervisor.routing",
        investigation_id=state["investigation_id"],
        has_triage=state.get("triage_result") is not None,
        has_action=state.get("action_decision") is not None,
        hil_approved=state.get("hil_approved"),
        has_comms=state.get("comms_result") is not None,
    )
    return {}


# ---------------------------------------------------------------------------
# HIL interrupt node
# ---------------------------------------------------------------------------

async def await_hil_node(state: InvestigationState) -> dict:
    log.info(
        "supervisor.hil_interrupt",
        investigation_id=state["investigation_id"],
        proposed_action=(
            state["action_decision"].chosen_action
            if state.get("action_decision")
            else None
        ),
    )
    # LangGraph interrupt — execution pauses here until resumed with hil_approved=True
    interrupt("Awaiting human approval before dispatching action to queue.")
    return {}

