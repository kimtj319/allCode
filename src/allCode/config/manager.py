"""Configuration loading and precedence handling."""

from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml
from pydantic import ValidationError

from allCode.config.defaults import (
    DEFAULT_CONFIG_PATH,
    ENV_API_KEY,
    ENV_API_KEY_ENV,
    ENV_APPROVAL_MODE,
    ENV_BASE_URL,
    ENV_CONFIG_PATH,
    ENV_MODEL,
    ENV_LSP_ENABLED,
    ENV_LSP_TIMEOUT_MS,
    ENV_SOURCE_INTELLIGENCE,
    ENV_WEB_SEARCH_BACKEND,
    ENV_WEB_SEARCH_API_KEY_ENV,
    ENV_WEB_SEARCH_LANGUAGE,
    ENV_WEB_SEARCH_TIMEOUT,
    ENV_WEB_SEARCH_URL,
    ENV_WORKSPACE,
    PROJECT_CONFIG_RELATIVE_PATH,
)
from allCode.config.env_file import load_project_env
from allCode.config.schema import AppConfig, ConfigFileSource, ConfigSourceReport, DotenvSource


class ConfigError(RuntimeError):
    """Raised when configuration cannot be loaded or validated."""


@dataclass(frozen=True)
class ConfigOverrides:
    config_path: str | None = None
    workspace: str | None = None
    model: str | None = None
    base_url: str | None = None
    approval: str | None = None

    def to_nested_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if self.workspace is not None:
            data.setdefault("workspace", {})["root"] = self.workspace
        if self.model is not None:
            data.setdefault("model", {})["model_name"] = self.model
        if self.base_url is not None:
            data.setdefault("model", {})["base_url"] = self.base_url
        if self.approval is not None:
            data.setdefault("approval", {})["mode"] = self.approval
        return data


@dataclass(frozen=True)
class ConfigLoadResult:
    config: AppConfig
    report: ConfigSourceReport


