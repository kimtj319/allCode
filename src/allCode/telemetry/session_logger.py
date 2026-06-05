"""Append-only JSONL logger for observable agent execution."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from allCode.config.schema import AppConfig
from allCode.core.events import AgentEvent
from allCode.memory.redaction import redact_data
from allCode.telemetry.paths import make_session_name, session_log_path, utc_now
from allCode.telemetry.schema import AgentLogRecord


class AgentSessionLogger:
    """Persist all agent events and runtime milestones to one session JSONL file."""

    def __init__(
        self,
        *,
        path: Path,
        session_id: str,
        session_name: str,
        workspace: str,
        model: str,
        approval_mode: str,
        fallback_path: Path | None = None,
    ) -> None:
        self.path = path.expanduser()
        self._fallback_path = fallback_path.expanduser() if fallback_path is not None else None
        self.session_id = session_id
        self.session_name = session_name
        self.workspace = workspace
        self.model = model
        self.approval_mode = approval_mode
        self._sequence = 0
        self._lock = asyncio.Lock()

    @classmethod
    def create(
        cls,
        *,
        config: AppConfig,
        base_dir: Path | None = None,
        now: datetime | None = None,
        session_id: str | None = None,
        session_name: str | None = None,
    ) -> "AgentSessionLogger":
        current = now or utc_now()
        resolved_session_id = session_id or uuid4().hex
        workspace_path = Path(config.workspace.root).expanduser().resolve()
        resolved_name = session_name or make_session_name(
            workspace_label=workspace_path.name or "workspace",
            now=current,
            suffix=resolved_session_id[:8],
        )
        return cls(
            path=session_log_path(resolved_name, base_dir=base_dir, now=current),
            session_id=resolved_session_id,
            session_name=resolved_name,
            workspace=str(workspace_path),
            model=config.model.model_name,
            approval_mode=config.approval.mode,
            fallback_path=session_log_path(
                resolved_name,
                base_dir=workspace_path / ".allCode" / "session",
                now=current,
            ),
        )

    async def handle_event(self, event: AgentEvent) -> None:
        payload = event.model_dump(mode="json")
        payload.setdefault("normalized", self._normalized_payload(event, payload))
        await self.log(
            category=self._category_for_event(event.event_type),
            event_type=event.event_type,
            severity=event.severity,
            message=event.message,
            turn_id=event.turn_id,
            trace_id=event.trace_id or event.turn_id,
            span_id=event.span_id or event.id,
            parent_span_id=event.parent_span_id,
            record_kind=self._record_kind_for_event(event.event_type, payload),
            payload=payload,
        )

    async def log(
        self,
        *,
        category: str,
        event_type: str,
        payload: dict,
        severity: str = "debug_only",
        message: str = "",
        turn_id: str | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        record_kind: str = "event",
    ) -> None:
        async with self._lock:
            self._sequence += 1
            redacted_payload = redact_data(payload)
            if event_type.startswith("model_") or event_type == "turn_result_ready":
                redacted_payload = self._with_log_metrics(redacted_payload)
            record = AgentLogRecord(
                sequence=self._sequence,
                session_id=self.session_id,
                session_name=self.session_name,
                turn_id=turn_id,
                trace_id=trace_id or turn_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                record_kind=record_kind,
                category=category,
                event_type=event_type,
                severity=severity,
                message=message,
                workspace=self.workspace,
                model=self.model,
                approval_mode=self.approval_mode,
                payload=redacted_payload,
            )
            line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            self._append_line(line)

    def _append_line(self, line: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
            return
        except OSError:
            if self._fallback_path is None or self.path == self._fallback_path:
                raise
        self.path = self._fallback_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _with_log_metrics(self, payload: dict) -> dict:
        measured = dict(payload)
        try:
            measured.setdefault(
                "log_metrics",
                {"payload_chars": len(json.dumps(payload, ensure_ascii=False, sort_keys=True))},
            )
        except (TypeError, ValueError):
            measured.setdefault("log_metrics", {"payload_chars": 0})
        return measured

    @staticmethod
    def _record_kind_for_event(event_type: str, payload: dict) -> str:
        if event_type == "tool_call_requested":
            return "action"
        if event_type in {"tool_execution_finished", "source_overview_collected"}:
            return "observation"
        if event_type in {"tool_policy_checked", "tool_approval_checked", "approval_requested", "approval_resolved"}:
            return "mediation"
        if event_type in {"model_request_prepared", "model_response_parsed", "model_metrics_recorded"}:
            return "model_span"
        if event_type == "recovery_state_updated":
            return "recovery"
        if event_type in {"turn_failed", "tool_loop_detected"}:
            return "agent_error"
        normalized = payload.get("normalized")
        if isinstance(normalized, dict) and normalized.get("error_type"):
            return "agent_error"
        return "event"

    @staticmethod
    def _normalized_payload(event: AgentEvent, payload: dict) -> dict:
        if event.event_type == "tool_call_requested":
            tool_call = payload.get("tool_call", {})
            return {
                "kind": "action",
                "tool_name": tool_call.get("name"),
                "action_id": tool_call.get("id"),
                "target": _target_from_arguments(tool_call.get("arguments", {})),
            }
        if event.event_type == "tool_execution_finished":
            result = payload.get("result", {})
            metadata = result.get("metadata", {})
            observation = metadata.get("observation") if isinstance(metadata, dict) else None
            return {
                "kind": "observation",
                "tool_name": result.get("name"),
                "action_id": result.get("call_id"),
                "ok": result.get("ok"),
                "error_type": result.get("error_type"),
                "observation": observation if isinstance(observation, dict) else {},
            }
        if event.event_type == "model_metrics_recorded":
            return {"kind": "model_metrics", **dict(payload.get("data", {}))}
        if event.event_type == "source_overview_collected":
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            return {
                "kind": "source_overview",
                "tool_name": "source_overview",
                "target": data.get("target"),
                "file_count": data.get("file_count"),
                "symbol_count": data.get("symbol_count"),
                "truncated": data.get("truncated"),
                "representative_read_count": len(data.get("representative_reads") or []),
                "coverage_ratio": (data.get("coverage") or {}).get("coverage_ratio")
                if isinstance(data.get("coverage"), dict)
                else None,
            }
        if event.event_type == "empty_search_denied":
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            return {
                "kind": "search_invalid",
                "tool_name": "search_files",
                "target": data.get("target"),
                "required_next_action": data.get("required_next_action"),
            }
        if event.event_type == "inspect_stage_selected":
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            return {
                "kind": "inspect_stage",
                "stage": data.get("stage"),
                "allowed_tools": data.get("allowed_tools"),
                "evidence_complete": data.get("evidence_complete"),
            }
        if event.event_type == "inspect_finalization_gate_opened":
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            return {
                "kind": "inspect_finalization",
                "target": data.get("source_overview_paths") or data.get("inspected_paths"),
                "round": data.get("round"),
            }
        if event.event_type == "recovery_state_updated":
            return {"kind": "recovery", **dict(payload.get("data", {}))}
        return {"kind": event.event_type}

    @staticmethod
    def _category_for_event(event_type: str) -> str:
        if event_type.startswith("model_"):
            return "model"
        if event_type.startswith("tool_"):
            return "tool"
        if event_type in {"source_overview_collected", "empty_search_denied"}:
            return "tool"
        if event_type.startswith("inspect_"):
            return "routing"
        if event_type.startswith("approval_"):
            return "approval"
        if event_type.startswith("routing_"):
            return "routing"
        if event_type.startswith("context_"):
            return "context"
        if event_type.startswith("validation_"):
            return "validation"
        if event_type.startswith("generation_"):
            return "generation"
        if event_type.startswith("recovery_"):
            return "recovery"
        if event_type.startswith("phase_") or event_type.startswith("repair_"):
            return "recovery"
        if event_type == "validation_action_injected":
            return "validation"
        if event_type.startswith("turn_") or event_type == "final_answer_ready":
            return "turn"
        return "event"


def _target_from_arguments(arguments: object) -> str | None:
    if not isinstance(arguments, dict):
        return None
    for key in ("file_path", "path", "query", "command", "url"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
