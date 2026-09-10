"""User/role/default response overrides for custom commands.

Configuration is intentionally environment-only so no new database migration is
needed. The JSON object is loaded from CUSTOM_RESPONSE_OVERRIDES_JSON.

Shape:
{
  "default": {"hi": "hi default"},
  "users": {"123": {"hi": "hi user"}},
  "roles": {"456": {"hi": "hi role"}}
}

Resolution order: exact user ID -> highest-priority matching role -> default.
Unknown or malformed entries are ignored instead of breaking bot startup.
"""
from __future__ import annotations

import json
import os
from typing import Any


ENV_NAME = "CUSTOM_RESPONSE_OVERRIDES_JSON"


def _load() -> dict[str, Any]:
    raw = os.environ.get(ENV_NAME, "").strip()
    if not raw:
        return {"default": {}, "users": {}, "roles": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"default": {}, "users": {}, "roles": {}}
    if not isinstance(data, dict):
        return {"default": {}, "users": {}, "roles": {}}
    return {
        "default": data.get("default") if isinstance(data.get("default"), dict) else {},
        "users": data.get("users") if isinstance(data.get("users"), dict) else {},
        "roles": data.get("roles") if isinstance(data.get("roles"), dict) else {},
    }


def resolve_override(command_name: str, user_id: int, role_ids_high_to_low: list[int]) -> tuple[str | None, str]:
    """Return (response, source) using USER > ROLE > DEFAULT precedence."""
    data = _load()
    name = command_name.casefold()
    user_map = data["users"].get(str(user_id), {})
    if isinstance(user_map, dict) and isinstance(user_map.get(name), str):
        return user_map[name], "user"

    for role_id in role_ids_high_to_low:
        role_map = data["roles"].get(str(role_id), {})
        if isinstance(role_map, dict) and isinstance(role_map.get(name), str):
            return role_map[name], "role"

    default = data["default"].get(name)
    if isinstance(default, str):
        return default, "default"
    return None, "none"


def has_any_override(command_name: str) -> bool:
    """Small helper for diagnostics/tests."""
    name = command_name.casefold()
    data = _load()
    if isinstance(data["default"].get(name), str):
        return True
    return any(isinstance(value, dict) and isinstance(value.get(name), str) for value in data["users"].values()) or any(
        isinstance(value, dict) and isinstance(value.get(name), str) for value in data["roles"].values()
    )
