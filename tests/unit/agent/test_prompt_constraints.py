from __future__ import annotations

from allCode.agent.prompt_constraints import PromptConstraintExtractor


def test_prompt_constraints_extract_safety_without_route_kind() -> None:
    constraints = PromptConstraintExtractor().extract("수정 금지. app.py를 실제 파일 검색으로 찾아줘")

    assert constraints.read_only_requested is True
    assert constraints.workspace_evidence_requested is True
    assert constraints.path_hints == ["app.py"]


def test_prompt_constraints_detects_korean_do_not_modify_sentence() -> None:
    constraints = PromptConstraintExtractor().extract("python -m pytest -q를 실행해줘. 파일 수정은 하지 마.")

    assert constraints.read_only_requested is True
    assert constraints.validation_requested_hint is True


def test_prompt_constraints_read_only_pattern_overrides_mutation_hint() -> None:
    constraints = PromptConstraintExtractor().extract("src 내 코드를 정리해줘. 코드 수정은 엄격히 금지한다")

    assert constraints.read_only_requested is True
    assert constraints.mutation_requested_hint is False
    assert constraints.project_generation_hint is False
    assert constraints.path_hints == ["src"]
    assert "read_only_pattern" in constraints.matched_constraints


def test_prompt_constraints_detects_korean_compound_prohibition_list() -> None:
    constraints = PromptConstraintExtractor().extract(
        "읽기 전용 분석이다. 소스 코드 수정, 파일 생성, 파일 삭제, 포맷팅 변경, 커밋은 엄격히 금지한다. "
        "현재 디렉터리의 src 내 코드 역할을 한국어로 정리해줘."
    )

    assert constraints.read_only_requested is True
    assert constraints.mutation_requested_hint is False
    assert constraints.workspace_evidence_requested is True
    assert constraints.path_hints == ["src"]
    assert "read_only_clause" in constraints.matched_constraints


def test_prompt_constraints_detect_followup_workspace_evidence() -> None:
    constraints = PromptConstraintExtractor().extract("방금 요약한 모듈 중 engine 메인 클래스를 실제 파일 검색으로 찾아줘")

    assert constraints.followup_requested is True
    assert constraints.workspace_evidence_requested is True


def test_prompt_constraints_detects_argumentation_answer_followup() -> None:
    constraints = PromptConstraintExtractor().extract("방금 제시한 요인을 반박하고 재반박해줘")

    assert constraints.followup_requested is True
    assert constraints.answer_followup_hint is True
    assert constraints.argumentation_followup_hint is True


def test_prompt_constraints_detects_directory_project_generation_signals() -> None:
    constraints = PromptConstraintExtractor().extract(
        "./output/ops_platform 아래에 CLI, config, registry, tests, README를 포함한 플랫폼 프로젝트를 생성하라."
    )

    assert constraints.directory_output_hint is True
    assert constraints.multi_artifact_hint is True
    assert constraints.project_output_hint is True
    assert constraints.project_generation_hint is True
    assert constraints.mutation_requested_hint is True
    assert constraints.code_artifact_hint is True


def test_prompt_constraints_detects_korean_inside_particle_for_package_generation() -> None:
    constraints = PromptConstraintExtractor().extract(
        "./output/jsonl_viewer 안에 표준 라이브러리만 사용하는 Python 패키지형 CLI를 생성해줘. "
        "config, registry, retry, pytest, README를 포함해야 한다."
    )

    assert constraints.directory_output_hint is True
    assert constraints.multi_artifact_hint is True
    assert constraints.project_output_hint is True
    assert constraints.project_generation_hint is True
    assert constraints.mutation_requested_hint is True
    assert constraints.primary_target_hint == "./output/jsonl_viewer"
    assert constraints.stdlib_only_requested is True


def test_prompt_constraints_detects_stdlib_only_direct_answer_constraint() -> None:
    constraints = PromptConstraintExtractor().extract(
        "코드 수정은 금지한다. Python 표준 라이브러리만 사용해서 CLI 설계와 핵심 코드 초안을 답변으로 작성해줘."
    )

    assert constraints.read_only_requested is True
    assert constraints.answer_artifact_hint is True
    assert constraints.stdlib_only_requested is True


def test_prompt_constraints_detects_dependency_constraint_variants() -> None:
    korean = PromptConstraintExtractor().extract("외부 패키지 없이 기본 라이브러리만 사용해서 CLI 설계를 답변으로 작성해줘.")
    english = PromptConstraintExtractor().extract("Use Python built-in modules only and avoid third-party libraries.")

    assert korean.stdlib_only_requested is True
    assert english.stdlib_only_requested is True


def test_prompt_constraints_does_not_treat_dependency_discussion_as_constraint() -> None:
    constraints = PromptConstraintExtractor().extract("외부 라이브러리 선택 기준과 의존성 관리 장단점을 설명해줘.")

    assert constraints.stdlib_only_requested is False


def test_prompt_constraints_detects_unstable_business_knowledge_without_workspace_tools() -> None:
    constraints = PromptConstraintExtractor().extract("AI 코딩 에이전트 도입 비용, KPI, 2026년 시장 동향을 정리해줘")

    assert constraints.unstable_knowledge_hint is True
    assert constraints.external_knowledge_hint is True
    assert constraints.workspace_evidence_requested is False


def test_prompt_constraints_suppresses_external_for_general_principle_scope() -> None:
    constraints = PromptConstraintExtractor().extract(
        "RAG 시스템에서 latency, cost trade-off를 최신 수치가 아니라 일반 원칙 중심으로 설명해줘."
    )

    assert constraints.unstable_knowledge_hint is False
    assert constraints.external_knowledge_hint is False
    assert "external_knowledge_suppressed" in constraints.matched_constraints


def test_prompt_constraints_distinguishes_code_artifact_from_general_writing() -> None:
    code_constraints = PromptConstraintExtractor().extract("가격 규정에 맞춘 billing 정책 코드를 구현해줘.")
    answer_constraints = PromptConstraintExtractor().extract("RSA와 양자컴퓨터 관계를 한국어로 작성해줘.")

    assert code_constraints.code_artifact_hint is True
    assert answer_constraints.code_artifact_hint is False


def test_prompt_constraints_distinguishes_answer_only_code_artifact_from_workspace_evidence() -> None:
    constraints = PromptConstraintExtractor().extract(
        "코드 수정은 금지한다. Python 표준 라이브러리만 사용해서 taskhub 미니 프로젝트를 설계하고, "
        "CLI로 task add/list/done/export-json을 지원하는 파일 구조와 핵심 코드 초안을 작성해줘. "
        "실제 파일은 만들지 말고 답변으로만 제공해줘."
    )

    assert constraints.read_only_requested is True
    assert constraints.answer_artifact_hint is True
    assert constraints.code_artifact_hint is True
    assert constraints.workspace_evidence_requested is False
    assert constraints.path_hints == []


def test_prompt_constraints_treats_existing_file_ban_with_output_scope_as_mutation() -> None:
    constraints = PromptConstraintExtractor().extract(
        "./output/tool_app 아래에 프로젝트를 생성하라. 기존 파일 수정 금지, ./output 하위만 수정하라."
    )

    assert constraints.read_only_requested is False
    assert constraints.mutation_requested_hint is True
    assert constraints.directory_output_hint is True
    assert "scoped_output_mutation_allowed" in constraints.matched_constraints
