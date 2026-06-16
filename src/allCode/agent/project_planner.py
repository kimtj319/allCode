"""Model-backed project planning for generation workflow."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from allCode.agent.project_plan_paths import looks_like_planned_file_path
from allCode.agent.task_plan import ApiObligation, PlannedFile, ProjectPlan, ValidationCommand
from allCode.agent.workflow_report_artifact import ensure_requested_report_artifact
from allCode.core.models import Message
from allCode.llm.client import LLMClient
from allCode.llm.settings import ModelSettings


class ModelProjectPlanner:
    """Ask the model for a compact, validated project plan.

    The planner is deliberately optional. Any invalid, unsafe, or non-JSON
    response falls back to the deterministic language strategy path.
    """

    def __init__(self, *, llm_client: LLMClient, settings: ModelSettings) -> None:
        self._llm_client = llm_client
        self._settings = settings

    # The model produces a good plan most of the time but its JSON is
    # occasionally malformed; a single miss would fall back to a bare scaffold.
    # Retry a few times so an intermittent bad response does not cost the whole
    # multi-file plan.
    _PLAN_ATTEMPTS = 3

    async def create_plan(
        self,
        prompt: str,
        *,
        target_hint: str | None = None,
        task_digest: str | None = None,
    ) -> ProjectPlan | None:
        planner_settings = self._settings.model_copy(
            update={
                "temperature": 0.0,
                "max_output_tokens": max(self._settings.max_output_tokens, 6000),
            }
        )
        for _ in range(self._PLAN_ATTEMPTS):
            plan = await self._attempt_plan(
                prompt, target_hint=target_hint, task_digest=task_digest, settings=planner_settings
            )
            if plan is not None:
                return plan
        return None

    async def _attempt_plan(
        self,
        prompt: str,
        *,
        target_hint: str | None,
        task_digest: str | None,
        settings: ModelSettings,
    ) -> ProjectPlan | None:
        try:
            response = await self._llm_client.complete(
                self._messages(prompt, target_hint=target_hint, task_digest=task_digest),
                tools=[],
                settings=settings,
            )
        except Exception:
            return None
        payload = _extract_json_object(response.final_text)
        if payload is None:
            return None
        try:
            plan = ProjectPlan.model_validate(_coerce_plan_payload(payload))
        except Exception:
            return None
        return _sanitize_plan(plan, prompt=prompt, target_hint=target_hint)

    def _messages(self, prompt: str, *, target_hint: str | None, task_digest: str | None) -> Sequence[Message]:
        target_line = f"Explicit target hint: {target_hint}" if target_hint else "Explicit target hint: none"
        planning_context = _planning_context(prompt, target_hint=target_hint, task_digest=task_digest)
        return [
            Message(
                role="system",
                content=(
                    "You are a project planning component for allCode. "
                    "Return only one JSON object matching this schema: "
                    "{target_root, language, constraints, files, validation_commands, tasks, api_obligations}. "
                    "Each file item must have path, purpose, stage, content, required. "
                    "Each api_obligation item must have path, symbol, reason. "
                    "Allowed stages are skeleton, implementation, tests. "
                    "Use relative paths only, never absolute paths or '..'. "
                    "Make files complete and runnable. Do not include markdown fences. "
                    "Validation commands must be test/build commands only. "
                    "When the planning context lists required exact filenames, use those paths verbatim instead of generic names like main.py or test_main.py. "
                    "You must plan specific files and target constraints to fully satisfy all prompt-derived artifact obligations listed in the planning context. "
                    "When tests are planned, they must import or call the public classes, functions, methods, or command entrypoints listed in api_obligations and assert expected behavior. "
                    "Do not generate simple hello-world smoke tests for a featureful request. "
                    "Do not include private symbols, TypeVars, or internal-only helpers in api_obligations."
                ),
            ),
            Message(
                role="user",
                content=(
                    f"{target_line}\n"
                    f"{planning_context}\n\n"
                    "Create a skeleton-first implementation plan for this request. "
                    "If the request mentions a directory, either set target_root to that directory "
                    "and make file paths relative to it, or set target_root to '.' and include the directory in file paths. "
                    "The plan must include implementation files, tests when validation is requested or implied, "
                    "and validation commands that can run without installing external services. "
                    "For each prompt-derived artifact obligation, include at least one source/document/test plan item or api_obligation that makes the obligation verifiable. "
                    "Tests must exercise requested behavior, not only import a placeholder function.\n\n"
                    f"User request:\n{prompt}"
                ),
            ),
        ]


def _planning_context(prompt: str, *, target_hint: str | None, task_digest: str | None) -> str:
    lines = ["Planning context:"]
    if target_hint:
        lines.append(f"- Target root: {target_hint}")
    required_names = _explicit_required_names(prompt)
    if required_names:
        lines.append("- Required exact filenames (use verbatim, do not rename to main.py/test_main.py):")
        lines.extend(f"  - {item}" for item in required_names[:8])
    obligations = _artifact_obligations(prompt)
    if obligations:
        lines.append("- Prompt-derived artifact obligations:")
        lines.extend(f"  - {item}" for item in obligations[:12])
    constraints = _generation_constraints(prompt)
    if constraints:
        lines.append("- Prompt-derived constraints:")
        lines.extend(f"  - {item}" for item in constraints[:8])
    if task_digest:
        lines.append("- Compact task state:")
        lines.append(_indent(_compact(task_digest, limit=1800)))
    return "\n".join(lines)


def _explicit_required_names(prompt: str) -> list[str]:
    """Filenames the prompt names verbatim (e.g. breaker.py, test_breaker.py)."""
    names: list[str] = []
    for raw in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*\.py)\b", prompt):
        if raw not in names:
            names.append(raw)
    return names


def _artifact_obligations(prompt: str) -> list[str]:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", prompt.lower())
    obligation_terms: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("CLI entrypoint", ("cli", "entrypoint", "command line", "진입점", "명령어", "커맨드")),
        ("configuration loader", ("config", "configuration", "settings", "설정", "환경설정")),
        ("task or command registry", ("registry", "레지스트리", "등록기")),
        ("job/task runner", ("runner", "job runner", "task runner", "실행기", "작업 실행")),
        ("retry/backoff behavior", ("retry", "backoff", "재시도", "백오프")),
        ("structured audit logging", ("jsonl", "audit", "logger", "logging", "감사", "로거", "로그")),
        ("plugin-like modules", ("plugin", "plugins", "extension", "플러그인", "확장")),
        ("HTTP API endpoints/routes", ("endpoint", "route", "router", "fastapi", "flask", "api", "엔드포인트", "라우터", "라우트", "에이피아이")),
        ("request/response schema models", ("schema", "pydantic", "dto", "model", "스키마", "모델")),
        ("service layer / business logic module", ("service", "infrastructure", "인프라", "서비스")),
        ("email/SMTP sending module", ("smtp", "email", "mail", "이메일", "메일", "발송")),
        ("data store / repository", ("storage", "repository", "store", "database", "db", "저장소", "리포지토리", "데이터베이스")),
        ("dependency manifest (requirements/pyproject)", ("requirements", "requirements.txt", "pyproject", "dependencies", "의존성", "패키지 목록")),
        ("tests", ("pytest", "tests", "unit test", "테스트", "검증")),
        ("README or user documentation", ("readme", "docs", "documentation", "문서", "사용법")),
    )
    obligations: list[str] = []
    for label, terms in obligation_terms:
        if any(term in lowered or term.replace(" ", "") in compact for term in terms):
            obligations.append(label)
    return obligations


def _generation_constraints(prompt: str) -> list[str]:
    lowered = prompt.lower()
    constraints: list[str] = []
    if any(term in lowered for term in ("standard library", "stdlib", "no external package", "no external dependency")) or any(
        term in prompt for term in ("표준 라이브러리", "외부 패키지 사용 금지", "외부 의존성 금지")
    ):
        constraints.append("Use only the language standard library unless the prompt explicitly allows dependencies.")
    if any(term in lowered for term in ("validate", "validation", "run tests", "pytest")) or any(
        term in prompt for term in ("검증", "테스트 실행", "테스트까지")
    ):
        constraints.append("Include validation commands that can run from the target root.")
    if any(term in lowered for term in ("existing file", "do not modify existing")) or any(
        term in prompt for term in ("기존 파일 수정 금지", "기존 파일 변경 금지")
    ):
        constraints.append("Keep generated files inside the requested target root.")
    return constraints


def _compact(text: str, *, limit: int) -> str:
    compacted = "\n".join(line.rstrip() for line in str(text or "").splitlines() if line.strip())
    if len(compacted) <= limit:
        return compacted
    return compacted[:limit].rstrip() + "\n[task digest truncated]"


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines() if line.strip())


# Allowed keys per nested model (CoreModel uses extra="forbid", so any stray
# key the model invents — e.g. a task "name" or a file "symbol" — hard-fails
# validation and would otherwise discard an entire good plan).
_TASK_KEYS = {"id", "description", "step", "status", "evidence"}
_FILE_KEYS = {"path", "purpose", "stage", "content", "required"}
_VALIDATION_KEYS = {"command", "cwd", "timeout_seconds", "environment"}
_OBLIGATION_KEYS = {"path", "symbol", "reason"}


def _normalize_constraints(value) -> list[str]:
    """Coerce constraints into a list[str] regardless of the model's shape.

    Models sometimes emit constraints as a string, or as an object like
    ``{"python_version": "3.9+", "dependencies": [...]}`` instead of the
    schema's list[str]. Flatten any of these to readable strings rather than
    rejecting the plan."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        items: list[str] = []
        for key, val in value.items():
            if isinstance(val, (list, tuple)):
                val = ", ".join(str(v) for v in val)
            items.append(f"{key}: {val}")
        return items
    if isinstance(value, (list, tuple)):
        flattened: list[str] = []
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    flattened.append(item.strip())
            elif isinstance(item, dict):
                flattened.extend(_normalize_constraints(item))
            else:
                flattened.append(str(item))
        return flattened
    return [str(value)]


