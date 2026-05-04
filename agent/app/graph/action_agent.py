import uuid
from datetime import UTC, datetime
from pathlib import Path

import anthropic
import structlog
from pydantic import ValidationError

from app.graph.supervisor import InvestigationState
from app.queue.producer import enqueue_job
from app.schemas.tool_io import ActionDecision, QueueJob

log = structlog.get_logger()

PRODUCTION_ACTIONS = {"retrain", "rollback"}


def load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / f"{name}.md").read_text()


def _parse_system_and_user(prompt_text: str) -> tuple[str, str]:
    parts = prompt_text.split("# USER PROMPT TEMPLATE", 1)
    system = parts[0].replace("# SYSTEM PROMPT", "").strip()
    user_template = parts[1].strip() if len(parts) > 1 else ""
    return system, user_template


ACTION_PROMPT = load_prompt("action")
SYSTEM_PROMPT, USER_TEMPLATE = _parse_system_and_user(ACTION_PROMPT)


async def action_agent_node(state: InvestigationState) -> dict:
    triage = state["triage_result"]
    hil_approved = state.get("hil_approved", False)

    log.info(
        "action_agent.start",
        investigation_id=state["investigation_id"],
        hil_approved=hil_approved,
        recommended_actions=triage.recommended_actions,
    )

    user_prompt = USER_TEMPLATE.format(
        drifting_features=triage.drifting_features,
        drift_hypothesis=triage.drift_hypothesis,
        recommended_actions=triage.recommended_actions,
        urgency=triage.urgency,
        hil_approved=hil_approved,
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
        decision = ActionDecision.model_validate_json(raw)
    except (anthropic.APIError, anthropic.APIConnectionError, ValidationError) as exc:
        log.error("action_agent.llm_error", error=str(exc))
        decision = _fallback_decision(triage, hil_approved)
        raw = f"fallback due to error: {exc}"

    # Enforce: Production-touching actions always require HIL regardless of LLM output
    if decision.chosen_action in PRODUCTION_ACTIONS:
        decision = decision.model_copy(update={"requires_human_approval": True})

    # If HIL approved and action ready to dispatch, assign a queue job ID and enqueue
    if not decision.requires_human_approval or hil_approved:
        if decision.chosen_action not in ("monitor_only", "await_human"):
            job_id = str(uuid.uuid4())
            decision = decision.model_copy(update={"queue_job_id": job_id})
            drift_event = state["drift_event"]
            queue_job = QueueJob(
                job_id=job_id,
                job_type=decision.chosen_action,  # type: ignore[arg-type]
                model_name=drift_event.model_name,
                model_version=drift_event.model_version,
                investigation_id=state["investigation_id"],
                created_at=datetime.now(tz=UTC),
            )
            await enqueue_job(state["redis_client"], queue_job)
            log.info(
                "action_agent.job_enqueued",
                investigation_id=state["investigation_id"],
                job_id=job_id,
                action=decision.chosen_action,
            )

    log.info(
        "action_agent.complete",
        investigation_id=state["investigation_id"],
        chosen_action=decision.chosen_action,
        requires_hil=decision.requires_human_approval,
    )

    return {
        "action_decision": decision,
        "messages": [{"role": "action_agent", "content": raw}],
    }


def _fallback_decision(triage, hil_approved: bool) -> ActionDecision:
    action = triage.recommended_actions[0] if triage.recommended_actions else "monitor_only"
    requires_hil = action in PRODUCTION_ACTIONS
    return ActionDecision(
        chosen_action=action,
        requires_human_approval=requires_hil,
        justification="Fallback rule-based decision (LLM unavailable).",
    )
