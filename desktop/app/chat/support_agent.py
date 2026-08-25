from __future__ import annotations

import json
from typing import Any


def echo_command(payload: dict[str, Any]) -> str:
    """Temporary echo: return the same payload the client sends to the chat API."""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
