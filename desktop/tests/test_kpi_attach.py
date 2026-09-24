from __future__ import annotations

from pathlib import Path

from app.sdk_agent.bridge import (
    CursorSdkError,
    cursor_sdk_error_text,
    is_transient_cursor_error,
)
from app.sdk_agent.kpi_attach import (
    KPI_SOURCE_OPTIONS,
    catalog_from_jobs,
    collect_kpi_prompt_images,
    kpi_repair_prompt,
    kpi_slug,
    kpi_write_jobs,
    kpi_write_prompt,
    needs_source_detail,
    parse_kpi_rows,
    source_for_kpi,
    source_kind_from_answer,
    source_spec_from_answer,
    unasked_kpi_rows,
    write_kpi_example_files,
)


def _write_scan_pdf_pages(path: Path, count: int) -> None:
    import fitz

    document = fitz.open()
    for _ in range(count):
        page = document.new_page()
        page.draw_rect(page.rect, color=(0.1, 0.1, 0.1), width=3)
    document.save(str(path))
    document.close()


def test_collect_kpi_prompt_images_skips_cover(tmp_path: Path) -> None:
    attachments = tmp_path / "materials" / "attachments"
    attachments.mkdir(parents=True)
    source = attachments / "001_method.pdf"
    _write_scan_pdf_pages(source, 3)

    pages = collect_kpi_prompt_images(tmp_path)
    assert [item["page"] for item in pages] == [2]
    assert all(item["filename"] == "001_method.pdf" for item in pages)
    assert all((tmp_path / item["path"]).is_file() for item in pages)
    assert not (tmp_path / "materials" / "vision" / ".attached").is_file()


def test_collect_kpi_prompt_images_empty_without_file(tmp_path: Path) -> None:
    assert collect_kpi_prompt_images(tmp_path) == []


def test_parse_kpi_rows_from_agent_list() -> None:
    rows = parse_kpi_rows(
        "\n".join(
            [
                "1. Планирование заседаний — вес 40%",
                "2. Назначение ДПИ — 10%",
                "просто текст без веса",
            ]
        )
    )
    assert [(item["name"], item["weight"]) for item in rows] == [
        ("Планирование заседаний", "40"),
        ("Назначение ДПИ", "10"),
    ]


def test_unasked_kpi_rows_skips_names_already_in_questions() -> None:
    rows = [
        {"name": "Планирование совещаний", "weight": "40"},
        {"name": "Назначение ДПИ", "weight": "10"},
    ]
    pending = unasked_kpi_rows(
        rows,
        "Откуда брать план и факт по показателю «Планирование совещаний (40%)»?",
    )
    assert [item["name"] for item in pending] == ["Назначение ДПИ"]


def test_parse_kpi_rows_without_space_after_number() -> None:
    rows = parse_kpi_rows("1.Планирование заседаний — вес 40%\n2.Назначение ДПИ — вес 10%")
    assert [item["weight"] for item in rows] == ["40", "10"]


def test_kpi_slug_transliterates_russian_name() -> None:
    assert kpi_slug("Планирование заседаний", 1) == "planirovanie_zasedaniy"
    assert kpi_slug("Назначение ДПИ", 2) == "naznachenie_dpi"


def test_source_kind_and_catalog_from_jobs() -> None:
    assert source_kind_from_answer("1С") == "onec"
    assert source_kind_from_answer("Outlook") == "outlook"
    assert source_kind_from_answer("Уже написано в положении") == "regulation"
    assert source_kind_from_answer("Excel или другой файл") == "files"
    assert source_kind_from_answer("Форма / вручную") == "manual"
    assert source_kind_from_answer("Ходы агента") == "agent_runs"
    assert source_kind_from_answer("Турбопроект") == "unknown"
    assert (
        source_kind_from_answer(
            "план фактный отчет по совещаниям за месяц, где руководитель = Донцова Анна Егоровна"
        )
        == "onec"
    )
    assert needs_source_detail("Другая система — напишу какая")
    assert not needs_source_detail("1С")
    assert "Другая система — напишу какая" in KPI_SOURCE_OPTIONS
    assert source_spec_from_answer("Турбопроект") == {
        "kind": "unknown",
        "note": "Турбопроект",
    }
    jobs = kpi_write_jobs(
        [
            {"name": "Планирование заседаний", "weight": "40"},
            {"name": "Назначение ДПИ", "weight": "10"},
            {"name": "Отчёт по объектам", "weight": "20", "source": "Турбопроект"},
        ],
        source_notes="Планирование заседаний: 1С\nНазначение ДПИ: Outlook",
        position="Помощник руководителя",
    )
    catalog = catalog_from_jobs(jobs, position="Помощник руководителя")
    assert catalog["position_name"] == "Помощник руководителя"
    first, second, third = catalog["metrics"]
    assert first["code"] == "planirovanie_zasedaniy"
    assert first["sources"][1]["kind"] == "onec"
    assert first["sources"][1]["extra_json"]["loader"] == "odata"
    assert second["sources"][1]["kind"] == "outlook"
    assert second["sources"][1]["extra_json"]["loader"] == "outlook"
    assert third["sources"][1]["kind"] == "unknown"
    assert third["sources"][1]["extra_json"]["note"] == "Турбопроект"
    assert "loader" not in third["sources"][1]["extra_json"]


