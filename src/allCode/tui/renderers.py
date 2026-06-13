"""Core-event renderers for the TUI."""

from __future__ import annotations

from pydantic import Field

from allCode.core.events import AgentEvent
from allCode.core.models import CoreModel
from allCode.tui import messages
from allCode.tui.tool_timeline import build_tool_timeline_entry


class RenderedEvent(CoreModel):
    transcript: str = ""
    transcript_role: str = "status"
    status: str = ""
    spinner: bool = False
    foldable: bool = False
    fold_title: str = ""
    fold_full_text: str = ""
    diff: str = ""
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

    def _render_routing_decided(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.ROUTING_STATUS, spinner=True, severity=event.severity)

    def _render_model_request_prepared(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.MODEL_REQUEST_STATUS, spinner=True, severity=event.severity)

    def _render_model_stream_started(self, event: AgentEvent) -> RenderedEvent:
        stream_phase = event.data.get("stream_phase")
        if stream_phase == "continuation":
            return RenderedEvent(status=messages.MODEL_CONTINUING_STATUS, spinner=True, severity=event.severity)
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
        if result.name == "source_overview":
            return self._render_source_overview_result(result, event.severity)
        entry = build_tool_timeline_entry(result)
        if entry.quiet_status:
            return RenderedEvent(status=entry.quiet_status, severity="status_only")
        return RenderedEvent(
            transcript=entry.line,
            transcript_role="tool",
            status="도구 실행 완료",
            foldable=entry.foldable,
            fold_title=entry.fold_title,
            fold_full_text=entry.fold_full_text,
            diff=entry.diff,
            severity="user_visible",
        )

    def _render_source_overview_collected(self, event: AgentEvent) -> RenderedEvent:
        target = str(event.data.get("target") or "workspace")
        file_count = _compact_count(event.data.get("file_count"), "files")
        symbol_count = _compact_count(event.data.get("symbol_count"), "symbols")
        truncated = " · truncated" if event.data.get("truncated") else ""
        metrics = " · ".join(part for part in (file_count, symbol_count) if part)
        suffix = f" · {metrics}" if metrics else ""
        return RenderedEvent(
            transcript="",
            transcript_role="status",
            status=messages.ORGANIZING_STATUS,
            severity="status_only",
        )

    def _render_empty_search_denied(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status="구조 탐색 도구로 전환 중", severity=event.severity)

    def _render_inspect_stage_selected(self, event: AgentEvent) -> RenderedEvent:
        stage = str(event.data.get("stage") or "")
        if stage == "source_discovery":
            status = "코드 구조 확인 중"
        elif stage == "targeted_read":
            status = "대표 파일 확인 중"
        elif stage == "finalize":
            status = messages.ORGANIZING_STATUS
        else:
            status = messages.WORKING_STATUS
        return RenderedEvent(status=status, spinner=stage != "finalize", severity=event.severity)

    def _render_inspect_finalization_gate_opened(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.ORGANIZING_STATUS, spinner=True, severity=event.severity)

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

    def _render_generation_workflow_started(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.WORKFLOW_STATUS, spinner=True, severity=event.severity)

    def _render_generation_workflow_finished(self, event: AgentEvent) -> RenderedEvent:
        status = str(event.data.get("status") or "")
        if status == "failed":
            return RenderedEvent(
                transcript="생성 워크플로우 검증을 완료하지 못했습니다.",
                transcript_role="status",
                status=messages.FINAL_GATE_STATUS,
                severity="user_visible",
            )
        return RenderedEvent(status=messages.FINAL_REPORT_STATUS, severity="status_only")

    def _render_approval_requested(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript=messages.APPROVAL_REQUIRED_TITLE,
            transcript_role="approval",
            status=messages.APPROVAL_STATUS,
            severity=event.severity,
        )

    def _render_approval_resolved(self, event: AgentEvent) -> RenderedEvent:
        allowed = event.data.get("allowed")
        action = str(event.data.get("action") or "")
        if allowed is True:
            return RenderedEvent(status=messages.WORKING_STATUS, severity="status_only")
        if action in {"deny", "denied"} or allowed is False:
            return RenderedEvent(
                transcript=messages.APPROVAL_DENIED_STATUS,
                transcript_role="status",
                status=messages.APPROVAL_DENIED_STATUS,
                severity="user_visible",
            )
        return RenderedEvent(status=messages.APPROVAL_STATUS, severity="status_only")

    def _render_tool_loop_detected(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript=messages.RECOVERY_STATUS,
            transcript_role="status",
            status=messages.RECOVERY_STATUS,
            spinner=True,
            severity=event.severity,
        )

    def _render_recovery_state_updated(self, event: AgentEvent) -> RenderedEvent:
        reason = str(event.data.get("reason", ""))
        blocked = bool(event.data.get("blocked", False))
        if reason == "validation_failed":
            status = messages.REPAIR_STATUS if not blocked else messages.FINAL_GATE_STATUS
        elif reason in {"reasoning_only", "empty_response", "stream_timeout"}:
            status = messages.RECOVERY_STATUS
        elif reason in {"tool_loop", "no_progress"}:
            status = messages.FINAL_GATE_STATUS if blocked else messages.MODEL_CONTINUING_STATUS
        else:
            status = messages.RECOVERY_STATUS
        return RenderedEvent(status=status, spinner=not blocked, severity=event.severity)

    def _render_phase_transitioned(self, event: AgentEvent) -> RenderedEvent:
        phase = str(event.data.get("phase") or "")
        if "validation" in phase:
            status = messages.VALIDATION_STATUS
        elif "repair" in phase:
            status = messages.REPAIR_STATUS
        elif "final" in phase:
            status = messages.FINAL_REPORT_STATUS
        else:
            status = messages.WORKING_STATUS
        return RenderedEvent(status=status, spinner=True, severity=event.severity)

    def _render_validation_action_injected(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.VALIDATION_STATUS, spinner=True, severity=event.severity)

    def _render_tool_call_suppressed(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status=messages.FINAL_GATE_STATUS, spinner=False, severity=event.severity)

    def _render_tool_call_schema_denied(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(
            transcript="현재 단계에서 허용되지 않은 도구 호출을 실행하지 않았습니다.",
            transcript_role="status",
            status=messages.FINAL_GATE_STATUS,
            severity="user_visible",
        )

    def _render_event_dropped(self, event: AgentEvent) -> RenderedEvent:
        return RenderedEvent(status="일부 내부 이벤트 생략됨", severity=event.severity)

    def _render_final_answer_ready(self, event: AgentEvent) -> RenderedEvent:
        final_answer = getattr(event, "final_answer", event.message)
        return RenderedEvent(
            transcript=final_answer,
            transcript_role="allCode",
            status=messages.READY_STATUS,
            severity=event.severity,
        )

    def _render_turn_finalized(self, event: AgentEvent) -> RenderedEvent:
        final_answer = getattr(event, "final_answer", event.message)
        status = getattr(event, "status", event.data.get("status", ""))
        prefix = ""
        if status in {"partial", "failed"}:
            prefix = f"{status}: "
        return RenderedEvent(
            transcript=f"{prefix}{final_answer}" if final_answer else event.message,
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

    def _render_source_overview_result(self, result, severity: str) -> RenderedEvent:
        status = "ok" if result.ok else result.error_type or "error"
        target = _tool_target(result)
        file_count = _compact_count(result.metadata.get("file_count"), "files")
        symbol_count = _compact_count(result.metadata.get("symbol_count"), "symbols")
        truncated = " · truncated" if result.metadata.get("truncated") else ""
        metrics = " · ".join(part for part in (file_count, symbol_count) if part)
        metric_suffix = f" · {metrics}" if metrics else ""
        target_suffix = f" {target}" if target else ""
        full_text = result.content or result.error or ""
        if result.ok:
            return RenderedEvent(status="코드 구조 확인 중", severity="status_only")
        return RenderedEvent(
            transcript=f"• inspect{target_suffix} -> {status}{metric_suffix}{truncated}",
            transcript_role="tool",
            status=messages.ORGANIZING_STATUS if result.ok else "도구 실행 완료",
            foldable=bool(full_text),
            fold_title=f"source_overview: {status}",
            fold_full_text=full_text,
            severity="user_visible",
        )


class FoldedToolOutput(CoreModel):
    title: str
    preview: str
    expanded: bool = False
    full_text: str = ""

    def toggle(self) -> "FoldedToolOutput":
        return self.model_copy(update={"expanded": not self.expanded})


def _tool_target(result) -> str:
    metadata = getattr(result, "metadata", {}) or {}
    observation = metadata.get("observation")
    if isinstance(observation, dict) and observation.get("target"):
        return str(observation["target"])
    for key in ("file_path", "path", "query", "command"):
        value = metadata.get(key)
        if value:
            return str(value)
    return ""


def _compact_count(value, label: str) -> str:
    if isinstance(value, int):
        return f"{value} {label}"
    if isinstance(value, str) and value.strip().isdigit():
        return f"{value.strip()} {label}"
    return ""
