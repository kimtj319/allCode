from __future__ import annotations

from allCode.agent.router import RuleBasedRouter


def test_router_read_only_overrides_modify_signal() -> None:
    decision = RuleBasedRouter().classify("수정 금지. src/app.py를 분석만 해줘")

    assert decision.kind == "inspect"
    assert decision.read_only_requested is True
    assert decision.requires_mutation is False
    assert "read_only_requested" in decision.flags
    assert decision.target_hint == "src/app.py"


def test_router_korean_spaced_read_only_overrides_modify_term() -> None:
    decision = RuleBasedRouter().classify("현재 디렉터리의 src 코드를 정리해줘. 코드 수정은 엄격히 금지한다")

    assert decision.read_only_requested is True
    assert decision.kind in {"answer", "inspect"}
    assert decision.requires_mutation is False
    assert "mutate_file" not in decision.tool_capabilities


def test_router_detects_modify_and_validation() -> None:
    decision = RuleBasedRouter().classify("Implement the parser fix and run tests")

    assert decision.kind == "modify"
    assert decision.requires_mutation is True
    assert decision.requires_shell is False
    assert decision.requires_validation is True


def test_router_treats_conceptual_change_wording_as_answer() -> None:
    decision = RuleBasedRouter().classify("파일 수정형 agent에서 completion evidence가 중요한 이유를 알려줘")

    assert decision.kind == "answer"
    assert decision.requires_mutation is False
    assert "conceptual_question" in decision.flags
    assert "explicit_change_request" not in decision.flags


def test_router_treats_conceptual_implementation_wording_as_answer() -> None:
    decision = RuleBasedRouter().classify("completion evidence 구현 방식을 설명해줘")

    assert decision.kind == "answer"
    assert decision.requires_mutation is False


def test_router_treats_read_only_code_draft_as_direct_answer() -> None:
    decision = RuleBasedRouter().classify(
        "코드 수정은 금지한다. Python 표준 라이브러리만 사용해서 CLI 프로젝트 설계와 "
        "task add/list/done/export-json 핵심 코드 초안을 작성해줘. "
        "실제 파일은 만들지 말고 답변으로만 제공해줘."
    )

    assert decision.kind == "answer"
    assert decision.requires_tools is False
    assert decision.requires_mutation is False
    assert decision.target_hint is None
    assert "answer_artifact" in decision.flags


def test_router_does_not_treat_test_in_feature_name_as_validation() -> None:
    decision = RuleBasedRouter().classify("test reporter 프로젝트를 만들기 전에 최소 구조를 먼저 설명해줘.")

    assert decision.kind == "answer"
    assert decision.requires_validation is False
    assert "requires_validation" not in decision.flags


def test_router_keeps_explicit_korean_file_change_as_modify() -> None:
    decision = RuleBasedRouter().classify("src/app.py를 수정해서 completion evidence 검사를 추가해줘")

    assert decision.kind == "modify"
    assert decision.requires_mutation is True
    assert decision.target_hint == "src/app.py"
    assert "explicit_change_request" in decision.flags


def test_router_detects_korean_change_connective_with_validation_command() -> None:
    decision = RuleBasedRouter().classify("그 프로젝트에 feature_value API를 추가하고 테스트까지 실행해줘")

    assert decision.kind == "modify"
    assert decision.requires_mutation is True
    assert decision.requires_validation is True
    assert "explicit_change_request" in decision.flags


def test_router_detects_external_knowledge() -> None:
    decision = RuleBasedRouter().classify("검색해서 최신 공개 문서를 확인해줘")

    assert decision.requires_external_knowledge is True
    assert decision.needs_llm_router is True


def test_router_extracts_path_hint() -> None:
    decision = RuleBasedRouter().classify("Explain @src/allCode/core/result.py")

    assert decision.kind == "inspect"
    assert decision.target_hint == "src/allCode/core/result.py"


def test_router_marks_broad_source_analysis_without_mutation() -> None:
    decision = RuleBasedRouter().classify(
        "코드 수정은 금지한다. 현재 작업공간의 src 아래 프로젝트 뼈대와 레이어 구성을 한국어로 정리해줘."
    )

    assert decision.kind == "inspect"
    assert decision.requires_mutation is False
    assert "broad_source_analysis" in decision.flags


def test_router_does_not_use_tests_word_as_generation_target() -> None:
    decision = RuleBasedRouter().classify("Create a Python project named alpha_tool with tests")

    assert decision.kind == "modify"
    assert decision.target_hint is None
    assert "broad_source_analysis" not in decision.flags