class ConfigManager:
    """Single entrypoint for allCode configuration."""

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        default_config_path: Path | None = None,
    ) -> None:
        self._environ = dict(environ) if environ is not None else None
        self._default_config_path = default_config_path or DEFAULT_CONFIG_PATH

    @property
    def environ(self) -> Mapping[str, str]:
        if self._environ is not None:
            return self._environ
        import os

        return os.environ

    def load(self, overrides: ConfigOverrides | None = None) -> AppConfig:
        return self.load_with_report(overrides).config

    def load_with_report(self, overrides: ConfigOverrides | None = None) -> ConfigLoadResult:
        cli = overrides or ConfigOverrides()
        merged = AppConfig().model_dump(mode="python")
        config_sources: list[ConfigFileSource] = []
        dotenv_sources: list[DotenvSource] = []

        user_config_path = self._select_user_config_path(cli.config_path)
        user_data = self._load_yaml_if_present(user_config_path)
        config_sources.append(ConfigFileSource(path=str(user_config_path), loaded=bool(user_data), source_type="user"))
        self._deep_merge(merged, user_data)

        project_root = self._project_root_for_config(merged, cli)
        project_config_path = project_root / PROJECT_CONFIG_RELATIVE_PATH
        project_data = self._load_yaml_if_present(project_config_path)
        config_sources.append(ConfigFileSource(path=str(project_config_path), loaded=bool(project_data), source_type="project"))
        self._deep_merge(merged, project_data)
        launch_config_used = False
        if not project_data and self._launch_config_fallback_allowed(cli):
            launch_config_path = Path.cwd() / PROJECT_CONFIG_RELATIVE_PATH
            if not _same_path(launch_config_path, project_config_path):
                launch_data = self._load_yaml_if_present(launch_config_path)
                config_sources.append(
                    ConfigFileSource(path=str(launch_config_path), loaded=bool(launch_data), source_type="launch")
                )
                if launch_data:
                    self._deep_merge(merged, launch_data)
                    launch_config_used = True
        dotenv_sources.extend(self._load_project_env(project_root))

        env_overrides = self._env_overrides()
        self._deep_merge(merged, env_overrides)
        cli_overrides = cli.to_nested_dict()
        self._deep_merge(merged, cli_overrides)

        try:
            config = AppConfig.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError(f"Invalid allCode configuration: {exc}") from exc
        return ConfigLoadResult(
            config=config,
            report=self._build_report(
                config,
                config_sources=config_sources,
                dotenv_sources=dotenv_sources,
                env_overrides=sorted(env_overrides.keys()),
                cli_overrides=_nested_override_keys(cli_overrides),
                launch_config_used=launch_config_used,
            ),
        )

    def _select_user_config_path(self, cli_config_path: str | None) -> Path:
        if cli_config_path:
            return Path(cli_config_path).expanduser()
        env_path = self.environ.get(ENV_CONFIG_PATH)
        if env_path:
            return Path(env_path).expanduser()
        return self._default_config_path

    def _project_root_for_config(
        self,
        merged: Mapping[str, Any],
        cli: ConfigOverrides,
    ) -> Path:
        if cli.workspace:
            return Path(cli.workspace).expanduser().resolve()
        env_workspace = self.environ.get(ENV_WORKSPACE)
        if env_workspace:
            return Path(env_workspace).expanduser().resolve()
        workspace = merged.get("workspace", {})
        root = workspace.get("root", ".") if isinstance(workspace, Mapping) else "."
        return Path(str(root)).expanduser().resolve()

    def _load_yaml_if_present(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                loaded = yaml.safe_load(handle) or {}
        except OSError as exc:
            raise ConfigError(f"Could not read config file {path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise ConfigError(f"Could not parse config file {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"Config file {path} must contain a mapping")
        return loaded

    def _load_project_env(self, project_root: Path) -> list[DotenvSource]:
        environ = self._mutable_environ()
        sources: list[DotenvSource] = []
        project_env = project_root / ".env"
        loaded = load_project_env(project_env, environ, override=False)
        if project_env.exists():
            sources.append(DotenvSource(path=str(project_env), loaded_keys=sorted(loaded.keys())))
        if self._environ is not None:
            return sources
        cwd_env = Path.cwd() / ".env"
        if _same_path(project_env, cwd_env):
            return sources
        loaded = load_project_env(cwd_env, environ, override=False)
        if cwd_env.exists():
            sources.append(DotenvSource(path=str(cwd_env), loaded_keys=sorted(loaded.keys())))
        return sources

    def _mutable_environ(self) -> MutableMapping[str, str]:
        if self._environ is not None:
            return self._environ
        import os

        return os.environ

    def _env_overrides(self) -> dict[str, Any]:
        env = self.environ
        data: dict[str, Any] = {}
        if env.get(ENV_MODEL):
            data.setdefault("model", {})["model_name"] = env[ENV_MODEL]
        if env.get(ENV_BASE_URL):
            data.setdefault("model", {})["base_url"] = env[ENV_BASE_URL]
        if env.get(ENV_API_KEY_ENV):
            data.setdefault("model", {})["api_key_env"] = env[ENV_API_KEY_ENV]
        elif env.get(ENV_API_KEY):
            data.setdefault("model", {})["api_key_env"] = ENV_API_KEY
        if env.get(ENV_WORKSPACE):
            data.setdefault("workspace", {})["root"] = env[ENV_WORKSPACE]
        if env.get(ENV_APPROVAL_MODE):
            data.setdefault("approval", {})["mode"] = env[ENV_APPROVAL_MODE]
        if env.get(ENV_WEB_SEARCH_URL):
            data.setdefault("web", {})["search_url"] = env[ENV_WEB_SEARCH_URL]
        if env.get(ENV_WEB_SEARCH_BACKEND):
            data.setdefault("web", {})["backend"] = env[ENV_WEB_SEARCH_BACKEND]
        if env.get(ENV_WEB_SEARCH_API_KEY_ENV):
            data.setdefault("web", {})["api_key_env"] = env[ENV_WEB_SEARCH_API_KEY_ENV]
        if env.get(ENV_WEB_SEARCH_TIMEOUT):
            data.setdefault("web", {})["timeout_seconds"] = env[ENV_WEB_SEARCH_TIMEOUT]
        if env.get(ENV_WEB_SEARCH_LANGUAGE):
            data.setdefault("web", {})["default_language"] = env[ENV_WEB_SEARCH_LANGUAGE]
        if env.get(ENV_SOURCE_INTELLIGENCE):
            data.setdefault("source_intelligence", {})["mode"] = env[ENV_SOURCE_INTELLIGENCE]
        if env.get(ENV_LSP_ENABLED):
            data.setdefault("source_intelligence", {})["lsp_enabled"] = _truthy(env[ENV_LSP_ENABLED])
        if env.get(ENV_LSP_TIMEOUT_MS):
            data.setdefault("source_intelligence", {})["lsp_timeout_ms"] = env[ENV_LSP_TIMEOUT_MS]
        return data

    def _launch_config_fallback_allowed(self, cli: ConfigOverrides) -> bool:
        return self._environ is None and not cli.config_path and not self.environ.get(ENV_CONFIG_PATH)

    def _build_report(
        self,
        config: AppConfig,
        *,
        config_sources: list[ConfigFileSource],
        dotenv_sources: list[DotenvSource],
        env_overrides: list[str],
        cli_overrides: list[str],
        launch_config_used: bool,
    ) -> ConfigSourceReport:
        api_key_env = config.model.api_key_env
        return ConfigSourceReport(
            config_files=config_sources,
            dotenv_files=dotenv_sources,
            env_overrides=env_overrides,
            cli_overrides=cli_overrides,
            workspace_root=config.workspace.root,
            model_name=config.model.model_name,
            base_url=_display_url(config.model.base_url),
            api_key_env=api_key_env,
            api_key_present=bool(self.environ.get(api_key_env)),
            approval_mode=config.approval.mode,
            web_backend=config.web.backend,
            web_search_host=_display_url(config.web.search_url),
            launch_config_fallback_used=launch_config_used,
        )

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = deepcopy(value)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return left.expanduser().absolute() == right.expanduser().absolute()


def _nested_override_keys(data: Mapping[str, Any], *, prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            keys.extend(_nested_override_keys(value, prefix=name))
        else:
            keys.append(name)
    return sorted(keys)


def _display_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme:
        return value
    host = parsed.netloc
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{host}{path}"