def test_source_for_kpi_reads_answer_line() -> None:
    notes = (
        "Откуда брать план и факт по показателю «Планирование заседаний (40%)»? — 1С\n"
        "Назначение ДПИ: Outlook"
    )
    assert source_for_kpi("Планирование заседаний", notes) == "1С"
    assert source_for_kpi("Назначение ДПИ", notes) == "Outlook"


def test_kpi_write_jobs_one_slug_per_prompt() -> None:
    jobs = kpi_write_jobs(
        [
            {"name": "Планирование заседаний", "weight": "40"},
            {"name": "Назначение ДПИ", "weight": "10"},
        ],
        source_notes="Планирование заседаний: 1С\nНазначение ДПИ: Outlook",
        position="Помощник руководителя",
    )
    assert [item["slug"] for item in jobs] == [
        "planirovanie_zasedaniy",
        "naznachenie_dpi",
    ]
    first, second = jobs[0]["prompt"], jobs[1]["prompt"]
    assert "Пиши только один модуль" in first
    assert "Не читай PDF" in first
    assert "KPI уже выписаны" in first
    assert "generated/planirovanie_zasedaniy.py" in first
    assert "generated/naznachenie_dpi.py" not in first
    assert "score_planirovanie_zasedaniy_kpi(rows, *, as_of" in first
    assert "load_planirovanie_zasedaniy_rows(ctx)" in first
    assert "compute_planirovanie_zasedaniy_kpi(ctx" in first
    assert "def score_orders_on_time_kpi(rows, *, as_of" in first
    assert "def load_orders_on_time_rows(ctx)" in first
    assert "def compute_orders_on_time_kpi(ctx" in first
    assert '"source": "onec.odata"' in first
    assert "data_sources.json" in first
    assert "Откуда брать план и факт: 1С" in first
    assert "Источник любой" in first
    assert "не подставляй odata" not in first
    turbo = kpi_write_prompt(
        position="Секретарь",
        name="Отчёт по объектам",
        weight="20",
        source="Турбопроект",
        slug="otchet_po_obektam",
    )
    assert "Турбопроект" in turbo
    assert "data_sources.json" in turbo
    assert "Турбопроект" in turbo
    assert "Помощник руководителя" in first
    assert "generated/naznachenie_dpi.py" in second
    assert "generated/planirovanie_zasedaniy.py" not in second
    assert "onec.odata_catalog" in first
    assert "Имена EntitySet не выдумывай" in first


def test_kpi_write_jobs_skips_existing_slug() -> None:
    jobs = kpi_write_jobs(
        [
            {"name": "Планирование заседаний", "weight": "40"},
            {"name": "Назначение ДПИ", "weight": "10"},
        ],
        existing_slugs=["planirovanie_zasedaniy"],
    )
    assert [item["slug"] for item in jobs] == ["naznachenie_dpi"]


def test_kpi_repair_prompt_stays_on_one_slug() -> None:
    text = kpi_repair_prompt("orders_on_time", "E   tests/test_orders_on_time.py FAILED")
    assert "Тесты не прошли" in text
    assert "generated/orders_on_time.py" in text
    assert "tests/test_orders_on_time.py" in text
    assert "Не читай PDF" in text
    assert "Не пиши другие slug" in text
    assert "onec.odata_catalog" in text
    assert "FAILED" in text


def test_write_kpi_example_matches_contract(tmp_path: Path) -> None:
    write_kpi_example_files(tmp_path)
    sample = (tmp_path / "orders_on_time.py").read_text(encoding="utf-8")
    test = (tmp_path / "test_orders_on_time.py").read_text(encoding="utf-8")
    assert "def score_orders_on_time_kpi(rows, *, as_of" in sample
    assert "def load_orders_on_time_rows(ctx)" in sample
    assert "def compute_orders_on_time_kpi(ctx" in sample
    assert '"source": "onec.odata"' in sample
    assert "fact_pct" in sample
    assert "compute_orders_on_time_kpi" in test


def test_kpi_write_prompt_tokens_skip_pdf_hint() -> None:
    text = kpi_write_prompt(
        position="Секретарь",
        name="Приказы",
        weight="50",
        source="1С",
        slug="prikazy",
    )
    assert "KPI уже выписаны" in text
    assert "Не читай PDF" in text
    assert "office.read_file" in text
    assert "start_page" not in text


