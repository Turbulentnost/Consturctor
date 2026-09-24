"""Run one regulation-interview turn through the local Cursor SDK.

stdin: the prompt. argv[1]: workspace id. stdout: one JSON object
{"answer": "..."} or {"error": "..."}.
"""

from __future__ import annotations

import json
import sys

from app.sdk_agent.bridge import (
    REGULATION_SDK_MODEL,
    REGULATION_SDK_QUESTION_PARAMS,
    CursorSdkBridge,
)
from app.sdk_agent.prompt import build_regulation_sdk_prompt


def main() -> int:
    workflow_id = (sys.argv[1] if len(sys.argv) > 1 else "regulation-interview").strip()
    mode = (sys.argv[2] if len(sys.argv) > 2 else "question").strip().lower()
    prompt = sys.stdin.read()
    if mode == "document":
        model_params = (
            {"id": "effort", "value": "medium"},
            {"id": "fast", "value": "false"},
        )
    else:
        model_params = REGULATION_SDK_QUESTION_PARAMS
    try:
        bridge = CursorSdkBridge()
        result = bridge.run(
            prompt=build_regulation_sdk_prompt(prompt),
            workflow_id=workflow_id,
            model=REGULATION_SDK_MODEL,
            model_params=[dict(item) for item in model_params],
            mode="interview",
            tools=[],
            write_document=False,
            use_tools=False,
            resume_agent_id="",
        )
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    answer = str(result.get("answer") or "").strip()
    sys.stdout.write(json.dumps({"answer": answer}, ensure_ascii=False))
    return 0 if answer else 1


if __name__ == "__main__":
    raise SystemExit(main())
