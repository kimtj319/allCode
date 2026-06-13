from __future__ import annotations

from allCode.agent.router import RoutingDecision
from allCode.agent.source_answer_guard import (
    source_answer_retry_messages,
    source_answer_retry_used,
    source_answer_violation,
)
from allCode.agent.source_answer_retry_context import (
    repeated_source_answer_violation,
    source_answer_retry_count,
    source_answer_violation_error,
)
from allCode.core.models import Message
from allCode.core.result import RecoveryState


def inspect_routing() -> RoutingDecision:
    return RoutingDecision(
        kind="inspect",
        confidence=0.95,
        reason="unit",
        requires_tools=True,
        read_only_requested=True,
    )


def broad_inspect_routing() -> RoutingDecision:
    return inspect_routing().model_copy(update={"flags": {"broad_source_analysis"}})


def tool_message() -> Message:
    return Message(
        role="tool",
        content="Source probe for src/allCode/agent/loop.py",
        tool_call_id="call-1",
        metadata={
            "tool_name": "source_probe",
            "ok": True,
            "observation": {
                "kind": "source_probe",
                "target": "src/allCode/agent/loop.py",
                "observed_symbols": ["AgentLoop", "AgentLoop.run_turn"],
                "line_ranges": [
                    {"start": 3, "end": 50, "reason": "imports", "symbol": ""},
                    {"start": 53, "end": 76, "reason": "symbol_header", "symbol": "AgentLoop"},
                    {"start": 133, "end": 156, "reason": "child_signature", "symbol": "AgentLoop.run_turn"},
                ],
            },
        },
    )


def body_sample_tool_message() -> Message:
    return Message(
        role="tool",
        content="Source probe for src/allCode/agent/loop.py",
        tool_call_id="call-body",
        metadata={
            "tool_name": "source_probe",
            "ok": True,
            "observation": {
                "kind": "source_probe",
                "target": "src/allCode/agent/loop.py",
                "observed_symbols": ["AgentLoop", "AgentLoop.run_turn"],
                "line_ranges": [
                    {"start": 53, "end": 76, "reason": "symbol_header", "symbol": "AgentLoop"},
                    {"start": 133, "end": 142, "reason": "child_body_sample", "symbol": "AgentLoop.run_turn"},
                ],
            },
        },
    )


def source_overview_role_message() -> Message:
    return Message(
        role="tool",
        content="Source overview for src",
        tool_call_id="overview-1",
        metadata={
            "tool_name": "source_overview",
            "ok": True,
            "package_roles": [
                {"path": "src/app/agent", "role": "agent orchestration"},
                {"path": "src/app/generation", "role": "project generation"},
                {"path": "src/app/llm", "role": "model adapter"},
                {"path": "src/app/memory", "role": "session memory"},
                {"path": "src/app/tools", "role": "tool execution"},
                {"path": "src/app/tui", "role": "terminal UI"},
            ],
            "observation": {
                "kind": "source_overview",
                "target": "src",
            },
        },
    )


def narrow_package_role_message() -> Message:
    return Message(
        role="tool",
        content="Source overview for src/app/agent/loop.py",
        tool_call_id="overview-narrow",
        metadata={
            "tool_name": "source_overview",
            "ok": True,
            "package_roles": [
                {"path": "src/app/agent", "role": "agent orchestration"},
                {"path": "src/app/generation", "role": "project generation"},
                {"path": "src/app/llm", "role": "model adapter"},
                {"path": "src/app/tools", "role": "tool execution"},
            ],
            "observation": {
                "kind": "source_overview",
                "target": "src/app/agent/loop.py",
            },
        },
    )


def extended_source_overview_role_message() -> Message:
    roles = [
        ("src/app/agent", "agent orchestration"),
        ("src/app/generation", "project generation"),
        ("src/app/llm", "model adapter"),
        ("src/app/memory", "session memory"),
        ("src/app/tools", "tool execution"),
        ("src/app/tui", "terminal UI"),
        ("src/app/workspace", "workspace context"),
        ("src/app/core", "shared contracts"),
        ("src/app", "runtime wiring"),
        ("src/app/config", "configuration loading"),
        ("src/app/telemetry", "session telemetry"),
        ("src", "source root"),
    ]
    return Message(
        role="tool",
        content="Source overview for src",
        tool_call_id="overview-wide",
        metadata={
            "tool_name": "source_overview",
            "ok": True,
            "package_roles": [{"path": path, "role": role} for path, role in roles],
            "observation": {
                "kind": "source_overview",
                "target": "src",
            },
        },
    )