def _coerce_plan_payload(payload: dict) -> dict:
    """Coerce a loosely-shaped model plan into the strict ProjectPlan schema.

    Capable models reliably produce a good multi-file plan but with surface
    variations the strict (extra="forbid") schema rejects wholesale: constraints
    as a dict/string, validation_commands/tasks as plain strings, tasks carrying
    an extra ``name`` field, files carrying stray keys, or empty content (bodies
    are generated downstream). Rather than discard the whole plan and fall back
    to a bare single-module scaffold, normalize these shapes and drop unknown
    keys so the real plan survives.
    """

    if not isinstance(payload, dict):
        return payload
    data = dict(payload)

    if "constraints" in data:
        data["constraints"] = _normalize_constraints(data.get("constraints"))

    commands = data.get("validation_commands")
    if isinstance(commands, list):
        coerced_commands: list = []
        for item in commands:
            if isinstance(item, str):
                coerced_commands.append({"command": item})
            elif isinstance(item, dict):
                coerced_commands.append({k: v for k, v in item.items() if k in _VALIDATION_KEYS})
            else:
                coerced_commands.append(item)
        data["validation_commands"] = coerced_commands

    tasks = data.get("tasks")
    if isinstance(tasks, list):
        coerced_tasks: list = []
        for item in tasks:
            if isinstance(item, str):
                coerced_tasks.append({"description": item, "step": "implementation"})
            elif isinstance(item, dict):
                task = {k: v for k, v in item.items() if k in _TASK_KEYS}
                # Models often label tasks with "name"/"title" instead of "description".
                if not task.get("description"):
                    task["description"] = str(item.get("name") or item.get("title") or "").strip()
                task.setdefault("step", "implementation")
                task.setdefault("description", "")
                coerced_tasks.append(task)
            else:
                coerced_tasks.append(item)
        data["tasks"] = coerced_tasks

    obligations = data.get("api_obligations")
    if isinstance(obligations, list):
        coerced_obligations: list = []
        for item in obligations:
            if isinstance(item, dict):
                coerced_obligations.append({k: v for k, v in item.items() if k in _OBLIGATION_KEYS})
            else:
                coerced_obligations.append(item)
        data["api_obligations"] = coerced_obligations

    files = data.get("files")
    if isinstance(files, list):
        coerced_files: list = []
        for item in files:
            if not isinstance(item, dict):
                coerced_files.append(item)
                continue
            file = {k: v for k, v in item.items() if k in _FILE_KEYS}
            file.setdefault("stage", "implementation")
            file.setdefault("purpose", "")
            file.setdefault("required", True)
            if not file.get("content"):
                # Implementation/test bodies are (re)generated per file later, so a
                # placeholder is sufficient to pass the non-empty content contract.
                purpose = str(file.get("purpose") or "").strip()
                file["content"] = f"# {purpose}\n" if purpose else "# generated\n"
            coerced_files.append(file)
        data["files"] = coerced_files

    return data


