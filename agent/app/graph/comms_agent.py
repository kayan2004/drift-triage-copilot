from pathlib import Path

import anthropic
import structlog
from pydantic import ValidationError

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


async def comms_agent_node(state: InvestigationState) -> dict:
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

    client: anthropic.AsyncAnthropic = state["llm_client"]
    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        report = CommsReport.model_validate_json(raw)
    except (anthropic.APIError, anthropic.APIConnectionError, ValidationError) as exc:
        log.error("comms_agent.llm_error", error=str(exc))
        report = _fallback_report(event, action)
        raw = f"fallback due to error: {exc}"

    log.info(
        "comms_agent.complete",
        investigation_id=state["investigation_id"],
        status=report.investigation_status,
    )

    return {
        "comms_result": report,
        "messages": [{"role": "comms_agent", "content": raw}],
    }


def _fallback_report(event, action) -> CommsReport:
    chosen = action.chosen_action if action else "monitor_only"
    status = "resolved" if chosen == "monitor_only" else "escalated"
    return CommsReport(
        summary=f"Drift event ({event.severity}) detected on {event.model_name} v{event.model_version}.",
        actions_taken=[chosen] if chosen != "monitor_only" else [],
        next_steps="Monitor model performance and check queue for job status.",
        investigation_status=status,
    )