def test_source_answer_guard_rejects_symbol_claim_with_import_anchor() -> None:
    answer = "`AgentLoop.run_turn`이 턴을 실행합니다 (`src/allCode/agent/loop.py:L3-L50(reason:imports)`)."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is not None
    assert violation.reason == "source_answer_mismatched_anchor"
    assert "AgentLoop.run_turn" in violation.excerpt


def test_source_answer_guard_allows_matching_symbol_anchor() -> None:
    answer = "`AgentLoop.run_turn`은 턴 실행 메서드입니다 (`src/allCode/agent/loop.py:L133-L156(reason:child_signature:AgentLoop.run_turn)`)."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is None


def test_source_answer_guard_requires_priority_package_roles_for_broad_source_request() -> None:
    # Covering only 2 of 6 observed packages ignores the bulk of the architecture
    # and still fails (minor omissions are tolerated; wholesale omission is not).
    answer = "\n".join(
        [
            "src 구조는 다음과 같습니다.",
            "- `src/app/agent`: agent orchestration",
            "- `src/app/tools`: tool execution",
        ]
    )

    violation = source_answer_violation(
        answer=answer,
        routing=inspect_routing(),
        messages=[source_overview_role_message()],
        user_prompt="src 내 코드들이 어떤 역할을 하는지 정리해줘",
    )

    assert violation is not None
    assert violation.reason == "source_answer_missing_priority_package_roles"
    assert "src/app/generation" in violation.excerpt


def test_source_answer_guard_uses_broad_route_flag_for_package_roles() -> None:
    # Covers only 1 of 4 observed packages -> exceeds the omission tolerance.
    violation = source_answer_violation(
        answer="agent 중심입니다.",
        routing=broad_inspect_routing(),
        messages=[narrow_package_role_message()],
        user_prompt="프로젝트 레이어를 알려줘",
    )

    assert violation is not None
    assert violation.reason == "source_answer_missing_priority_package_roles"


def test_source_answer_guard_does_not_force_package_roles_for_narrow_route() -> None:
    violation = source_answer_violation(
        answer="agent와 tools 중심입니다.",
        routing=inspect_routing(),
        messages=[narrow_package_role_message()],
        user_prompt="src/app/agent/loop.py만 설명해줘",
    )

    assert violation is None


def test_source_answer_guard_rejects_observed_package_role_in_limitation_section() -> None:
    answer = "\n".join(
        [
            "### `src/app/agent`",
            "agent orchestration을 담당합니다.",
            "",
            "### 기타 패키지 (관찰 근거 없음)",
            "`src/app/generation`, `src/app/llm`, `src/app/memory`, `src/app/tools`는 확인하지 못했습니다.",
        ]
    )

    violation = source_answer_violation(
        answer=answer,
        routing=broad_inspect_routing(),
        messages=[source_overview_role_message()],
        user_prompt="프로젝트 레이어를 알려줘",
    )

    assert violation is not None
    assert violation.reason == "source_answer_missing_priority_package_roles"
    assert "src/app/generation" in violation.excerpt


def test_source_answer_guard_tolerates_minor_package_omissions() -> None:
    # Covers 8 of 10 concrete packages, omitting only minor ones (config,
    # telemetry). Reference agents do the same, so this must NOT be forced into a
    # deterministic fallback.
    answer = "\n".join(
        [
            "`src/app/agent`: agent orchestration",
            "`src/app/generation`: project generation",
            "`src/app/llm`: model adapter",
            "`src/app/memory`: session memory",
            "`src/app/tools`: tool execution",
            "`src/app/tui`: terminal UI",
            "`src/app/workspace`: workspace context",
            "`src/app/core`: shared contracts",
        ]
    )

    violation = source_answer_violation(
        answer=answer,
        routing=broad_inspect_routing(),
        messages=[extended_source_overview_role_message()],
        user_prompt="프로젝트 레이어를 알려줘",
    )

    assert violation is None


def test_source_answer_retry_message_lists_priority_package_roles() -> None:
    violation = source_answer_violation(
        answer="src/app/agent와 src/app/tools 중심입니다.",
        routing=inspect_routing(),
        messages=[source_overview_role_message()],
        user_prompt="src 내 코드 역할을 정리해줘",
    )
    assert violation is not None

    messages = source_answer_retry_messages(
        current_messages=[source_overview_role_message()],
        previous_answer="src/app/agent와 src/app/tools 중심입니다.",
        violation=violation,
        language="ko",
    )

    assert "관찰된 상위 패키지 역할 후보" in messages[-1].content
    assert "src/app/generation" in messages[-1].content


