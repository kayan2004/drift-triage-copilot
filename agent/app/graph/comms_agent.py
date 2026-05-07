from pathlib import Path

import anthropic
import structlog
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from app.graph._json import parse_json_payload
from app.graph.supervisor import InvestigationState
from app.schemas.tool_io import CommsReport

log = structlog.get_logger()


def load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def _parse_system_and_user(prompt_text: str) -> tuple[str, str]:
    parts = prompt_text.split("# USER PROMPT TEMPLATE", 1)
    system = parts[0].replace("# SYSTEM PROMPT", "").strip()
    user_template = parts[1].strip() if len(parts) > 1 else ""
    return system, user_template


COMMS_PROMPT = load_prompt("comms")
SYSTEM_PROMPT, USER_TEMPLATE = _parse_system_and_user(COMMS_PROMPT)


async def comms_agent_node(state: InvestigationState, config: RunnableConfig) -> dict:
    event = state["drift_event"]
    triage = state["triage_result"]
    action = state["action_decision"]

    log.info(
        "comms_agent.start",
        investigation_id=state["investigation_id"],
        action=action.chosen_action if action else None,
    )

    user_prompt = USER_TEMPLATE.format(
        severity=event.severity,
        model_name=event.model_name,
        model_version=event.model_version,
        timestamp=event.timestamp.isoformat(),
        triage_result=triage.model_dump() if triage else {},
        action_decision=action.model_dump() if action else {},
        hil_approved=state.get("hil_approved", False),
    )

    client: anthropic.AsyncAnthropic = config["configurable"]["llm_client"]
    model: str = config["configurable"]["llm_model"]
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        report = parse_json_payload(raw, CommsReport)
    except (anthropic.APIError, anthropic.APIConnectionError, ValidationError) as exc:
        log.error("comms_agent.llm_error", error=str(exc))
        report = _fallback_report(event, action, state.get("hil_approved", False))
        raw = f"fallback due to error: {exc}"

    # Override the LLM's pessimistic status whenever the system has done its
    # job: a queue job was actually dispatched (either by action_agent for
    # non-HIL actions like replay_test, or by the approve endpoint after HIL).
    # The LLM occasionally calls these "escalated" because hil_approved=False,
    # which is wrong for actions that don't need HIL.
    if (
        report.investigation_status != "resolved"
        and action is not None
        and action.queue_job_id is not None
    ):
        log.info(
            "comms_agent.status_override",
            investigation_id=state["investigation_id"],
            llm_status=report.investigation_status,
            override_to="resolved",
            queue_job_id=action.queue_job_id,
        )
        report = report.model_copy(update={"investigation_status": "resolved"})

    log.info(
        "comms_agent.complete",
        investigation_id=state["investigation_id"],
        status=report.investigation_status,
    )

    return {
        "comms_result": report,
        "messages": [{"role": "comms_agent", "content": raw}],
    }


def _fallback_report(event, action, hil_approved: bool = False) -> CommsReport:
    """Rule-based fallback when the comms LLM call fails.

    Status policy:
      - chosen_action == monitor_only        → resolved (nothing to dispatch)
      - real action and HIL approved (or no HIL needed) → resolved (job is in flight)
      - real action without HIL approval     → escalated (something is off,
                                                operator should look at it)
    """
    chosen = action.chosen_action if action else "monitor_only"
    requires_hil = bool(action and action.requires_human_approval)
    if chosen == "monitor_only":
        status: str = "resolved"
    elif not requires_hil or hil_approved:
        status = "resolved"
    else:
        status = "escalated"

    if chosen == "monitor_only":
        actions_taken: list[str] = []
        next_steps = "No remediation needed. Continue monitoring."
    elif status == "resolved":
        actions_taken = [chosen]
        next_steps = (
            f"{chosen} job dispatched to the queue. "
            "Track progress in the queue monitor and verify the new model in MLflow."
        )
    else:
        actions_taken = []
        next_steps = (
            "Investigation escalated for manual review — proposed action requires "
            "human approval that was not granted in this run."
        )

    return CommsReport(
        summary=(
            f"Drift event ({event.severity}) detected on "
            f"{event.model_name} v{event.model_version}. "
            f"Proposed action: {chosen}. "
            f"HIL approved: {hil_approved}."
        ),
        actions_taken=actions_taken,
        next_steps=next_steps,
        investigation_status=status,  # type: ignore[arg-type]
    )
