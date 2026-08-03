"""Shared helper for turning a user-entered Project Name into a safe,
consistent filename prefix (e.g. "WoodmenLife Max Cash Value" -> "WoodmenLife_Max_Cash_Value")."""

import re


def safe_filename_part(name: str, default: str = "Project") -> str:
    name = (name or "").strip()
    if not name:
        return default
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    return name or default
