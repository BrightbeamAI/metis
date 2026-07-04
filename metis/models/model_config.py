"""Local model configuration.

By default Metis uses a local Ollama runtime and the Gemma model family. It must NOT
call cloud LLM APIs. Configuration is set with ``metis config set model.* ...``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "gemma4"
DEFAULT_URL = "http://localhost:11434"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = DEFAULT_PROVIDER
    name: str = DEFAULT_MODEL
    url: str = DEFAULT_URL
    enabled: bool = True
    timeout_s: float = 20.0

    def assert_local(self) -> None:
        """Guard against accidentally configuring a cloud endpoint."""
        if self.provider != "ollama":
            raise ValueError(
                f"Metis defaults to a local Ollama runtime; provider={self.provider!r} "
                "is not supported by the reference toolkit."
            )


def project_home(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("METIS_HOME", Path.cwd() / ".metis"))


def config_path(home: str | None = None) -> Path:
    return project_home(home) / "config.json"


def load_model_config(home: str | None = None) -> ModelConfig:
    path = config_path(home)
    if path.exists():
        data = json.loads(path.read_text())
        return ModelConfig(**data.get("model", {}))
    return ModelConfig()


def save_model_config(cfg: ModelConfig, home: str | None = None) -> Path:
    path = config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        existing = json.loads(path.read_text())
    existing["model"] = cfg.model_dump()
    path.write_text(json.dumps(existing, indent=2))
    return path


def set_model_key(key: str, value: str, home: str | None = None) -> ModelConfig:
    """Implements ``config set model.<key> <value>``."""
    cfg = load_model_config(home)
    field = key.split(".", 1)[1] if key.startswith("model.") else key
    if field not in {"provider", "name", "url", "enabled", "timeout_s"}:
        raise KeyError(f"Unknown model config key: {key}")
    if field == "enabled":
        value = value.lower() in ("1", "true", "yes", "on")  # type: ignore[assignment]
    elif field == "timeout_s":
        value = float(value)  # type: ignore[assignment]
    cfg = cfg.model_copy(update={field: value})
    save_model_config(cfg, home)
    return cfg
