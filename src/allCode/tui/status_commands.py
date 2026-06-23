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
        context_builder=None,
    ) -> None:
        self.config = config
        self.tools = tools
        self.session_log_path = Path(session_log_path).expanduser() if session_log_path is not None else None
        self.session_analyzer = session_analyzer or SessionAnalyzer()
        # Where /model and /approval persist changes (the project config file).
        self.project_root = Path(project_root).expanduser() if project_root is not None else Path(config.workspace.root).expanduser()
        self.session_id = session_id
        # Used by /resume to load a prior session's history into this session.
        self.context_builder = context_builder

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
        if root == "/plan":
            return self._plan(args)
        if root == "/thinking":
            return self._thinking(args)
        if root == "/permissions":
            return self._permissions(normalized)
        if root == "/mcp":
            return self._mcp(normalized)
        if root == "/skills":
            return self._skills()
        if root == "/resume":
            return self._resume(args)
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

    def _plan(self, args: list[str]) -> str:
        """Toggle Claude Code-style plan mode (session-scoped, not persisted).

        On: every turn is read-only — the agent investigates and proposes an
        implementation plan, making no file changes. Off: normal execution."""
        current = bool(getattr(self.config.agent, "plan_mode", False))
        if not args:
            target = not current  # bare /plan toggles
        else:
            verb = args[0].strip().lower()
            if verb in {"on", "start", "enable"}:
                target = True
            elif verb in {"off", "exit", "disable", "stop"}:
                target = False
            else:
                return "사용법: /plan [on|off] (인자 없이 입력하면 토글)"
        self.config.agent.plan_mode = target  # in-place: next turn picks it up (not persisted)
        if target:
            return (
                "계획 모드 ON — 읽기 전용입니다. 코드를 변경하지 않고 워크스페이스를 분석해 "
                "실행 계획을 제시합니다. 계획을 실행하려면 `/plan off` 후 진행하세요."
            )
        return "계획 모드 OFF — 일반 실행 모드로 돌아갑니다."

    def _thinking(self, args: list[str]) -> str:
        current = self.config.ui.show_thinking
        if not args:
            state = "on" if current else "off"
            return (
                f"추론 표시(/thinking): {state}\n"
                "- /thinking on  : 모델의 사고 과정을 흐리게 함께 표시\n"
                "- /thinking off : 사고 과정을 숨김(기본값)"
            )
        choice = args[0].strip().lower()
        if choice not in {"on", "off"}:
            return "사용법: /thinking on | /thinking off"
        value = choice == "on"
        self.config.ui.show_thinking = value  # in-place: next turn picks it up
        try:
            path = self._persist("ui", {"show_thinking": value})
        except Exception as exc:  # noqa: BLE001
            return f"추론 표시를 '{choice}'로 바꿨지만 설정 파일 저장에 실패했습니다: {exc}"
        note = "이제 모델의 사고 과정을 흐리게 표시합니다." if value else "사고 과정을 숨깁니다."
        return f"추론 표시를 '{choice}'로 변경하고 저장했습니다 ({path}). {note} 다음 턴부터 적용됩니다."

    def _skills(self) -> str:
        """List skills the model can load on demand via the skill tool."""
        from allCode.workspace.skills import load_skill_definitions

        skills = load_skill_definitions(self.project_root)
        if not skills:
            return (
                "정의된 스킬이 없습니다.\n"
                ".allCode/skills/<name>/SKILL.md (또는 .allCode/skills/<name>.md)에 "
                "frontmatter(description)와 지침을 작성하세요. 모델이 관련 작업에서 skill(<name>)로 로드합니다."
            )
        lines = ["정의된 스킬:"]
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.description}")
        lines.append("모델은 관련 작업 시 skill(<name>) 도구로 해당 지침을 로드합니다.")
        return "\n".join(lines)

    def _resume(self, args: list[str]) -> str:
        """List recent sessions, or load one's history into the current session.

        With no argument it shows a picker-style list. With <id|name> it replays
        that session's exchanges into the live context builder so the next turn
        continues from it (the current session id keeps logging new turns)."""
        from allCode.memory.conversation_store import ConversationStore

        store = ConversationStore(self.config.workspace.root)
        # A session name may contain spaces, so keep the whole argument string
        # (minus an explicit list/ls keyword) as the reference.
        ref = "" if (args and args[0].lower() in {"list", "ls"}) else " ".join(args)
        if not ref:
            entries = store.list_sessions_with_meta()
            if not entries:
                return "이전 세션이 없습니다. 첫 대화를 시작하면 세션이 기록됩니다."
            lines = ["최근 세션 (이어가려면 /resume <id|name>):"]
            for entry in entries[:10]:
                label = f"[{entry.name}] " if entry.name else ""
                current = " ← 현재" if entry.session_id == self.session_id else ""
                lines.append(
                    f"  - {entry.session_id[:8]}  {label}{entry.title}  ({entry.turns}턴){current}"
                )
            return "\n".join(lines)

        resolved = store.resolve(ref)
        if not resolved:
            return f"세션을 찾을 수 없습니다: {ref} (/resume 로 목록을 확인하세요)."
        if resolved == self.session_id:
            return "이미 현재 세션입니다."
        if self.context_builder is None or not self.session_id:
            return "이 환경에서는 세션을 이어올 수 없습니다 (컨텍스트 빌더 없음)."
        exchanges = store.load(resolved)
        restored = 0
        for role, text in exchanges:
            if role == "user":
                self.context_builder.remember_user_prompt(self.session_id, text)
                self.context_builder.remember_user_note(self.session_id, text)
                restored += 1
            elif role == "assistant":
                self.context_builder.remember_assistant_summary(self.session_id, text)
        if restored == 0:
            return f"세션 {resolved[:8]}에 불러올 대화가 없습니다."
        return f"세션 {resolved[:8]}의 {restored}개 대화를 현재 세션에 불러왔습니다. 이어서 진행하세요."

    def _mcp(self, command: str) -> str:
        """List/add/remove MCP servers in the project config (effective next run)."""
        from allCode.config import mcp_admin

        parts = command.split()
        sub = parts[1].lower() if len(parts) > 1 else "list"
        if sub in {"list", "ls"}:
            servers = mcp_admin.list_servers(self.project_root)
            active = sorted(d.name for d in self.tools.definitions() if d.group == "mcp")
            lines = ["MCP 서버 (config.yaml):"]
            lines += [f"  - {mcp_admin.describe_server(s)}" for s in servers] or ["  (없음)"]
            lines.append(
                f"이번 세션 활성 MCP 도구: {len(active)}개" + (f" — {', '.join(active)}" if active else "")
            )
            lines.append(
                "추가: /mcp add <name> <command> [args...] · HTTP: /mcp add <name> --http <url> · 제거: /mcp remove <name>"
            )
            return "\n".join(lines)
        if sub == "add":
            rest = parts[2:]
            if not rest:
                return "사용법: /mcp add <name> <command> [args...]  |  /mcp add <name> --http <url>"
            name, spec = rest[0], rest[1:]
            try:
                if spec and spec[0] in {"--http", "--sse", "--url"}:
                    if len(spec) < 2:
                        return "사용법: /mcp add <name> --http <url>"
                    transport = "sse" if spec[0] == "--sse" else "http"
                    path = mcp_admin.add_server(self.project_root, name, url=spec[1], transport=transport)
                elif spec:
                    path = mcp_admin.add_server(self.project_root, name, command=spec[0], args=spec[1:])
                else:
                    return "stdio 서버는 command가 필요합니다: /mcp add <name> <command> [args...]"
            except Exception as exc:  # noqa: BLE001
                return f"MCP 서버 추가에 실패했습니다: {exc}"
            return f"MCP 서버 '{name}'를 추가하고 저장했습니다 ({path}). 다음 실행부터 도구로 로드됩니다."
        if sub in {"remove", "rm", "delete"}:
            if len(parts) < 3:
                return "사용법: /mcp remove <name>"
            path, removed = mcp_admin.remove_server(self.project_root, parts[2])
            if not removed:
                return f"해당 이름의 MCP 서버가 없습니다: {parts[2]}"
            return f"MCP 서버 '{parts[2]}'를 제거했습니다 ({path}). 다음 실행부터 적용됩니다."
        return "지원: /mcp [list|add|remove]"

    def _permissions(self, command: str) -> str:
        """Show or persist permission rules (allow/deny) to .allCode/config.yaml.

        Unlike the session-only "allow for session" choice, a rule added here is
        written to the project config so it persists across runs."""
        approval = self.config.approval
        parts = command.split(maxsplit=2)  # ["/permissions", action, pattern]
        if len(parts) < 2:
            allow = "\n".join(f"  - {rule}" for rule in approval.allow) or "  (없음)"
            deny = "\n".join(f"  - {rule}" for rule in approval.deny) or "  (없음)"
            session = "\n".join(f"  - {rule}" for rule in approval.session_allow) or "  (없음)"
            return (
                f"승인 모드: {approval.mode}\n"
                f"허용(allow) 규칙:\n{allow}\n"
                f"거부(deny) 규칙:\n{deny}\n"
                f"이번 세션 한시 허용:\n{session}\n"
                "추가: /permissions allow <규칙> · /permissions deny <규칙>  "
                "(예: `Bash(npm run test*)`, `Write(src/**)`) — config.yaml에 영구 저장됩니다."
            )
        action = parts[1].strip().lower()
        pattern = parts[2].strip() if len(parts) > 2 else ""
        if action not in {"allow", "deny"} or not pattern:
            return "사용법: /permissions allow <규칙> | /permissions deny <규칙>"
        rules = approval.allow if action == "allow" else approval.deny
        if pattern in rules:
            return f"이미 {action} 목록에 있는 규칙입니다: {pattern}"
        rules.append(pattern)  # in-place: this turn's ApprovalManager already built, next turn picks it up
        try:
            path = self._persist("approval", {"allow": approval.allow, "deny": approval.deny})
        except Exception as exc:  # noqa: BLE001
            return f"규칙을 추가했지만 설정 파일 저장에 실패했습니다: {exc}"
        return f"{action} 규칙을 추가하고 저장했습니다 ({path}): {pattern}"

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
