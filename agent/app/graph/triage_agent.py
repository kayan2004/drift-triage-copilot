from pathlib import Path

import anthropic
import structlog
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from app.graph._json import parse_json_payload
from app.graph.supervisor import InvestigationState
from app.schemas.tool_io import ToolError, TriageAssessment
from app.tools.fetch_drift_report import fetch_drift_report

log = structlog.get_logger()


def load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def _parse_system_and_user(prompt_text: str) -> tuple[str, str]:
    parts = prompt_text.split("# USER PROMPT TEMPLATE", 1)
    system = parts[0].replace("# SYSTEM PROMPT", "").strip()
    user_template = parts[1].strip() if len(parts) > 1 else ""
    return system, user_template


TRIAGE_PROMPT = load_prompt("triage")
SYSTEM_PROMPT, USER_TEMPLATE = _parse_system_and_user(TRIAGE_PROMPT)


async def triage_agent_node(state: InvestigationState, config: RunnableConfig) -> dict:
    event = state["drift_event"]
    log.info(
        "triage_agent.start",
        investigation_id=state["investigation_id"],
        severity=event.severity,
        event_id=event.event_id,
    )

    # Fetch full drift report from model service (best-effort — fall back to webhook data)
    full_report = await fetch_drift_report(event.drift_report_id)
    if isinstance(full_report, ToolError):
        log.warning(
            "triage_agent.drift_report_fetch_failed",
            error=full_report.error,
            retryable=full_report.retryable,
        )
        full_report = {}

    user_prompt = USER_TEMPLATE.format(
        timestamp=event.timestamp.isoformat(),
        severity=event.severity,
        previous_severity=event.previous_severity,
        psi_summary=event.psi_summary,
        chi2_summary=event.chi2_summary,
        output_drift=event.output_drift,
        model_name=event.model_name,
        model_version=event.model_version,
    )

    client: anthropic.AsyncAnthropic = config["configurable"]["llm_client"]
    model: str = config["configurable"]["llm_model"]
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        assessment = parse_json_payload(raw, TriageAssessment)
        log.info(
            "triage_agent.complete",
            investigation_id=state["investigation_id"],
            urgency=assessment.urgency,
            recommended_actions=assessment.recommended_actions,
        )
        return {
            "triage_result": assessment,
            "messages": [{"role": "triage_agent", "content": raw}],
        }
    except (anthropic.APIError, anthropic.APIConnectionError, ValidationError) as exc:
        log.error("triage_agent.llm_error", error=str(exc))
        # Fallback: derive a minimal assessment from the webhook data directly
        fallback = _fallback_assessment(event)
        return {
            "triage_result": fallback,
            "messages": [{"role": "triage_agent", "content": f"fallback due to error: {exc}"}],
        }


def _fallback_assessment(event) -> TriageAssessment:
    """Minimal rule-based fallback when LLM call fails."""
    drifting = [f for f, v in event.psi_summary.items() if v > 0.1]
    drifting += [f for f, v in event.chi2_summary.items() if v < 0.05]
    urgency_map = {"critical": "critical", "warn": "medium", "ok": "low"}
    return TriageAssessment(
        drifting_features=drifting or ["unknown"],
        drift_hypothesis="unknown",
        recommended_actions=["replay_test"] if event.severity != "critical" else ["retrain"],
        urgency=urgency_map.get(event.severity, "medium"),
    )
