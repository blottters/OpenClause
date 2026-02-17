from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import toml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
CONFIG_FILE = CONFIG_DIR / "config.toml"
EXAMPLE_FILE = CONFIG_DIR / "config.example.toml"


def ensure_config_exists() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists() and EXAMPLE_FILE.exists():
        shutil.copy2(EXAMPLE_FILE, CONFIG_FILE)


def load_defaults() -> dict[str, Any]:
    if not EXAMPLE_FILE.exists():
        return {}
    with EXAMPLE_FILE.open("r", encoding="utf-8") as handle:
        return toml.loads(handle.read())


def load_config() -> dict[str, Any]:
    ensure_config_exists()
    target = CONFIG_FILE if CONFIG_FILE.exists() else EXAMPLE_FILE
    defaults = load_defaults()
    if not target.exists():
        return {"data": defaults, "error": "No config file found.", "has_error": True}

    try:
        with target.open("r", encoding="utf-8") as handle:
            data = toml.loads(handle.read())
        return {"data": data, "error": None, "has_error": False}
    except toml.TomlDecodeError as exc:
        return {
            "data": defaults,
            "error": f"Invalid TOML syntax in {target.name}: {exc}",
            "has_error": True,
        }


def save_config(data: dict[str, Any]) -> None:
    ensure_config_exists()
    rendered = toml.dumps(data)
    with CONFIG_FILE.open("w", encoding="utf-8") as handle:
        handle.write(rendered)


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _labelize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _comment_map() -> dict[str, str]:
    comments: dict[str, str] = {}
    if not EXAMPLE_FILE.exists():
        return comments

    current_path: list[str] = []
    pending: list[str] = []
    section_re = re.compile(r"^\[([^\]]+)\]")
    key_re = re.compile(r"^([A-Za-z0-9_]+)\s*=")

    for raw in EXAMPLE_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            if text:
                pending.append(text)
            continue
        section_match = section_re.match(stripped)
        if section_match:
            current_path = section_match.group(1).split(".")
            pending = []
            continue
        key_match = key_re.match(stripped)
        if key_match:
            joined = ".".join([*current_path, key_match.group(1)]) if current_path else key_match.group(1)
            inline = ""
            if "#" in stripped:
                inline = stripped.split("#", 1)[1].strip()
            text_parts = [part for part in [" ".join(pending).strip(), inline] if part]
            if text_parts:
                comments[joined] = " ".join(text_parts)
            pending = []
    return comments


def get_config_metadata() -> dict[str, Any]:
    defaults = load_defaults()
    comments = _comment_map()
    metadata: dict[str, Any] = {}

    def walk(prefix: str, node: dict[str, Any], target: dict[str, Any]) -> None:
        for key, value in node.items():
            full = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                target[key] = {}
                walk(full, value, target[key])
            else:
                description = comments.get(full) or f"Configuration for {_labelize(key)}."
                target[key] = {
                    "type": _infer_type(value),
                    "default": value,
                    "description": description,
                    "recommendation": description,
                }

    walk("", defaults, metadata)
    return metadata