def test_sidecar_write_loop_is_one_slug_new_agent() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (
        root / "orchestrator" / "desktop-electron" / "pybridge" / "agent_sidecar.py"
    ).read_text(encoding="utf-8")
    write_fn = text.split("def _write_kpi_modules", 1)[1].split(
        "def _rewrite_kpi_until_tests_pass", 1
    )[0]
    assert "kpi_write_jobs" in write_fn
    assert "Пишу модуль" in write_fn
    assert 'resume_agent_id=""' in write_fn
    assert "resume_agent_id=writer_id" in write_fn
    assert "kpi_repair_prompt(slug" in write_fn
    assert "_kpi_write_prompt" not in text
    module_fn = text.split("def _run_kpi_module", 1)[1].split("def _run_demo", 1)[0]
    assert "_write_kpi_modules" in module_fn
    assert "_catalog_draft_from_kpi" in module_fn
    assert "images=[]" in module_fn
    assert "images=images" not in module_fn
    assert "max_pages=1" in text
    assert "max_pages=20" not in text
    assert "_kpi_write_prompt" not in module_fn
    assert "needs_source_detail" in text
    assert "Какая система, отчёт или файл" in text
    assert "_kpi_retry_without_images" in text
    assert "sdk_kpi_write_tool_specs" in text
    assert "confirm_writes=True" in text.split("def _run_kpi_code_turn", 1)[1].split(
        "def _write_kpi_modules", 1
    )[0]


def _load_orch_sidecar():
    import sys

    root = Path(__file__).resolve().parents[2]
    pybridge = str(root / "orchestrator" / "desktop-electron" / "pybridge")
    if pybridge not in sys.path:
        sys.path.insert(0, pybridge)
    import agent_sidecar as sidecar_mod

    return sidecar_mod


def test_write_kpi_modules_starts_new_agent_each_slug(tmp_path: Path, monkeypatch) -> None:
    from threading import Event
    from types import SimpleNamespace

    sidecar_mod = _load_orch_sidecar()
    calls: list[dict] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"answer": "wrote", "agent_id": f"w{len(calls)}"}

    monkeypatch.setattr(sidecar_mod, "_run_kpi_slug_tests", lambda *_a, **_k: (True, "passed"))
    monkeypatch.setattr(sidecar_mod, "_promote_kpi_artifacts", lambda *_a, **_k: None)
    monkeypatch.setattr(sidecar_mod, "_existing_kpi_slugs", lambda *_a, **_k: [])

    gate = SimpleNamespace(ask_question=lambda *_a, **_k: {}, bind_events=lambda *_a, **_k: None)
    active = sidecar_mod.ActiveRun("run-1", gate, Event(), SimpleNamespace())
    sidecar_mod.Sidecar()._write_kpi_modules(
        active=active,
        bridge=SimpleNamespace(run=fake_run),
        run_cwd=tmp_path,
        workspace_id="kpi-1",
        events=[],
        answer="list",
        position="Секретарь",
        rows=[
            {"name": "Планирование заседаний", "weight": "40"},
            {"name": "Назначение ДПИ", "weight": "10"},
        ],
        source_notes="Планирование заседаний: 1С\nНазначение ДПИ: Outlook",
    )
    assert [item["resume_agent_id"] for item in calls] == ["", ""]
    assert "generated/planirovanie_zasedaniy.py" in calls[0]["prompt"]
    assert "generated/naznachenie_dpi.py" not in calls[0]["prompt"].split("Образец", 1)[0]
    assert "generated/naznachenie_dpi.py" in calls[1]["prompt"]
    assert calls[0].get("images") in (None, [])


def test_write_kpi_modules_repairs_on_same_writer(tmp_path: Path, monkeypatch) -> None:
    from threading import Event
    from types import SimpleNamespace

    sidecar_mod = _load_orch_sidecar()
    calls: list[dict] = []
    checks = iter([(False, "FAILED traceback"), (True, "passed")])

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {"answer": "fix", "agent_id": f"w{len(calls)}"}

    monkeypatch.setattr(sidecar_mod, "_run_kpi_slug_tests", lambda *_a, **_k: next(checks, (True, "passed")))
    monkeypatch.setattr(sidecar_mod, "_promote_kpi_artifacts", lambda *_a, **_k: None)
    monkeypatch.setattr(sidecar_mod, "_existing_kpi_slugs", lambda *_a, **_k: [])

    gate = SimpleNamespace(ask_question=lambda *_a, **_k: {}, bind_events=lambda *_a, **_k: None)
    sidecar_mod.Sidecar()._write_kpi_modules(
        active=sidecar_mod.ActiveRun("run-1", gate, Event(), SimpleNamespace()),
        bridge=SimpleNamespace(run=fake_run),
        run_cwd=tmp_path,
        workspace_id="kpi-1",
        events=[],
        answer="list",
        position="Секретарь",
        rows=[{"name": "Приказы", "weight": "50"}],
        source_notes="Приказы: 1С",
    )
    assert len(calls) == 2
    assert calls[0]["resume_agent_id"] == ""
    assert calls[1]["resume_agent_id"] == "w1"
    assert "Тесты не прошли" in calls[1]["prompt"]
    assert "prikazy" in calls[1]["prompt"]


