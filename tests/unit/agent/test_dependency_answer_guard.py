from __future__ import annotations

from types import SimpleNamespace

from allCode.agent.dependency_answer_guard import (
    dependency_answer_retry_messages,
    dependency_answer_retry_used,
    dependency_answer_sanitized_fallback,
    dependency_answer_violation,
)
from allCode.agent.router import RoutingDecision
from allCode.core.models import Message


def _route(*, flags: set[str] | None = None) -> RoutingDecision:
    return RoutingDecision(
        kind="answer",
        confidence=0.9,
        reason="direct answer",
        tool_capabilities=set(),
        flags=flags or {"stdlib_only_requested", "answer_artifact", "code_artifact"},
    )


def test_dependency_guard_detects_third_party_test_tool_for_stdlib_request() -> None:
    violation = dependency_answer_violation(
        answer="테스트는 pytest로 작성하고 requirements.txt에 pytest를 추가하세요.",
        routing=_route(),
    )

    assert violation is not None
    assert violation.reason in {"dependency_constraint_third_party_package", "dependency_constraint_install_suggestion"}


def test_dependency_guard_ignores_negated_alternative_mentions() -> None:
    violation = dependency_answer_violation(
        answer="pytest는 사용하지 말고 표준 라이브러리 unittest와 tempfile을 사용하세요.",
        routing=_route(),
    )

    assert violation is None


def test_dependency_guard_detects_positive_term_after_unrelated_negation() -> None:
    violation = dependency_answer_violation(
        answer="requests는 사용하지 말고 테스트는 pytest로 작성하세요.",
        routing=_route(),
    )

    assert violation is not None
    assert violation.reason == "dependency_constraint_third_party_package"


def test_dependency_guard_detects_poetry_and_uv_add_commands() -> None:
    poetry_violation = dependency_answer_violation(answer="poetry add pytest", routing=_route())
    uv_violation = dependency_answer_violation(answer="uv add requests", routing=_route())

    assert poetry_violation is not None
    assert uv_violation is not None


def test_dependency_guard_detects_unknown_third_party_imports_from_code_blocks() -> None:
    answer = "\n".join(
        [
            "```python",
            "from bs4 import BeautifulSoup",
            "import paramiko",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is not None
    assert violation.reason == "dependency_constraint_non_stdlib_import"
    assert "bs4" in violation.excerpt


def test_dependency_guard_detects_dynamic_third_party_imports() -> None:
    answer = "\n".join(
        [
            "```python",
            "import importlib",
            "client = importlib.import_module('redis')",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is not None
    assert violation.reason == "dependency_constraint_non_stdlib_import"
    assert "redis" in violation.excerpt


def test_dependency_guard_allows_stdlib_and_local_package_imports() -> None:
    answer = "\n".join(
        [
            "`src/taskhub/cli.py`",
            "```python",
            "import argparse",
            "from pathlib import Path",
            "from taskhub.store import JsonStore",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is None


def test_dependency_guard_allows_explicit_local_module_file_imports() -> None:
    answer = "\n".join(
        [
            "`config.py`",
            "```python",
            "from config import Settings",
            "import argparse",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is None


def test_dependency_guard_does_not_allow_known_third_party_via_local_file_comment() -> None:
    answer = "\n".join(
        [
            "```python",
            "# file: requests.py",
            "import requests",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is not None
    assert violation.reason == "dependency_constraint_third_party_package"


def test_dependency_guard_does_not_allow_unknown_import_from_url_file_reference() -> None:
    answer = "\n".join(
        [
            "참고 URL: https://example.com/libs/my_helper.py",
            "```python",
            "import my_helper",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is not None
    assert violation.reason == "dependency_constraint_non_stdlib_import"


def test_dependency_guard_does_not_treat_pyc_or_backup_as_local_module() -> None:
    answer = "\n".join(
        [
            "`config.pyc`",
            "```python",
            "import config",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is not None
    assert violation.reason == "dependency_constraint_non_stdlib_import"


def test_dependency_guard_ignores_relative_imports_and_allows_dynamic_stdlib_imports() -> None:
    answer = "\n".join(
        [
            "```python",
            "from .helper import run",
            "import importlib",
            "module = importlib.import_module('os')",
            "other = __import__('sys')",
            "```",
        ]
    )

    violation = dependency_answer_violation(answer=answer, routing=_route())

    assert violation is None


def test_dependency_guard_detects_non_python_install_commands() -> None:
    npm_violation = dependency_answer_violation(answer="npm install cheerio", routing=_route())
    cargo_violation = dependency_answer_violation(answer="cargo add anyhow", routing=_route())

    assert npm_violation is not None
    assert npm_violation.reason == "dependency_constraint_install_suggestion"
    assert cargo_violation is not None


def test_dependency_guard_ignores_negated_install_commands() -> None:
    violation = dependency_answer_violation(
        answer="npm install은 실행하지 말고 표준 라이브러리 기반 예시만 작성하세요.",
        routing=_route(),
    )

    assert violation is None


def test_dependency_guard_is_inactive_without_stdlib_flag() -> None:
    violation = dependency_answer_violation(
        answer="pytest와 requests를 사용하면 됩니다.",
        routing=_route(flags={"answer_artifact", "code_artifact"}),
    )

    assert violation is None


def test_dependency_retry_message_and_used_count() -> None:
    violation = dependency_answer_violation(answer="pip install pytest", routing=_route())
    assert violation is not None

    messages = dependency_answer_retry_messages(
        current_messages=[Message(role="user", content="표준 라이브러리만 사용해줘")],
        previous_answer="pip install pytest",
        violation=violation,
        language="ko",
    )

    assert messages[-1].role == "user"
    assert "표준 라이브러리" in messages[-1].content
    assert "pytest" in messages[-1].content

    recovery = SimpleNamespace(states=[SimpleNamespace(reason="dependency_constraint_violation")])
    assert dependency_answer_retry_used(recovery)


def test_dependency_sanitized_fallback_preserves_previous_useful_answer() -> None:
    previous = "\n".join(
        [
            "# taskhub 설계",
            "",
            "- `taskhub/cli.py`: argparse로 add/list/done/export-json 명령을 처리합니다.",
            "- `taskhub/store.py`: json과 pathlib로 작업 목록을 저장합니다.",
            "- 패키징: `pyproject.toml` scripts 설정 후 `pip install .`로 실행합니다.",
            "",
            "```python",
            "import argparse",
            "import unittest",
            "```",
        ]
    )
    messages = [Message(role="assistant", content=previous)]

    answer = dependency_answer_sanitized_fallback(
        messages=messages,
        current_answer='{"마지막_위반_근거":"pip install pytest"}',
        routing=_route(),
        language="ko",
    )

    assert "argparse" in answer
    assert "unittest" in answer
    assert "pip install" not in answer
    assert "pyproject.toml" not in answer
    assert "외부 의존성 제약" in answer
