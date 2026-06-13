"""Generated documentation checks against observable CLI parser structure."""

from __future__ import annotations

import ast
import re
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from allCode.agent.task_plan import ProjectPlan
from allCode.core.path_patterns import looks_like_test_path as _looks_test_path


@dataclass
class ArgparseCliSpec:
    commands: set[str] = field(default_factory=set)
    options: set[str] = field(default_factory=set)
    invocation_names: set[str] = field(default_factory=set)
    source_paths: set[str] = field(default_factory=set)


@dataclass
class DocumentedCliUsage:
    commands: set[str] = field(default_factory=set)
    options: set[str] = field(default_factory=set)


def cli_documentation_reference_errors(target_root: Path, plan: ProjectPlan) -> list[str]:
    spec = _argparse_cli_spec(target_root, plan)
    if not spec.commands and not spec.options:
        return []
    invocation_names = _known_invocation_names(target_root, plan) | spec.invocation_names
    package_names = _package_names(plan)
    parser_targets = ", ".join(sorted(spec.source_paths)[:3])
    errors: list[str] = []
    for relative_path, content in _document_files(target_root, plan):
        usage = _documented_cli_usage(
            content,
            invocation_names=invocation_names,
            package_names=package_names,
            known_commands=spec.commands,
        )
        missing_commands = sorted(command for command in usage.commands if command not in spec.commands)
        missing_options = sorted(option for option in usage.options if option not in spec.options)
        target_label = _target_label(relative_path, parser_targets)
        if missing_commands:
            errors.append(
                f"documentation references unsupported CLI command in {target_label}: "
                + ", ".join(missing_commands[:6])
            )
        if missing_options:
            errors.append(
                f"documentation references unsupported CLI option in {target_label}: "
                + ", ".join(missing_options[:6])
            )
    return errors


def _argparse_cli_spec(target_root: Path, plan: ProjectPlan) -> ArgparseCliSpec:
    spec = ArgparseCliSpec()
    for relative_path in plan.required_paths():
        normalized = relative_path.replace("\\", "/")
        if not normalized.endswith(".py") or _looks_test_path(normalized):
            continue
        path = target_root / normalized
        if not path.exists() or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        file_spec = _argparse_cli_spec_from_tree(tree)
        if file_spec.commands or file_spec.options:
            spec.commands.update(file_spec.commands)
            spec.options.update(file_spec.options)
            spec.invocation_names.update(file_spec.invocation_names)
            spec.source_paths.add(normalized)
    return spec


def _argparse_cli_spec_from_tree(tree: ast.AST) -> ArgparseCliSpec:
    spec = ArgparseCliSpec()
    subparser_vars: set[str] = set()
    parser_vars: set[str] = set()
    command_parser_vars: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            assigned = _assigned_names(node.targets)
            call = node.value
            if _is_argument_parser_call(call):
                parser_vars.update(assigned)
                prog = _argument_parser_prog(call)
                if prog:
                    spec.invocation_names.add(prog)
            elif _is_method_call(call, "add_subparsers"):
                if _call_owner_name(call) in parser_vars or not parser_vars:
                    subparser_vars.update(assigned)
            elif _is_method_call(call, "add_parser") and _call_owner_name(call) in subparser_vars:
                command = _first_string_arg(call)
                if command:
                    spec.commands.add(command)
                    for name in assigned:
                        command_parser_vars[name] = command
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if _is_method_call(call, "add_parser") and _call_owner_name(call) in subparser_vars:
                command = _first_string_arg(call)
                if command:
                    spec.commands.add(command)
            elif _is_method_call(call, "add_argument"):
                owner = _call_owner_name(call)
                if owner in parser_vars or owner in command_parser_vars or not parser_vars:
                    spec.options.update(_option_args(call))
    return spec


def _documented_cli_usage(
    content: str,
    *,
    invocation_names: set[str],
    package_names: set[str],
    known_commands: set[str],
) -> DocumentedCliUsage:
    usage = DocumentedCliUsage()
    for snippet in _command_snippets(content):
        tokens = _shell_tokens(snippet)
        if not tokens:
            continue
        args = _usage_args(tokens, invocation_names=invocation_names, package_names=package_names)
        if args is None:
            continue
        _collect_usage_tokens(args, known_commands=known_commands, usage=usage)
    return usage


def _command_snippets(content: str) -> list[str]:
    snippets: list[str] = []
    in_fence = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            snippets.append(_strip_shell_prompt(stripped))
    snippets.extend(match.group("code").strip() for match in re.finditer(r"`(?P<code>[^`\n]+)`", content))
    return [snippet for snippet in snippets if snippet]