def test_source_answer_guard_requires_body_anchor_when_user_requested_body_evidence() -> None:
    answer = "`AgentLoop.run_turn`은 턴 실행 메서드입니다 (`src/allCode/agent/loop.py:L53-L76(reason:symbol_header:AgentLoop)`)."

    violation = source_answer_violation(
        answer=answer,
        routing=inspect_routing(),
        messages=[body_sample_tool_message()],
        user_prompt="핵심 함수 본문 근거를 포함해서 설명해줘.",
    )

    assert violation is not None
    assert violation.reason == "source_answer_missing_body_evidence"
    assert "child_body_sample" in violation.excerpt


def test_source_answer_guard_allows_body_request_when_no_body_anchor_was_observed() -> None:
    answer = "`AgentLoop.run_turn`은 턴 실행 메서드입니다 (`src/allCode/agent/loop.py:L133-L156(reason:child_signature:AgentLoop.run_turn)`)."

    violation = source_answer_violation(
        answer=answer,
        routing=inspect_routing(),
        messages=[tool_message()],
        user_prompt="핵심 함수 본문 근거를 포함해서 설명해줘.",
    )

    assert violation is None


def test_source_answer_guard_rejects_unobserved_anchor() -> None:
    answer = "`AgentLoop` 근거는 `src/allCode/agent/loop.py:L999-L1000(reason:symbol)`입니다."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is not None
    assert violation.reason == "source_answer_unobserved_anchor"


def test_source_answer_guard_rejects_raw_tool_action_json() -> None:
    violation = source_answer_violation(
        answer='{"action": "search_files", "parameters": {"query": "SourceProbeTool"}}',
        routing=inspect_routing(),
        messages=[],
    )

    assert violation is not None
    assert violation.reason == "source_answer_raw_tool_action"


def test_source_answer_guard_allows_observed_subrange_anchor() -> None:
    answer = "import 근거는 `src/allCode/agent/loop.py:L3-L22(reason:imports)`입니다."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is None


def test_source_answer_guard_rejects_internal_claim_about_unread_file() -> None:
    answer = "`src/allCode/tools/base.py`에 정의된 `ToolDefinition`이 툴을 레지스트리에 등록합니다."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is not None
    assert violation.reason == "source_answer_unobserved_path_claim"


def test_source_answer_guard_rejects_unobserved_dotted_symbol_claim() -> None:
    answer = "`ToolContext.run_tool`이 선택된 툴을 실행합니다."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is not None
    assert violation.reason == "source_answer_unobserved_symbol_claim"


def test_source_answer_guard_allows_unread_path_in_limitation() -> None:
    answer = "`src/allCode/tools/base.py`는 직접 관찰하지 못했습니다."

    violation = source_answer_violation(answer=answer, routing=inspect_routing(), messages=[tool_message()])

    assert violation is None


def test_source_answer_guard_retry_message_and_used_flag() -> None:
    violation = source_answer_violation(
        answer="`AgentLoop.run_turn` (`src/allCode/agent/loop.py:L3-L50(reason:imports)`).",
        routing=inspect_routing(),
        messages=[tool_message()],
    )
    assert violation is not None

    messages = source_answer_retry_messages(
        current_messages=[tool_message()],
        previous_answer="bad answer",
        violation=violation,
        language="ko",
    )

    assert messages[-1].role == "user"
    assert "앵커" in messages[-1].content
    assert "관찰 앵커 후보" in messages[-1].content
    assert "src/allCode/agent/loop.py:L133-L156" in messages[-1].content
    assert "생략" in messages[-1].content
    assert all(message.content != "bad answer" for message in messages)
    recovery = type("Recovery", (), {"states": [RecoveryState(reason="no_progress", last_error=violation.reason)]})()
    assert source_answer_retry_used(recovery) is True


def test_source_answer_retry_context_counts_and_detects_repeated_violation() -> None:
    error = source_answer_violation_error("source_answer_mismatched_anchor", "bad anchor")
    recovery = type(
        "Recovery",
        (),
        {
            "states": [
                RecoveryState(reason="no_progress", last_error=error),
                RecoveryState(reason="no_progress", last_error="source_answer_unobserved_anchor: other"),
            ]
        },
    )()

    assert source_answer_retry_count(recovery) == 2
    assert repeated_source_answer_violation(
        recovery,
        reason="source_answer_mismatched_anchor",
        excerpt="bad anchor",
    ) is True
    assert repeated_source_answer_violation(
        recovery,
        reason="source_answer_mismatched_anchor",
        excerpt="different",
    ) is False
