"""Core-event renderers for the TUI."""

from __future__ import annotations

from pydantic import Field

from allCode.core.events import AgentEvent
from allCode.core.models import CoreModel
from allCode.tui import messages


class RenderedEvent(CoreModel):
    transcript: str = ""
    transcript_role: str = "status"
    status: str = ""
    spinner: bool = False
    foldable: bool = False
    fold_title: str = ""
    fold_full_text: str = ""
    severity: str = "status_only"


class EventRenderer:
    def render(self, event: AgentEvent) -> RenderedEvent:
        handler = getattr(self, f"_render_{event.event_type}", None)
        if handler is not None:
            return handler(event)
        if event.severity == "user_visible":
            return RenderedEvent(
                transcript=event.message,
                transcript_role="allCode",
                status=event.message,
                severity=event.severity,
            )
        return RenderedEvent(status=event.message, severity=event.severity)

    def _render_user_prompt_submitted(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript=event.message,
            transcript_role="user",
            status=messages.MODEL_REQUEST_STATUS,
            spinner=True,
            severity=event.severity,
        )

    def _render_turn_started(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.MODEL_REQUEST_STATUS, spinner=True, severity=event.severity)

    def _render_model_stream_started(self, event: AgentEvent) -> RenderedEvent:
        retry = event.data.get("retry")
        if retry is None:
            message = event.message.lower()
            retry = "round" in message and "round 1" not in message
        status = messages.RECOVERY_STATUS if retry else messages.MODEL_WAITING_STATUS
        return RenderedEvent(status=status, spinner=True, severity=event.severity)

    def _render_model_stream_heartbeat(self, event: AgentEvent) -> RenderedEvent:
        count = event.data.get("heartbeat_count")
        suffix = f"... {count}" if count else ""
        return RenderedEvent(status=f"{messages.SLOW_STREAM_STATUS}{suffix}", spinner=True, severity=event.severity)

    def _render_model_stream_timed_out(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(transcript=messages.RECOVERY_STATUS, status=messages.RECOVERY_STATUS, spinner=True, severity=event.severity)

    def _render_model_text_delta(self, event: AgentEvent) -> RenderedEvent:
        delta = getattr(event, "delta", "")
        return RenderedEvent(
            transcript=delta,
            transcript_role="allCode_stream",
            status=messages.ANSWERING_STATUS,
            spinner=True,
            severity=event.severity,
        )

    def _render_tool_call_requested(self, event: AgentEvent) -> RenderedEvent:
        tool_call = getattr(event, "tool_call", None)
        tool_name = tool_call.name if tool_call is not None else "tool"
        return RenderedEvent(status=f"도구 준비 중: {tool_name}", spinner=True, severity=event.severity)

    def _render_tool_execution_started(self, event: AgentEvent) -> RenderedEvent:
        tool_call = getattr(event, "tool_call", None)
        tool_name = tool_call.name if tool_call is not None else "tool"
        return RenderedEvent(status=f"도구 실행 중: {tool_name}", spinner=True, severity=event.severity)

    def _render_tool_execution_finished(self, event: AgentEvent) -> RenderedEvent:
        result = getattr(event, "result", None)
        if result is None:
            return RenderedEvent(status="도구 실행 완료", severity=event.severity)
        body = result.content or result.error or ""
        title = f"{result.name}: {'ok' if result.ok else 'error'}"
        transcript = f"[tool] {title}"
        if body:
            if len(body) > 1200:
                preview = body[:400] + "\n[folded output: open tool panel for full content]"
                return RenderedEvent(
                    transcript=f"{transcript}\n{preview}",
                    transcript_role="tool",
                    status="도구 실행 완료",
                    foldable=True,
                    fold_title=title,
                    fold_full_text=body,
                    severity="user_visible",
                )
            transcript = f"{transcript}\n{body}"
        return RenderedEvent(
            transcript=transcript,
            transcript_role="tool",
            status="도구 실행 완료",
            foldable=False,
            fold_title=title,
            severity="user_visible",
        )

    def _render_validation_started(self, event: AgentEvent) -> RenderedEvent:
        command = event.data.get("command", "")
        suffix = f": {command}" if command else ""
        return RenderedEvent(status=messages.VALIDATION_STATUS + suffix, spinner=True, severity=event.severity)

    def _render_validation_finished(self, event: AgentEvent) -> RenderedEvent:
        ok = event.data.get("passed")
        text = "검증 성공" if ok is True else "검증 실패"
        return RenderedEvent(transcript=text, transcript_role="status", status=text, severity=event.severity)

    def _render_generation_step_started(self, event: AgentEvent) -> RenderedEvent:
        step = str(event.data.get("step", ""))
        status = {
            "skeleton": "스켈레톤 생성 중",
            "implementation": "파일 구현 중",
            "tests": "테스트 작성 중",
            "validation": messages.VALIDATION_STATUS,
            "repair": messages.REPAIR_STATUS,
            "final_report": messages.FINAL_REPORT_STATUS,
        }.get(step, messages.WORKING_STATUS)
        return RenderedEvent(transcript=status, transcript_role="status", status=status, spinner=True, severity="user_visible")

    def _render_generation_step_finished(self, event: AgentEvent) -> RenderedEvent:
        step = event.data.get("step", "")
        status = event.data.get("status", "")
        return RenderedEvent(transcript=f"{step}: {status}", transcript_role="status", status=str(status), severity="user_visible")

    def _render_approval_requested(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript="승인이 필요합니다.",
            transcript_role="approval",
            status=messages.APPROVAL_STATUS,
            severity=event.severity,
        )

    def _render_tool_loop_detected(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript=messages.RECOVERY_STATUS,
            transcript_role="status",
            status=messages.RECOVERY_STATUS,
            spinner=True,
            severity=event.severity,
        )

    def _render_final_answer_ready(self, event: AgentEvent) -> RenderedEvent:
        final_answer = getattr(event, "final_answer", event.message)
        return RenderedEvent(
            transcript=final_answer,
            transcript_role="allCode",
            status=messages.READY_STATUS,
            severity=event.severity,
        )

    def _render_turn_failed(self, event: AgentEvent) -> RenderedEvent:
        if getattr(event, "cancelled", False):
            return RenderedEvent(
                transcript=messages.CANCELLED_STATUS,
                transcript_role="status",
                status=messages.READY_STATUS,
                severity=event.severity,
            )
        if "Completion evidence missing" in event.message or "Completion check failed" in event.message:
            return RenderedEvent(
                transcript=messages.FINAL_GATE_STATUS,
                transcript_role="status",
                status=messages.FINAL_GATE_STATUS,
                spinner=True,
                severity=event.severity,
            )
        return RenderedEvent(
            transcript=f"오류: {event.message}",
            transcript_role="error",
            status=messages.READY_STATUS,
            severity=event.severity,
        )

    def _render_turn_cancelled(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript=messages.CANCELLED_STATUS,
            transcript_role="status",
            status=messages.READY_STATUS,
            severity=event.severity,
        )


class FoldedToolOutput(CoreModel):
    title: str
    preview: str
    expanded: bool = False
    full_text: str = ""

    def toggle(self) -> "FoldedToolOutput":
        return self.model_copy(update={"expanded": not self.expanded})
