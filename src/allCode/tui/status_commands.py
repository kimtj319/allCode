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
    ) -> None:
        self.config = config
        self.tools = tools
        self.session_log_path = Path(session_log_path).expanduser() if session_log_path is not None else None
        self.session_analyzer = session_analyzer or SessionAnalyzer()

    async def handle(self, command: str) -> str:
        normalized = " ".join(command.strip().split())
        root = normalized.split(maxsplit=1)[0]
        if root == "/tools":
            return self._tools(normalized)
        if root == "/model":
            return self._model()
        if root == "/config":
            return self._config()
        if root == "/status":
            return self._status(normalized)
        if root == "/debug":
            return self._debug(normalized)
        return f"지원하지 않는 상태 명령입니다: {normalized}"

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

    def _model(self) -> str:
        parsed = urlparse(self.config.model.base_url)
        host = parsed.netloc or self.config.model.base_url
        return "\n".join(
            [
                "모델 설정:",
                f"- model: {self.config.model.model_name}",
                f"- base_url_host: {host}",
                f"- api_key_env: {self.config.model.api_key_env}",
                "- api_key_value: [hidden]",
            ]
        )

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
