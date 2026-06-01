"""Configuration loading and precedence handling."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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
    ENV_WEB_SEARCH_API_KEY_ENV,
    ENV_WEB_SEARCH_TIMEOUT,
    ENV_WEB_SEARCH_URL,
    ENV_WORKSPACE,
    PROJECT_CONFIG_RELATIVE_PATH,
)
from allCode.config.schema import AppConfig


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
        cli = overrides or ConfigOverrides()
        merged = AppConfig().model_dump(mode="python")

        user_config_path = self._select_user_config_path(cli.config_path)
        self._deep_merge(merged, self._load_yaml_if_present(user_config_path))

        project_root = self._project_root_for_config(merged, cli)
        project_config_path = project_root / PROJECT_CONFIG_RELATIVE_PATH
        self._deep_merge(merged, self._load_yaml_if_present(project_config_path))

        self._deep_merge(merged, self._env_overrides())
        self._deep_merge(merged, cli.to_nested_dict())

        try:
            return AppConfig.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError(f"Invalid allCode configuration: {exc}") from exc

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
        if env.get(ENV_WEB_SEARCH_API_KEY_ENV):
            data.setdefault("web", {})["api_key_env"] = env[ENV_WEB_SEARCH_API_KEY_ENV]
        if env.get(ENV_WEB_SEARCH_TIMEOUT):
            data.setdefault("web", {})["timeout_seconds"] = env[ENV_WEB_SEARCH_TIMEOUT]
        return data

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], source: Mapping[str, Any]) -> None:
        for key, value in source.items():
            if isinstance(value, Mapping) and isinstance(target.get(key), dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = deepcopy(value)
