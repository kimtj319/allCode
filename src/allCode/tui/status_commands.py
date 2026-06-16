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
        session_id: str | None = None,
    ) -> None:
        self.config = config
        self.tools = tools
        self.session_log_path = Path(session_log_path).expanduser() if session_log_path is not None else None
        self.session_analyzer = session_analyzer or SessionAnalyzer()
        # Where /model and /approval persist changes (the project config file).
        self.project_root = Path(project_root).expanduser() if project_root is not None else Path(config.workspace.root).expanduser()
        self.session_id = session_id

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
        if root == "/init":
            return self._init(args)
        if root == "/doctor":
            return self._doctor()
        if root == "/export":
            return self._export(args)
        if root == "/pr":
            return self._pr(args)
        if root == "/agents":
            return self._agents()
        if root == "/status":
            return self._status(normalized)
        if root == "/debug":
            return self._debug(normalized)
        return f"지원하지 않는 상태 명령입니다: {normalized}"

    def _init(self, args: list[str]) -> str:
        from allCode.workspace.project_init import build_agents_md

        force = bool(args) and args[0].lower() in {"force", "--force", "-f"}
        target = self.project_root / "AGENTS.md"
        if target.exists() and not force:
            return f"AGENTS.md가 이미 있습니다 ({target}). 덮어쓰려면 /init force."
        try:
            content = build_agents_md(self.project_root)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"AGENTS.md 생성에 실패했습니다: {exc}"
        return f"AGENTS.md 초안을 생성했습니다 ({target}). 내용을 검토·수정하세요."

    def _agents(self) -> str:
        from allCode.workspace.agent_definitions import load_agent_definitions

        definitions = load_agent_definitions(self.project_root)
        if not definitions:
            return (
                "정의된 서브에이전트가 없습니다.\n"
                "`.allCode/agents/<name>.md`에 frontmatter(description/model/tools)와 지침을 작성하세요."
            )
        lines = ["정의된 서브에이전트:"]
        for d in definitions:
            tools = f" · tools: {', '.join(d.tools)}" if d.tools else ""
            model = f" · model: {d.model}" if d.model else ""
            lines.append(f"- {d.name}: {d.description}{model}{tools}")
        return "\n".join(lines)

    def _pr(self, args: list[str]) -> str:
        from allCode.workspace.git_ops import create_pull_request

        title = " ".join(args).strip() or None
        result = create_pull_request(self.project_root, title=title)
        return result.message

    def _doctor(self) -> str:
        import os

        m = self.config.model
        key_set = bool(os.environ.get(m.api_key_env))
        host = urlparse(m.base_url).netloc or m.base_url or "(default)"
        checks = [
            ("workspace 존재", Path(self.config.workspace.root).expanduser().exists()),
            (f"API 키({m.api_key_env}) 설정", key_set),
            ("base_url 설정", bool(m.base_url)),
            ("AGENTS.md 존재", (self.project_root / "AGENTS.md").exists()),
            (".allCode/config.yaml 존재", (self.project_root / ".allCode" / "config.yaml").exists()),
        ]
        lines = ["진단(/doctor):"]
        for label, ok in checks:
            lines.append(f"- [{'OK' if ok else '!!'}] {label}")
        lines += [
            "",
            f"- model: {m.model_name}",
            f"- implementation_model: {m.implementation_model_name or '(model과 동일)'}",
            f"- base_url_host: {host}",
            f"- approval: {self.config.approval.mode}",
        ]
        if not key_set:
            lines.append(f"\n⚠ API 키가 없습니다. `export {m.api_key_env}=...` 후 다시 실행하세요.")
        return "\n".join(lines)

    def _export(self, args: list[str]) -> str:
        from allCode.memory.conversation_store import ConversationStore

        if not self.session_id:
            return "내보낼 세션 정보가 없습니다."
        store = ConversationStore(self.project_root)
        exchanges = store.load(self.session_id)
        if not exchanges:
            return "아직 내보낼 대화 기록이 없습니다."
        lines = [f"# allCode 세션 트랜스크립트 ({self.session_id})", ""]
        for index, (prompt, answer) in enumerate(exchanges, start=1):
            lines += [f"## {index}. 사용자", prompt, "", f"## {index}. allCode", answer, ""]
        body = "\n".join(lines)
        target = Path(args[0]).expanduser() if args else (self.project_root / f"allcode-session-{self.session_id[:8]}.md")
        try:
            target.write_text(body, encoding="utf-8")
        except OSError as exc:
            return f"트랜스크립트 저장에 실패했습니다: {exc}"
        return f"대화 {len(exchanges)}턴을 {target}에 저장했습니다."

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