def test_transient_cursor_errors() -> None:
    assert is_transient_cursor_error(CursorSdkError("Cursor SDK run failed"))
    assert is_transient_cursor_error(CursorSdkError("Network request failed"))
    assert is_transient_cursor_error("database is locked")
    assert not is_transient_cursor_error(CursorSdkError("CURSOR_API_KEY не задан"))
    assert (
        cursor_sdk_error_text(
            status="error",
            answer="",
            error_events=["Network request failed"],
        )
        == "Network request failed"
    )
    assert (
        cursor_sdk_error_text(status="error", answer="", error_events=[])
        == "Cursor SDK run failed"
    )


def test_kpi_bridge_run_drops_images_after_network_fail(tmp_path: Path, monkeypatch) -> None:
    from threading import Event
    from types import SimpleNamespace

    sidecar_mod = _load_orch_sidecar()
    calls: list[dict] = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        if kwargs.get("images"):
            raise CursorSdkError("Network request failed")
        return {"answer": "1. Приказы — вес 50%\nСПИСОК_ГОТОВ", "agent_id": "a2"}

    monkeypatch.setattr(sidecar_mod.time, "sleep", lambda *_a, **_k: None)
    gate = SimpleNamespace(ask_question=lambda *_a, **_k: {}, bind_events=lambda *_a, **_k: None)
    result = sidecar_mod.Sidecar()._kpi_bridge_run(
        sidecar_mod.ActiveRun("run-1", gate, Event(), SimpleNamespace()),
        SimpleNamespace(run=fake_run),
        prompt="Страницы положения уже в этом сообщении",
        workflow_id="kpi-1",
        images=[{"path": "p2.jpg"}],
        tools=[],
    )
    assert result["answer"].startswith("1. Приказы")
    assert calls[0]["images"]
    assert calls[1]["images"] == []
    assert "office.read_file" in str(calls[1].get("tools"))


def test_write_kpi_modules_retries_then_continues(tmp_path: Path, monkeypatch) -> None:
    from threading import Event
    from types import SimpleNamespace

    sidecar_mod = _load_orch_sidecar()
    calls = {"n": 0}

    def fake_run(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise CursorSdkError("Cursor SDK run failed")
        return {"answer": "wrote", "agent_id": "w-ok"}

    monkeypatch.setattr(sidecar_mod.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(sidecar_mod, "_run_kpi_slug_tests", lambda *_a, **_k: (True, "passed"))
    monkeypatch.setattr(sidecar_mod, "_promote_kpi_artifacts", lambda *_a, **_k: None)
    monkeypatch.setattr(sidecar_mod, "_existing_kpi_slugs", lambda *_a, **_k: [])

    gate = SimpleNamespace(ask_question=lambda *_a, **_k: {}, bind_events=lambda *_a, **_k: None)
    sidecar_mod.Sidecar()._write_kpi_modules(
        active=sidecar_mod.ActiveRun("run-1", gate, Event(), SimpleNamespace()),
        bridge=SimpleNamespace(run=fake_run),
        run_cwd=tmp_path,
        workspace_id="kpi-1",
        events=[],
        answer="list",
        position="Секретарь",
        rows=[{"name": "Приказы", "weight": "50"}],
        source_notes="Приказы: 1С",
    )
    assert calls["n"] == 2


def test_skip_trigger_while_kpi_module_runs() -> None:
    from threading import Event
    from types import SimpleNamespace

    sidecar_mod = _load_orch_sidecar()
    sidecar = sidecar_mod.Sidecar()
    started: list[str] = []
    gate = SimpleNamespace(bind=lambda **_k: None, bind_events=lambda *_a, **_k: None)
    live = sidecar_mod.ActiveRun("kpi-1", gate, Event(), SimpleNamespace(_process=None))
    live.kind = "kpi_module"
    live.thread = SimpleNamespace(is_alive=lambda: True)
    sidecar._active[live.run_id] = live
    sidecar._run_safe = lambda kind, *_a, **_k: started.append(kind)
    sidecar.start("check_trigger", {"id": "trg-1", "triggerId": "t-1", "workflowId": "wf-1"})
    assert started == []
    assert "trg-1" not in sidecar._active
