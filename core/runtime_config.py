from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


RUNTIME_CONFIG_FILENAME = "plugin_runtime_config.json"


def load_runtime_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(config, dict):
        return {}

    return config


def resolve_helper_python_command(config_path: Path) -> list[str]:
    runtime_config = load_runtime_config(config_path)
    configured_helper = str(runtime_config.get("helper_python", "")).strip()

    configured_command = _resolve_command(configured_helper)
    if configured_command:
        return configured_command

    for fallback_name in _iter_fallback_names():
        fallback_command = _resolve_command(fallback_name)
        if fallback_command:
            return fallback_command

    return []


def _iter_fallback_names() -> tuple[str, ...]:
    if sys.platform == "win32":
        return ("py", "python", "python3")
    return ("python3", "python")


def _resolve_command(command_name: str) -> list[str]:
    if not command_name:
        return []

    command_path = Path(command_name)
    if command_path.exists():
        return _build_command(command_path)

    resolved_path = shutil.which(command_name)
    if resolved_path:
        return _build_command(Path(resolved_path))

    return []


def _build_command(command_path: Path) -> list[str]:
    command = [str(command_path)]
    if sys.platform == "win32" and command_path.stem.lower() == "py":
        command.append("-3")
    return command
