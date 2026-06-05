from __future__ import annotations

from allCode.agent.router import RoutingDecision
from allCode.agent.task_loop_digest import build_task_loop_digest, task_loop_digest_messages
from allCode.core.models import Message, TurnInput, WorkspaceRef
from allCode.core.result import CompletionEvidence, RecoveryState, RequestedArtifact


def _turn(prompt: str = "src/app.py를 수정하고 테스트해줘") -> TurnInput:
    return TurnInput(user_prompt=prompt, workspace=WorkspaceRef(root="."))


def _routing() -> RoutingDecision:
    return RoutingDecision(
        kind="modify",
        confidence=0.9,
        reason="change request",
        tool_capabilities={"read_file", "mutate_file", "run_validation"},
        requires_tools=True,
        requires_mutation=True,
        requires_validation=True,
    )


def test_task_loop_digest_keeps_goal_evidence_and_remaining_obligations() -> None:
    evidence = CompletionEvidence(
        changed_files=["src/app.py"],
        validation_commands=["pytest"],
        validation_passed=False,
        validation_failure_excerpt="AssertionError: expected 2",
        requested_artifacts=[
            RequestedArtifact(kind="test", target="tests/test_app.py", reason="prompt requested tests"),
        ],
        feature_objectives=["계산 로직"],
    )

    digest = build_task_loop_digest(
        turn_input=_turn(),
        routing=_routing(),
        evidence=evidence,
        recovery_states=[RecoveryState(reason="validation_failed", attempts=1, last_error="pytest failed")],
    )

    rendered = digest.render()
    assert "src/app.py를 수정하고 테스트" in rendered
    assert "changed: src/app.py" in rendered
    assert "test: tests/test_app.py" in rendered
    assert "feature objective: 계산 로직" in rendered
    assert digest.validation_status == "failed"
    assert "AssertionError" in rendered


def test_task_loop_digest_redacts_secrets() -> None:
    evidence = CompletionEvidence(validation_failure_excerpt="token sk-test-secret-value failed")

    digest = build_task_loop_digest(
        turn_input=_turn("API token sk-test-secret-value를 쓰지 말고 파일을 수정해줘"),
        routing=_routing(),
        evidence=evidence,
    )

    rendered = digest.render()
    assert "sk-test-secret-value" not in rendered
    assert "[REDACTED]" in rendered


def test_task_loop_digest_messages_injects_single_system_message_without_mutating_runtime() -> None:
    messages = [
        Message(role="system", content="base"),
        Message(role="user", content="prompt"),
    ]
    digest = build_task_loop_digest(
        turn_input=_turn(),
        routing=_routing(),
        evidence=CompletionEvidence(),
    )

    outgoing = task_loop_digest_messages(messages, digest)
    outgoing_again = task_loop_digest_messages(outgoing, digest)

    assert [message.content for message in messages] == ["base", "prompt"]
    assert len([message for message in outgoing if message.metadata.get("task_loop_digest")]) == 1
    assert len([message for message in outgoing_again if message.metadata.get("task_loop_digest")]) == 1
    assert outgoing[1].role == "system"
    assert "Task loop digest" in outgoing[1].content
