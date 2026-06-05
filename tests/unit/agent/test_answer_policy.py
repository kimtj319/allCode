from __future__ import annotations

from allCode.agent.answer_policy import apply_answer_policy, decide_answer_policy
from allCode.agent.prompt_constraints import PromptConstraintExtractor
from allCode.agent.router import RoutingDecision


def _answer_route(*, tools: set[str] | None = None, external: bool = False) -> RoutingDecision:
    return RoutingDecision(
        kind="answer",
        confidence=0.9,
        reason="answer",
        tool_capabilities=tools or set(),
        requires_tools=bool(tools),
        requires_external_knowledge=external,
    )


def test_answer_policy_keeps_stable_general_question_direct() -> None:
    constraints = PromptConstraintExtractor().extract("RSA와 양자컴퓨터의 관계를 쉽게 설명해줘")

    decision = decide_answer_policy(_answer_route(tools={"read_file", "web_search"}), constraints=constraints, local_workspace_request=False)
    route = apply_answer_policy(_answer_route(tools={"read_file", "web_search"}), constraints=constraints, local_workspace_request=False)

    assert decision.mode == "direct"
    assert route.tool_capabilities == set()
    assert route.requires_tools is False
    assert route.requires_external_knowledge is False


def test_answer_policy_exposes_only_web_for_latest_external_question() -> None:
    constraints = PromptConstraintExtractor().extract("2026년 현재 최신 Python 릴리스 정보를 알려줘")

    route = apply_answer_policy(_answer_route(), constraints=constraints, local_workspace_request=False)

    assert route.tool_capabilities == {"web_search"}
    assert route.requires_tools is True
    assert route.requires_external_knowledge is True
    assert route.workflow_hint == "external_research"


def test_answer_policy_respects_no_network_by_using_direct_answer_mode() -> None:
    constraints = PromptConstraintExtractor().extract("최신 Python 릴리스 정보를 알려줘. 외부 검색 금지")

    route = apply_answer_policy(_answer_route(external=True, tools={"web_search"}), constraints=constraints, local_workspace_request=False)

    assert route.tool_capabilities == set()
    assert route.requires_external_knowledge is False
    assert route.requires_tools is False


def test_answer_policy_does_not_change_non_answer_routes() -> None:
    constraints = PromptConstraintExtractor().extract("현재 디렉터리의 src 구조를 분석해줘")
    route = RoutingDecision(
        kind="inspect",
        confidence=0.9,
        reason="inspect",
        tool_capabilities={"read_file", "search_workspace"},
        requires_tools=True,
    )

    updated = apply_answer_policy(route, constraints=constraints, local_workspace_request=True)

    assert updated == route
