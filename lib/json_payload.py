from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JsonParseResult:
    ok: bool
    value: Any | None
    error: str | None
    text: str


def decode_payload(payload: bytes | bytearray | str, *, encoding: str = "utf-8") -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, bytearray):
        payload = bytes(payload)
    return payload.decode(encoding, errors="replace")


def parse_json_payload(payload: bytes | bytearray | str) -> Any:
    """Parse payload as JSON.

    Returns a Python object (dict/list/str/number/bool/None).
    Raises json.JSONDecodeError for invalid JSON.
    """
    text = decode_payload(payload)
    return json.loads(text)


def try_parse_json_payload(payload: bytes | bytearray | str) -> JsonParseResult:
    text = decode_payload(payload)
    try:
        value = json.loads(text)
        return JsonParseResult(ok=True, value=value, error=None, text=text)
    except Exception as e:
        return JsonParseResult(ok=False, value=None, error=str(e), text=text)


def ensure_json_object(value: Any) -> dict[str, Any]:
    """Ensure value is a JSON object (dict)."""
    if isinstance(value, dict):
        return value
    raise TypeError(f"Expected JSON object (dict), got {type(value).__name__}")


def ensure_json_array(value: Any) -> list[Any]:
    """Ensure value is a JSON array (list)."""
    if isinstance(value, list):
        return value
    raise TypeError(f"Expected JSON array (list), got {type(value).__name__}")


_MISSING = object()


def get_value_by_key(obj: dict[str, Any], key: str, default: Any = _MISSING) -> Any:
    """Get value by key from a JSON object (dict).

    - If default is provided, returns default when key is missing.
    - If default is not provided, raises KeyError when key is missing.
    """
    if default is _MISSING:
        return obj[key]
    return obj.get(key, default)


def getValueByKey(obj: dict[str, Any], key: str, default: Any = _MISSING) -> Any:
    # Backward-compatible alias for existing code.
    return get_value_by_key(obj, key, default)