def _extract_json_object(text: str) -> dict | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _sanitize_plan(plan: ProjectPlan, *, prompt: str = "", target_hint: str | None = None) -> ProjectPlan | None:
    original_root = _safe_root(plan.target_root)
    forced_root = _safe_root(target_hint) if target_hint else None
    if original_root is None or (target_hint and forced_root is None):
        return None
    target_root = forced_root or original_root
    files: list[PlannedFile] = []
    for planned_file in plan.files:
        path = _safe_relative_path(planned_file.path)
        if path is None:
            return None
        if not looks_like_planned_file_path(path, purpose=planned_file.purpose):
            continue
        for root in (target_root, original_root):
            if root != "." and path.startswith(f"{root}/"):
                path = path[len(root) + 1 :]
                break
        files.append(planned_file.model_copy(update={"path": path}))
    files = _normalize_python_package_layout(files, prompt=prompt, target_root=target_root, language=plan.language)
    files = _ensure_artifact_obligations(files, prompt=prompt, target_root=target_root)
    files = ensure_requested_report_artifact(files, prompt=prompt)
    api_obligations = _sanitize_api_obligations(
        plan.api_obligations,
        target_root=target_root,
        original_root=original_root,
    )
    if not files:
        return None
    commands: list[ValidationCommand] = []
    for command in plan.validation_commands:
        command = _normalize_validation_cwd(command, original_root=original_root, target_root=target_root)
        sanitized = _sanitize_validation_command(command, target_root=target_root)
        if sanitized is not None:
            commands.append(sanitized)
    return plan.model_copy(
        update={
            "target_root": target_root,
            "files": files,
            "validation_commands": commands,
            "api_obligations": api_obligations,
        }
    )


