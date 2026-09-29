import json
from pathlib import Path

path = Path(
    r"C:\Users\a.komarkova\.cursor\projects\c-Users-a-komarkova-Documents-projects-NewConstructor\terminals\850348.txt"
)
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if '"type": "tool_result"' not in line:
        continue
    if not any(name in line for name in ("onec.meeting_protocols", "onec.erp_assignments", "write_action_tracker")):
        continue
    payload = (json.loads(line).get("payload") or {})
    tool = str(payload.get("tool") or "")
    if tool not in {"onec.meeting_protocols", "onec.erp_assignments", "excel.write_action_tracker"}:
        continue
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    protocols = result.get("protocols")
    print(
        tool,
        "ok", payload.get("ok"),
        "count", result.get("count"),
        "assignments", result.get("assignments"),
        "protocols", len(protocols) if isinstance(protocols, list) else result.get("protocols"),
        "truncated", result.get("truncated"),
        "file", result.get("result_file") or result.get("protocols_file"),
        "error", str(result.get("error") or payload.get("error") or "")[:240],
    )