def _usage_args(
    tokens: list[str],
    *,
    invocation_names: set[str],
    package_names: set[str],
) -> list[str] | None:
    tokens = _drop_env_assignments(tokens)
    if len(tokens) >= 3 and tokens[0] in {"python", "python3"} and tokens[1] == "-m":
        module = tokens[2]
        if module.split(".", 1)[0] in package_names:
            return tokens[3:]
        return None
    if len(tokens) >= 3 and tokens[0] in {"uv", "poetry", "pipenv"} and tokens[1] == "run":
        return _usage_args(tokens[2:], invocation_names=invocation_names, package_names=package_names)
    if tokens and tokens[0] in invocation_names:
        return tokens[1:]
    return None


def _collect_usage_tokens(args: list[str], *, known_commands: set[str], usage: DocumentedCliUsage) -> None:
    index = 0
    command_seen = False
    while index < len(args):
        token = args[index]
        if token.startswith("-"):
            option = token.split("=", 1)[0]
            if _is_placeholder_token(option):
                index += 1
                continue
            usage.options.add(option)
            if "=" not in token and index + 1 < len(args) and not args[index + 1].startswith("-"):
                if args[index + 1] not in known_commands:
                    index += 1
            index += 1
            continue
        if not command_seen:
            if not _is_placeholder_token(token):
                usage.commands.add(token)
                command_seen = True
        index += 1


def _known_invocation_names(target_root: Path, plan: ProjectPlan) -> set[str]:
    names = set(_package_names(plan))
    names.add(Path(plan.target_root).name.replace("_", "-"))
    pyproject = target_root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
            data = {}
        project = data.get("project") if isinstance(data, dict) else {}
        if isinstance(project, dict):
            for key in ("scripts", "gui-scripts"):
                scripts = project.get(key)
                if isinstance(scripts, dict):
                    names.update(str(name) for name in scripts)
    return {name for name in names if name}


def _document_files(target_root: Path, plan: ProjectPlan) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    for relative_path in plan.required_paths():
        if Path(relative_path).suffix.lower() not in {".md", ".rst", ".txt"}:
            continue
        path = target_root / relative_path
        try:
            files.append((relative_path, path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return files


def _package_names(plan: ProjectPlan) -> set[str]:
    names: set[str] = set()
    for relative_path in plan.required_paths():
        parts = relative_path.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[0] == "src" and parts[-1].endswith(".py"):
            names.add(parts[1])
        elif len(parts) >= 2 and parts[-1].endswith(".py") and parts[0] not in {"tests", "test"}:
            names.add(parts[0])
    return names


def _assigned_names(targets: list[ast.expr]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.update(name.id for name in target.elts if isinstance(name, ast.Name))
    return names


def _is_argument_parser_call(node: object) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "ArgumentParser"
        and isinstance(func.value, ast.Name)
        and func.value.id == "argparse"
    ) or (isinstance(func, ast.Name) and func.id == "ArgumentParser")


def _is_method_call(node: object, method: str) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == method


def _call_owner_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return node.func.value.id
    return ""


def _first_string_arg(node: ast.Call) -> str:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return ""


def _option_args(node: ast.Call) -> set[str]:
    options: set[str] = set()
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"):
            options.add(arg.value)
    return options


def _argument_parser_prog(node: ast.Call) -> str:
    for keyword in node.keywords:
        if keyword.arg == "prog" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return ""


def _shell_tokens(snippet: str) -> list[str]:
    command = snippet.split("#", 1)[0].strip()
    for separator in ("&&", ";", "|"):
        command = command.split(separator, 1)[0].strip()
    if not command:
        return []
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _strip_shell_prompt(line: str) -> str:
    return re.sub(r"^(?:\$|>|%)\s+", "", line.strip())


def _drop_env_assignments(tokens: list[str]) -> list[str]:
    index = 0
    while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
        index += 1
    return tokens[index:]


def _is_placeholder_token(token: str) -> bool:
    value = str(token or "").strip()
    if not value:
        return True
    stripped = value.strip("[]<>")
    if not stripped:
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    if value.startswith("[") and value.endswith("]"):
        return True
    return stripped.isupper() and any(char.isalpha() for char in stripped)


def _target_label(document_path: str, parser_targets: str) -> str:
    if parser_targets:
        return f"{document_path}, {parser_targets}"
    return document_path