def _sanitize_api_obligations(
    obligations: Sequence[ApiObligation],
    *,
    target_root: str,
    original_root: str,
) -> list[ApiObligation]:
    sanitized: list[ApiObligation] = []
    seen: set[tuple[str, str]] = set()
    for obligation in obligations:
        path = _safe_relative_path(obligation.path)
        if path is None:
            continue
        for root in (target_root, original_root):
            if root != "." and path.startswith(f"{root}/"):
                path = path[len(root) + 1 :]
                break
        key = (path, obligation.symbol)
        if key in seen:
            continue
        seen.add(key)
        sanitized.append(obligation.model_copy(update={"path": path}))
    return sanitized


def _ensure_artifact_obligations(files: list[PlannedFile], *, prompt: str, target_root: str) -> list[PlannedFile]:
    obligations = set(_artifact_obligations(prompt))
    updated = list(files)
    if "README or user documentation" in obligations and not _has_documentation_file(updated):
        updated.append(
            PlannedFile(
                path="README.md",
                purpose="User documentation requested by the prompt.",
                stage="implementation",
                content=_readme_seed(target_root),
                required=True,
            )
        )
    return updated


def _normalize_python_package_layout(
    files: list[PlannedFile],
    *,
    prompt: str,
    target_root: str,
    language: str,
) -> list[PlannedFile]:
    if language.lower() != "python" or not _prompt_requests_python_package(prompt):
        return files
    package_name = _safe_python_package_name(target_root)
    if not package_name:
        return files
    if _has_package_layout(files, package_name):
        return _ensure_python_package_metadata(files, package_name=package_name, target_root=target_root)
    updated: list[PlannedFile] = []
    moved_any = False
    for planned_file in files:
        path = planned_file.path.replace("\\", "/")
        name = path.rsplit("/", 1)[-1]
        if "/" not in path and path.endswith(".py") and name not in {"setup.py"}:
            updated.append(planned_file.model_copy(update={"path": f"{package_name}/{path}"}))
            moved_any = True
            continue
        updated.append(planned_file)
    if moved_any and not any(file.path == f"{package_name}/__init__.py" for file in updated):
        updated.insert(
            0,
            PlannedFile(
                path=f"{package_name}/__init__.py",
                purpose="Python package marker for importable package layout.",
                stage="skeleton",
                content='"""Generated package."""\n',
                required=True,
            ),
        )
    return _ensure_python_package_metadata(updated, package_name=package_name, target_root=target_root)


def _prompt_requests_python_package(prompt: str) -> bool:
    lowered = prompt.lower()
    compact = re.sub(r"\s+", "", lowered)
    if any(marker in compact for marker in ("단일파일", "singlefile", "onefile")):
        return False
    return any(
        marker in compact
        for marker in (
            "패키지형",
            "패키지구조",
            "pythonpackage",
            "package-style",
            "packagedcli",
            "packagedproject",
        )
    )


