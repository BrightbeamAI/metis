"""Load and render local-model prompt templates and whisper templates (YAML)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..resources import prompts_dir


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return yaml.safe_load(path.read_text()) or {}


def load_model_prompt(name: str) -> dict[str, Any]:
    """Load prompts/model/<name>.yaml."""
    return _load_yaml(prompts_dir() / "model" / f"{name}.yaml")


def load_whisper_template(name: str) -> dict[str, Any]:
    """Load prompts/whispers/<name>.yaml."""
    return _load_yaml(prompts_dir() / "whispers" / f"{name}.yaml")


def list_whisper_templates() -> list[str]:
    d = prompts_dir() / "whispers"
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def render(template: str, **variables: Any) -> str:
    """Render a template string with {placeholder} substitution (missing keys are kept)."""
    class _Safe(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_Safe(variables))
