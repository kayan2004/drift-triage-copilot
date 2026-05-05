from langgraph.graph import END, START, StateGraph

from app.graph.action_agent import action_agent_node
from app.graph.comms_agent import comms_agent_node
from app.graph.supervisor import (
    InvestigationState,
    await_hil_node,
    route_after_supervisor,
    supervisor_node,
)
from app.graph.triage_agent import triage_agent_node


def build_graph() -> StateGraph:
    builder = StateGraph(InvestigationState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("triage_agent", triage_agent_node)
    builder.add_node("action_agent", action_agent_node)
    builder.add_node("await_hil", await_hil_node)
    builder.add_node("comms_agent", comms_agent_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "triage_agent": "triage_agent",
            "action_agent": "action_agent",
            "await_hil": "await_hil",
            "comms_agent": "comms_agent",
            END: END,
        },
    )
    builder.add_edge("triage_agent", "supervisor")
    builder.add_edge("action_agent", "supervisor")
    builder.add_edge("await_hil", "supervisor")
    builder.add_edge("comms_agent", "supervisor")

    return builder