def _safe_python_package_name(target_root: str) -> str:
    raw = target_root.rstrip("/").rsplit("/", 1)[-1]
    normalized = re.sub(r"\W+", "_", raw).strip("_").lower()
    if not normalized:
        return ""
    if normalized[0].isdigit():
        normalized = "_" + normalized
    return normalized


def _has_package_layout(files: Sequence[PlannedFile], package_name: str) -> bool:
    prefixes = (f"{package_name}/", f"src/{package_name}/")
    return any(file.path.replace("\\", "/").startswith(prefixes) for file in files)


def _ensure_python_package_metadata(
    files: list[PlannedFile],
    *,
    package_name: str,
    target_root: str,
) -> list[PlannedFile]:
    updated = list(files)
    paths = {file.path.replace("\\", "/") for file in updated}
    if f"{package_name}/__init__.py" not in paths and f"src/{package_name}/__init__.py" not in paths:
        updated.insert(
            0,
            PlannedFile(
                path=f"{package_name}/__init__.py",
                purpose="Python package marker for importable package layout.",
                stage="skeleton",
                content='"""Generated package."""\n',
                required=True,
            ),
        )
    if "pyproject.toml" not in paths:
        updated.insert(
            0,
            PlannedFile(
                path="pyproject.toml",
                purpose="Package metadata and pytest import path for generated Python package.",
                stage="skeleton",
                content=_pyproject_seed(package_name, target_root),
                required=True,
            ),
        )
    return updated


def _pyproject_seed(package_name: str, target_root: str) -> str:
    project_name = target_root.rstrip("/").rsplit("/", 1)[-1] or package_name
    return "\n".join(
        [
            "[project]",
            f'name = "{project_name}"',
            'version = "0.1.0"',
            'requires-python = ">=3.11"',
            "dependencies = []",
            "",
            "[tool.pytest.ini_options]",
            'pythonpath = ["."]',
            'testpaths = ["tests"]',
            "",
        ]
    )


def _has_documentation_file(files: Sequence[PlannedFile]) -> bool:
    for planned_file in files:
        name = planned_file.path.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if name in {"readme", "readme.md", "readme.rst"}:
            return True
        if name.endswith((".md", ".rst")) and "doc" in name:
            return True
    return False


def _readme_seed(target_root: str) -> str:
    project_name = target_root.rstrip("/").rsplit("/", 1)[-1] or "generated project"
    return "\n".join(
        [
            f"# {project_name}",
            "",
            "Generated project documentation.",
            "",
            "## Usage",
            "",
            "Run the validation command listed in the final report from the project root.",
        ]
    )


def _normalize_validation_cwd(command: ValidationCommand, *, original_root: str, target_root: str) -> ValidationCommand:
    cwd = command.cwd.strip() or "."
    if original_root != target_root and cwd == original_root:
        return command.model_copy(update={"cwd": target_root})
    return command


def _safe_root(value: str) -> str | None:
    normalized = value.strip().strip("/").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == ".":
        return "."
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if any(part in {".git", ".venv", "node_modules"} for part in normalized.split("/")):
        return None
    return normalized


def _safe_relative_path(value: str) -> str | None:
    normalized = value.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    if any(part in {".git", ".venv", "node_modules"} for part in normalized.split("/")):
        return None
    return normalized


def _sanitize_validation_command(command: ValidationCommand, *, target_root: str) -> ValidationCommand | None:
    raw_command = command.command.strip()
    if not raw_command or any(token in raw_command for token in (";", "&&", "||", "|", "`", "$(")):
        return None
    lowered = raw_command.lower()
    allowed_markers = (
        "pytest",
        "python -m pytest",
        "python -m py_compile",
        "unittest",
        "node --test",
        "npm test",
        "npm run test",
        "go test",
        "cargo test",
        "gradle test",
        "./gradlew test",
        "mvn test",
        "javac",
    )
    if not any(marker in lowered for marker in allowed_markers):
        return None
    cwd = command.cwd.strip() or "."
    if target_root != "." and cwd == ".":
        cwd = target_root
    if _safe_relative_path(cwd) is None and cwd != ".":
        return None
    return command.model_copy(update={"command": raw_command, "cwd": cwd})
