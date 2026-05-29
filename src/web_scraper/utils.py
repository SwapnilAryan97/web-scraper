from __future__ import annotations

import os
import random
import re
import time
from pathlib import Path
from typing import Any, Optional

_HEADER_NORMALIZER = re.compile(r"[^A-Za-z0-9_]+")
_FILENAME_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")


def normalize_header(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("-", "_").replace(" ", "_")
    text = _HEADER_NORMALIZER.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text.lower()


def sanitize_filename_component(value: Any, *, lowercase: bool = False) -> str:
    text = str(value).strip().replace(" ", "_")
    text = _FILENAME_SANITIZER.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text.lower() if lowercase else text


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def maybe_sleep(min_seconds: float, max_seconds: float) -> None:
    lower = max(0.0, min_seconds)
    upper = max(lower, max_seconds)
    if upper == 0:
        return
    time.sleep(random.uniform(lower, upper))


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_or_default(
    key: str,
    env_file_values: dict[str, str],
    default: Optional[str] = None,
) -> Optional[str]:
    if key in os.environ:
        return os.environ[key]
    if key in env_file_values:
        return env_file_values[key]
    return default


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
            continue
        merged[key] = value
    return merged
