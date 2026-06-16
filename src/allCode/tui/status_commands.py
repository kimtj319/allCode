"""Runtime status slash command backend."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from allCode.config.schema import AppConfig
from allCode.telemetry import SessionAnalyzer
from allCode.tools.registry import ToolRegistry


class RuntimeStatusCommandService:
    def __init__(
        self,
        *,
        config: AppConfig,
        tools: ToolRegistry,
        session_log_path: str | Path | None = None,
        session_analyzer: SessionAnalyzer | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.config = config
        self.tools = tools
        self.session_log_path = Path(session_log_path).expanduser() if session_log_path is not None else None
        self.session_analyzer = session_analyzer or SessionAnalyzer()
        # Where /model and /approval persist changes (the project config file).
        self.project_root = Path(project_root).expanduser() if project_root is not None else Path(config.workspace.root).expanduser()

    async def handle(self, command: str) -> str:
        normalized = " ".join(command.strip().split())
        root = normalized.split(maxsplit=1)[0]
        args = normalized.split()[1:]
        if root == "/tools":
            return self._tools(normalized)
        if root == "/model":
            return self._model(args)
        if root == "/approval":
            return self._approval(args)
        if root == "/config":
            return self._config()
        if root == "/status":
            return self._status(normalized)
        if root == "/debug":
            return self._debug(normalized)
        return f"지원하지 않는 상태 명령입니다: {normalized}"

    def _persist(self, section: str, values: dict) -> Path:
        from allCode.config.manager import update_project_config_file

        return update_project_config_file(self.project_root, {section: values})

    def _approval(self, args: list[str]) -> str:
        if not args:
            return (
                f"현재 승인 모드: {self.config.approval.mode}\n"
                "- /approval auto : 권한 요청 없이 모두 진행\n"
                "- /approval ask  : 변경/셸 실행 전 승인 요청(기존과 동일)"
            )
        mode = args[0].strip().lower()
        if mode not in {"auto", "ask"}:
            return "사용법: /approval auto | /approval ask"
        self.config.approval.mode = mode  # in-place: next turn picks it up
        try:
            path = self._persist("approval", {"mode": mode})
        except Exception as exc:  # noqa: BLE001
            return f"승인 모드를 '{mode}'로 바꿨지만 설정 파일 저장에 실패했습니다: {exc}"
        note = "권한 요청 없이 모두 진행합니다." if mode == "auto" else "변경/셸 실행 전 승인을 요청합니다."
        return f"승인 모드를 '{mode}'로 변경하고 저장했습니다 ({path}). {note}"

    def _tools(self, command: str) -> str:
        detailed = "desc" in command.split()[1:]
        definitions = sorted(self.tools.definitions(), key=lambda item: (item.group, item.name))
        if not definitions:
            return "등록된 도구가 없습니다."
        lines = ["사용 가능한 도구:"]
        for definition in definitions:
            marker = "read" if definition.read_only else "write"
            approval = "approval" if definition.requires_approval else "no-approval"
            line = f"- {definition.name} [{definition.group}/{marker}/{definition.risk}/{approval}]"
            if detailed and definition.description:
                line = f"{line}: {definition.description}"
            lines.append(line)
        return "\n".join(lines)

    def _model(self, args: list[str] | None = None) -> str:
        args = args or []
        if args:
            return self._model_set(args)
        parsed = urlparse(self.config.model.base_url)
        host = parsed.netloc or self.config.model.base_url
        return "\n".join(
            [
                "모델 설정:",
                f"- model: {self.config.model.model_name}",
                f"- implementation_model: {self.config.model.implementation_model_name or '(model과 동일)'}",
                f"- base_url_host: {host}",
                f"- api_key_env: {self.config.model.api_key_env}",
                "- api_key_value: [hidden]",
                "",
                "변경: /model <모델명> · /model impl <모델명> · /model base <url>",
            ]
        )

    def _model_set(self, args: list[str]) -> str:
        # /model impl <name> | /model base <url> | /model <name>
        field_aliases = {
            "impl": ("implementation_model_name", "구현 모델"),
            "implementation": ("implementation_model_name", "구현 모델"),
            "base": ("base_url", "base_url"),
            "base_url": ("base_url", "base_url"),
            "name": ("model_name", "모델"),
            "model": ("model_name", "모델"),
        }
        if args[0].lower() in field_aliases and len(args) >= 2:
            attr, label = field_aliases[args[0].lower()]
            value = " ".join(args[1:]).strip()
        else:
            attr, label, value = "model_name", "모델", " ".join(args).strip()
        if not value:
            return "사용법: /model <모델명> | /model impl <모델명> | /model base <url>"
        setattr(self.config.model, attr, value)  # in-place: next turn picks it up
        try:
            path = self._persist("model", {attr: value})
        except Exception as exc:  # noqa: BLE001
            return f"{label}을(를) '{value}'로 바꿨지만 설정 파일 저장에 실패했습니다: {exc}"
        return f"{label}을(를) '{value}'로 변경하고 저장했습니다 ({path}). 다음 턴부터 적용됩니다."

    def _config(self) -> str:
        web_backend = self.config.web.backend if self.config.web.search_url else "disabled"
        return "\n".join(
            [
                "실행 설정:",
                f"- workspace: {self.config.workspace.root}",
                f"- approval: {self.config.approval.mode}",
                f"- sandbox_enabled: {self.config.workspace.sandbox_enabled}",
                f"- web_backend: {web_backend}",
            ]
        )

    def _status(self, command: str) -> str:
        if command not in {"/status", "/status last"}:
            return "지원하는 상태 명령: /status last"
        diagnostics = self._diagnostics()
        if diagnostics is None:
            return "아직 분석할 세션 로그가 없습니다."
        return diagnostics.summary()

    def _debug(self, command: str) -> str:
        if command not in {"/debug", "/debug last"}:
            return "지원하는 디버그 명령: /debug last"
        diagnostics = self._diagnostics()
        if diagnostics is None:
            return "아직 분석할 세션 로그가 없습니다."
        return json.dumps(diagnostics.model_dump(mode="json"), ensure_ascii=False, indent=2)

    def _diagnostics(self):
        if self.session_log_path is None or not self.session_log_path.exists():
            return None
        return self.session_analyzer.analyze(self.session_log_path)
