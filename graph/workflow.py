"""LangGraph workflow assembly (section 8).

    START -> plan -> repository_analysis -> risk_assessment -> implementation
          -> test_generation -> run_tests
                                  |-- PASS --> security_policy -> git_commit
                                  |                -> ci_validation -> create_pr
                                  |                -> human_review -> END
                                  |-- FAIL --> debugging -> run_tests
          ci_validation FAIL --> ci_debugging -> run_tests
          any hard stop --------> halt -> END

Two deliberate departures from the diagram in section 8, both driven by other
sections of the same document:

* ``security_policy`` runs *before* ``git_commit`` so a blocked change never
  enters git history at all (section 25).
* ``ci_validation`` runs *after* ``git_commit`` because section 26 requires a
  pushed branch before a pipeline can run.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from agents.supervisor import Supervisor
from graph.context import WorkflowContext
from graph.nodes import Nodes
from graph.routing import HALT, after_ci, after_commit, after_policy, after_risk, after_tests
from graph.state import AgentState


def build_workflow(context: WorkflowContext) -> Any:
    """Compile the agent graph for one execution context."""
    nodes = Nodes(context)
    supervisor = Supervisor(context)
    graph: StateGraph = StateGraph(AgentState)

    definitions = {
        "plan": nodes.plan,
        "repository_analysis": nodes.repository_analysis,
        "risk_assessment": nodes.risk_assessment,
        "implementation": nodes.implementation,
        "test_generation": nodes.test_generation,
        "run_tests": nodes.run_tests,
        "debugging": nodes.debugging,
        "security_policy": nodes.security_policy,
        "git_commit": nodes.git_commit,
        "ci_validation": nodes.ci_validation,
        "ci_debugging": nodes.ci_debugging,
        "create_pr": nodes.create_pr,
        "human_review": nodes.human_review,
        HALT: nodes.halt,
    }
    for name, function in definitions.items():
        graph.add_node(name, supervisor.instrument(name, function))

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "repository_analysis")
    graph.add_edge("repository_analysis", "risk_assessment")

    graph.add_conditional_edges(
        "risk_assessment", after_risk, {"implementation": "implementation", HALT: HALT}
    )
    graph.add_edge("implementation", "test_generation")
    graph.add_edge("test_generation", "run_tests")

    graph.add_conditional_edges(
        "run_tests",
        after_tests,
        {"security_policy": "security_policy", "debugging": "debugging", HALT: HALT},
    )
    graph.add_edge("debugging", "run_tests")

    graph.add_conditional_edges(
        "security_policy", after_policy, {"git_commit": "git_commit", HALT: HALT}
    )
    graph.add_conditional_edges(
        "git_commit", after_commit, {"ci_validation": "ci_validation", HALT: HALT}
    )

    graph.add_conditional_edges(
        "ci_validation",
        after_ci,
        {"create_pr": "create_pr", "ci_debugging": "ci_debugging", HALT: HALT},
    )
    graph.add_edge("ci_debugging", "run_tests")

    graph.add_edge("create_pr", "human_review")
    graph.add_edge("human_review", END)
    graph.add_edge(HALT, END)

    return graph.compile()


#: Recursion ceiling - the debugging and CI loops are bounded by state, this is
#: only a backstop against a routing bug (rule 18 of section 61).
RECURSION_LIMIT = 60
