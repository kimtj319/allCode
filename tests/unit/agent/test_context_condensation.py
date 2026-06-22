from __future__ import annotations

from allCode.agent.context_condensation import build_condensed_context, condense_messages_for_model
from allCode.core.models import Message, ToolCall


def test_condense_messages_keeps_first_constraint_and_current_user_without_mutating_runtime() -> None:
    messages = [
        Message(role="system", content="base system"),
        Message(role="user", content="처음 제약: 파일 수정 금지"),
        *[Message(role="assistant", content=f"old answer {index} " + ("x" * 400)) for index in range(12)],
        Message(role="user", content="현재 질문: src 구조를 설명해줘"),
    ]

    outgoing = condense_messages_for_model(messages, max_chars=2500, recent_messages=3)

    assert messages[2].content.startswith("old answer 0")
    assert any(message.metadata.get("context_condensed") for message in outgoing)
    assert any("처음 제약: 파일 수정 금지" in message.content for message in outgoing)
    assert outgoing[-1].content == "현재 질문: src 구조를 설명해줘"


def test_condense_messages_summarizes_old_tool_output_but_keeps_recent_failure() -> None:
    old_tool = Message(
        role="tool",
        content="old inventory " + ("a" * 5000),
        metadata={"tool_name": "source_overview", "ok": True, "observation": {"target": "src"}},
    )
    recent_failure = Message(
        role="tool",
        content="Traceback\nSyntaxError: invalid syntax in src/app.py",
        metadata={"tool_name": "run_tests", "ok": False, "error_type": "validation_failed"},
    )
    messages = [
        Message(role="system", content="base"),
        Message(role="user", content="테스트 실패를 고쳐줘"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="1", name="source_overview", arguments={})]),
        old_tool,
        *[Message(role="assistant", content="middle " + ("b" * 800)) for _ in range(8)],
        recent_failure,
        Message(role="user", content="계속 진행해줘"),
    ]

    outgoing = condense_messages_for_model(messages, max_chars=2600, recent_messages=3)
    rendered = "\n".join(message.content for message in outgoing)

    assert "source_overview src -> ok" in rendered
    assert "old inventory " in rendered
    assert "Traceback\nSyntaxError: invalid syntax in src/app.py" in rendered
    assert "a" * 2000 not in rendered


def test_condense_messages_keeps_tool_call_transaction_blocks_together() -> None:
    assistant_call = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"file_path": "src/app.py"})],
    )
    tool_result = Message(
        role="tool",
        content="src/app.py content",
        tool_call_id="call-1",
        metadata={"tool_name": "read_file", "ok": True, "file_path": "src/app.py"},
    )
    messages = [
        Message(role="system", content="base"),
        Message(role="user", content="처음 제약"),
        *[Message(role="assistant", content="middle " + ("x" * 600)) for _ in range(8)],
        assistant_call,
        tool_result,
        Message(role="user", content="현재 질문"),
    ]

    outgoing = condense_messages_for_model(messages, max_chars=2200, recent_messages=2)
    tool_index = next(index for index, message in enumerate(outgoing) if message.role == "tool")

    assert outgoing[tool_index - 1].role == "assistant"
    assert outgoing[tool_index - 1].tool_calls


def test_condensed_context_redacts_secrets_and_strips_reasoning_markers() -> None:
    context = build_condensed_context(
        [
            Message(role="assistant", content="reasoning: hidden chain\nVisible decision"),
            Message(role="tool", content="token sk-test-secret-value failed", metadata={"tool_name": "run_tests", "ok": False}),
        ]
    )
    rendered = context.render()

    assert "reasoning:" not in rendered
    assert "hidden chain" not in rendered
    assert "Visible decision" in rendered
    assert "sk-test-secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_recent_short_reasoning_block_is_removed_before_model_view() -> None:
    messages = [
        Message(role="system", content="base"),
        Message(role="user", content="질문"),
        *[Message(role="assistant", content="middle " + ("x" * 700)) for _ in range(8)],
        Message(role="assistant", content="<think>\ninternal reasoning\n</think>\nVisible answer"),
        Message(role="user", content="계속"),
    ]

    outgoing = condense_messages_for_model(messages, max_chars=2200, recent_messages=3)
    rendered = "\n".join(message.content for message in outgoing)

    assert "internal reasoning" not in rendered
    assert "<think>" not in rendered
    assert "Visible answer" in rendered


def test_window_aware_max_chars_returns_total_budget_not_body() -> None:
    # Regression: window_aware_max_chars must return the WHOLE-message budget
    # (condense_messages_for_model compares the full list incl. system prefix).
    # A prior version subtracted the system prefix here, double-charging it.
    from allCode.agent.context_condensation import window_aware_max_chars, MAX_MODEL_CONTEXT_CHARS

    # unknown window -> legacy fixed budget
    assert window_aware_max_chars(context_window_tokens=0, max_output_tokens=8192) == MAX_MODEL_CONTEXT_CHARS
    # 32k window, 8k output -> (32768-8192)*0.85*4 chars, well above legacy
    big = window_aware_max_chars(context_window_tokens=32768, max_output_tokens=8192)
    assert big > MAX_MODEL_CONTEXT_CHARS
    # does not depend on / subtract any message content (no messages arg)
    small_win = window_aware_max_chars(context_window_tokens=8192, max_output_tokens=4096)
    assert small_win >= 8000  # floored at 2000 tokens


def test_bound_message_contents_preserves_first_system_prompt() -> None:
    from allCode.agent.context_condensation import _bound_message_contents

    sys_prompt = Message(role="system", content="AUTHORITATIVE SYSTEM PROMPT: tool rules. " + "S" * 2000)
    bundle = Message(role="system", content="workspace context " + "C" * 5000)
    asst = Message(role="assistant", content="A" * 5000)
    usr = Message(role="user", content="U" * 300)
    # Budget large enough to keep the system prompt once the other oversized
    # messages are trimmed (each trims to ~812), but below the untrimmed total —
    # so the system prompt stays intact while the rest shrink.
    out = _bound_message_contents([sys_prompt, bundle, asst, usr], max_chars=4200)
    # The authoritative system prompt (first system message) must stay intact;
    # later non-user messages are truncated first.
    assert "AUTHORITATIVE SYSTEM PROMPT" in out[0].content
    assert len(out[0].content) > 2000
    assert any(m.metadata.get("context_hard_truncated") for m in out[1:])
