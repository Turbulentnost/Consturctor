"""Headless driver: re-run the SDK design (formation) for one workflow.

Mirrors WorkflowPage._run_design_with_sdk without Qt so we can reproduce and
observe the formation, then save the fresh draft. Prints compact events and
writes the parsed plan to _formation_out.json (UTF-8).
"""

from __future__ import annotations

import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

WORKFLOW_ID = "754829e8-3af5-4192-ab34-44d8ef368d89"

from app.api_client import ApiClient, ApiError
from app.config import backend_url, erp_login, erp_password
from app.sdk_agent import CursorSdkBridge
from app.sdk_agent.files import prepare_sdk_workspace
from app.sdk_agent.prompt import build_design_sdk_prompt, inferred_design_answers
from app.tools.runtime_api import configure as configure_runtime_api
from app.ui.pages.workflow_page import (
    _draft_from_sdk_answer,
    _local_design_prompt_for_record,
    _sdk_design_transcript,
    apply_sdk_answers_to_draft,
    merge_design_answers,
    qa_from_design_answers,
    qa_from_sdk_events,
)


def _p(*a: object) -> None:
    print(*a, flush=True)


def main() -> int:
    api = ApiClient(base_url=backend_url())
    fio, pwd = erp_login(), erp_password()
    _p(f"[login] backend={api.base_url} fio={fio!r}")
    api.login(fio, pwd)
    configure_runtime_api(token=api.token, base_url=api.base_url)
    _p("[login] ok, token set")

    record = api.get_workflow(WORKFLOW_ID)
    _p(f"[workflow] {WORKFLOW_ID} phase={record.phase} title={record.title!r}")

    answered = merge_design_answers(
        (record.local_run or {}).get("design_answers"),
        inferred_design_answers(record),
    )
    qa = qa_from_design_answers(answered)
    _p(f"[answers] {len(qa)} stored Q/A")

    try:
        design_prompt = api.local_design_prompt(WORKFLOW_ID)
    except ApiError as exc:
        _p(f"[design_prompt] backend failed ({exc}); using local fallback")
        design_prompt = _local_design_prompt_for_record(record)

    events: list[dict] = []

    def on_event(payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        et = str(payload.get("type") or "")
        if et in {"ready", "done"}:
            return
        events.append(payload)
        if et == "tool_call":
            _p(f"  [tool_call] {payload.get('tool')}")
        elif et == "tool_result":
            _p(f"  [tool_result] {payload.get('tool')} ok")
        elif et == "assistant":
            txt = str(payload.get("text") or "")[:160].replace("\n", " ")
            if txt:
                _p(f"  [assistant] {txt}")
        elif et in {"question", "status", "decision", "error", "thinking"}:
            _p(f"  [{et}] {str(payload.get('text') or payload.get('message') or '')[:160]}")

    def on_question(payload: dict) -> dict:
        q = str(payload.get("question") or (payload.get("arguments") or {}).get("question") or "")
        _p(f"  [ASK] {q[:160]}")
        for stored_q, stored_a in qa:
            if stored_q and stored_a and stored_q[:20].lower() in q.lower():
                _p(f"  [ANSWER stored] {stored_a[:120]}")
                return {"ok": True, "answer": stored_a}
        default = "Действуй по паспорту и уже данным ответам, новых вопросов не задавай."
        _p("  [ANSWER default]")
        return {"ok": True, "answer": default}

    bridge = CursorSdkBridge()
    bridge.check_ready()
    run_cwd = bridge.workspace_cwd(WORKFLOW_ID)
    prepare_sdk_workspace(
        api,
        WORKFLOW_ID,
        run_cwd,
        workflow=record,
        extra_brief=design_prompt,
    )
    sdk_prompt = build_design_sdk_prompt(record, design_prompt)
    _p(f"[prompt] len={len(sdk_prompt)} cwd={run_cwd}")
    _p(f"[run] mode=design cwd={run_cwd}")

    result = bridge.run(
        prompt=sdk_prompt,
        workflow_id=WORKFLOW_ID,
        cwd=run_cwd,
        mode="design",
        on_event=on_event,
        on_question=on_question,
        confirm_writes=False,
    )
    answer = str(result.get("answer") or "").strip()
    agent_id = str(result.get("agent_id") or "")
    _p(f"[run] done status={result.get('status')} agent_id={agent_id} answer_len={len(answer)}")

    fresh_qa = list(qa) or qa_from_sdk_events(events)
    transcript = _sdk_design_transcript(answer, events)
    draft = apply_sdk_answers_to_draft(_draft_from_sdk_answer(transcript), fresh_qa)

    steps = draft.get("steps") or []
    _p(f"[draft] steps={len(steps)}")
    for s in steps:
        _p(
            "  - {id} | {sys}/{ent}/{op} | tools={tc}".format(
                id=s.get("id"),
                sys=s.get("system"),
                ent=s.get("entity"),
                op=s.get("operation"),
                tc=s.get("tool_candidates"),
            )
        )

    out = {
        "answer": answer,
        "agent_id": agent_id,
        "status": result.get("status"),
        "draft": draft,
    }
    with open("_formation_out.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    _p("[out] wrote _formation_out.json")

    if steps:
        try:
            finished = api.finish_local_design_workflow(
                WORKFLOW_ID,
                answer=json.dumps(draft, ensure_ascii=False),
                events=events,
            )
            _p(f"[save] finish_local_design ok, phase={finished.phase}")
        except ApiError as exc:
            _p(f"[save] finish_local_design failed: {exc}")
    else:
        _p("[save] no steps parsed; not saving")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
