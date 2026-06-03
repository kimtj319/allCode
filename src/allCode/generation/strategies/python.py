"""Python skeleton-first generation strategy."""

from __future__ import annotations

from allCode.agent.task_plan import PlannedFile, ProjectPlan, TaskItem
from allCode.generation.strategy import GenerationRequest, infer_target_root, safe_name, validation_command


class PythonProjectStrategy:
    language = "python"
    aliases = ("python", "pytest", ".py", "파이썬")

    def create_plan(self, request: GenerationRequest) -> ProjectPlan:
        target = safe_name(request.target_root or infer_target_root(request.prompt))
        package = safe_name(target)
        if self._looks_like_standard_library_api(request.prompt):
            return self._api_plan(target, package)
        return ProjectPlan(
            target_root=target,
            language=self.language,
            constraints=["Use a dependency-light src layout.", "Validate with pytest."],
            files=[
                PlannedFile(path="pyproject.toml", purpose="package metadata", stage="skeleton", content=self._pyproject(target)),
                PlannedFile(path=f"src/{package}/__init__.py", purpose="package marker", stage="skeleton", content='"""Generated package."""\n'),
                PlannedFile(path=f"src/{package}/main.py", purpose="public application API", stage="skeleton", content=self._main_skeleton()),
                PlannedFile(path=f"src/{package}/main.py", purpose="public application API", stage="implementation", content=self._main_implementation()),
                PlannedFile(path="tests/test_main.py", purpose="pytest coverage for public API", stage="tests", content=self._tests(package)),
            ],
            validation_commands=[
                validation_command("python -m pytest", cwd=target, environment={"PYTHONPATH": "src"}),
            ],
            tasks=[
                TaskItem(description="Create package skeleton and project metadata.", step="skeleton"),
                TaskItem(description="Implement the public application API.", step="implementation"),
                TaskItem(description="Add validation tests.", step="tests"),
                TaskItem(description="Run pytest validation.", step="validation"),
            ],
        )

    def repair_files(self, plan: ProjectPlan, failure_log: str) -> dict[str, str]:
        package = safe_name(plan.target_root)
        return {f"src/{package}/main.py": self._main_implementation()}

    def _api_plan(self, target: str, package: str) -> ProjectPlan:
        return ProjectPlan(
            target_root=target,
            language=self.language,
            constraints=[
                "Use only the Python standard library.",
                "Separate routing, repository, auth, and server responsibilities.",
                "Validate with pytest.",
            ],
            files=[
                PlannedFile(path="pyproject.toml", purpose="package metadata", stage="skeleton", content=self._pyproject(target)),
                PlannedFile(path=f"src/{package}/__init__.py", purpose="package exports", stage="skeleton", content=self._api_init(package)),
                PlannedFile(path=f"src/{package}/routing.py", purpose="route table and handlers", stage="implementation", content=self._api_routing()),
                PlannedFile(path=f"src/{package}/repository.py", purpose="in-memory repository", stage="implementation", content=self._api_repository()),
                PlannedFile(path=f"src/{package}/auth.py", purpose="authentication stub", stage="implementation", content=self._api_auth()),
                PlannedFile(path=f"src/{package}/server.py", purpose="standard-library request dispatcher", stage="implementation", content=self._api_server(package)),
                PlannedFile(path="tests/test_api.py", purpose="pytest coverage for API scaffold", stage="tests", content=self._api_tests(package)),
            ],
            validation_commands=[
                validation_command("python -m pytest", cwd=target, environment={"PYTHONPATH": "src"}),
            ],
            tasks=[
                TaskItem(description="Create package metadata and public exports.", step="skeleton"),
                TaskItem(description="Implement routing, repository, auth, and server modules.", step="implementation"),
                TaskItem(description="Add validation tests for the API scaffold.", step="tests"),
                TaskItem(description="Run pytest validation.", step="validation"),
            ],
        )

    @staticmethod
    def _looks_like_standard_library_api(prompt: str) -> bool:
        lowered = prompt.lower()
        compact = prompt.replace(" ", "").lower()
        api_signal = any(marker in lowered for marker in ("api", "http", "server", "endpoint")) or any(
            marker in compact for marker in ("라우팅", "인증", "저장소")
        )
        component_signal = any(marker in lowered for marker in ("routing", "repository", "auth")) or any(
            marker in compact for marker in ("라우팅", "저장소", "인증")
        )
        return api_signal and component_signal

    def _pyproject(self, name: str) -> str:
        return "\n".join(
            [
                "[project]",
                f'name = "{name}"',
                'version = "0.1.0"',
                f'description = "Generated Python project {name}."',
                'requires-python = ">=3.11"',
                "",
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
            ]
        )

    def _main_skeleton(self) -> str:
        return "\n".join(
            [
                '"""Application entry points."""',
                "",
                "",
                "def greet(name: str = \"world\") -> str:",
                "    \"\"\"Return a greeting for a caller.\"\"\"",
                "    cleaned = name.strip() or \"world\"",
                "    return cleaned",
                "",
            ]
        )

    def _main_implementation(self) -> str:
        return "\n".join(
            [
                '"""Application entry points."""',
                "",
                "",
                "def greet(name: str = \"world\") -> str:",
                "    \"\"\"Return a stable greeting for a caller.\"\"\"",
                "    cleaned = name.strip() or \"world\"",
                "    return f\"Hello, {cleaned}!\"",
                "",
            ]
        )

    def _tests(self, package: str) -> str:
        return "\n".join(
            [
                f"from {package}.main import greet",
                "",
                "",
                "def test_greet_uses_name() -> None:",
                "    assert greet(\"User\") == \"Hello, User!\"",
                "",
                "",
                "def test_greet_defaults_to_world() -> None:",
                "    assert greet(\"   \") == \"Hello, world!\"",
                "",
            ]
        )

    def _api_init(self, package: str) -> str:
        return "\n".join(
            [
                '"""Standard-library API scaffold."""',
                "",
                "from .auth import authenticate",
                "from .repository import Repository",
                "from .routing import route_request, routes",
                "from .server import build_response",
                "",
                '__all__ = ["Repository", "authenticate", "build_response", "route_request", "routes"]',
                "",
            ]
        )

    def _api_routing(self) -> str:
        return "\n".join(
            [
                '"""Route table and request dispatch helpers."""',
                "",
                "from collections.abc import Callable",
                "",
                "",
                "def health_handler() -> dict[str, str]:",
                "    return {\"status\": \"ok\"}",
                "",
                "",
                "def users_handler() -> dict[str, list[str]]:",
                "    return {\"users\": []}",
                "",
                "",
                "routes: dict[str, Callable[[], dict]] = {",
                "    \"/health\": health_handler,",
                "    \"/users\": users_handler,",
                "}",
                "",
                "",
                "def route_request(path: str) -> dict:",
                "    handler = routes.get(path)",
                "    if handler is None:",
                "        return {\"error\": \"not_found\", \"path\": path}",
                "    return handler()",
                "",
            ]
        )

    def _api_repository(self) -> str:
        return "\n".join(
            [
                '"""Small in-memory repository used by the API scaffold."""',
                "",
                "from dataclasses import dataclass, field",
                "",
                "",
                "@dataclass",
                "class Repository:",
                "    users: dict[str, dict] = field(default_factory=dict)",
                "",
                "    def add_user(self, user_id: str, payload: dict) -> dict:",
                "        stored = dict(payload)",
                "        stored[\"id\"] = user_id",
                "        self.users[user_id] = stored",
                "        return stored",
                "",
                "    def get_user(self, user_id: str) -> dict | None:",
                "        return self.users.get(user_id)",
                "",
                "    def list_users(self) -> list[dict]:",
                "        return list(self.users.values())",
                "",
            ]
        )

    def _api_auth(self) -> str:
        return "\n".join(
            [
                '"""Authentication stub for local development and tests."""',
                "",
                "",
                "def authenticate(token: str | None) -> bool:",
                "    \"\"\"Accept a deterministic development token and reject empty tokens.\"\"\"",
                "    return bool(token and token == \"dev-token\")",
                "",
            ]
        )

    def _api_server(self, package: str) -> str:
        return "\n".join(
            [
                '"""Standard-library response dispatcher for the scaffold."""',
                "",
                "from __future__ import annotations",
                "",
                "import json",
                "",
                "from .auth import authenticate",
                "from .routing import route_request",
                "",
                "",
                "def build_response(path: str, *, token: str | None = None) -> tuple[int, str]:",
                "    if not authenticate(token):",
                "        return 401, json.dumps({\"error\": \"unauthorized\"})",
                "    payload = route_request(path)",
                "    status = 404 if payload.get(\"error\") == \"not_found\" else 200",
                "    return status, json.dumps(payload, sort_keys=True)",
                "",
                "",
                "def run() -> str:",
                "    return \"standard-library api scaffold ready\"",
                "",
            ]
        )

    def _api_tests(self, package: str) -> str:
        return "\n".join(
            [
                f"from {package}.auth import authenticate",
                f"from {package}.repository import Repository",
                f"from {package}.routing import route_request",
                f"from {package}.server import build_response, run",
                "",
                "",
                "def test_auth_stub_accepts_dev_token() -> None:",
                "    assert authenticate(\"dev-token\") is True",
                "    assert authenticate(None) is False",
                "",
                "",
                "def test_repository_round_trip() -> None:",
                "    repository = Repository()",
                "    user = repository.add_user(\"u1\", {\"name\": \"Ada\"})",
                "    assert user == {\"id\": \"u1\", \"name\": \"Ada\"}",
                "    assert repository.get_user(\"u1\") == user",
                "    assert repository.list_users() == [user]",
                "",
                "",
                "def test_route_request_handles_known_and_unknown_paths() -> None:",
                "    assert route_request(\"/health\") == {\"status\": \"ok\"}",
                "    assert route_request(\"/missing\") == {\"error\": \"not_found\", \"path\": \"/missing\"}",
                "",
                "",
                "def test_build_response_uses_auth_and_routing() -> None:",
                "    assert build_response(\"/health\", token=None)[0] == 401",
                "    status, body = build_response(\"/health\", token=\"dev-token\")",
                "    assert status == 200",
                "    assert 'ok' in body",
                "    assert run().endswith(\"ready\")",
                "",
            ]
        )
