from app.services import cursor_llm


def test_cursor_llm_generate_uses_cached_agent(monkeypatch) -> None:
    cursor_llm.reset_runtime_agent()

    def fake_create_agent(**kwargs):
        return {
            "agent": {"id": "bc-test-agent"},
            "run": {"id": "run-init", "status": "RUNNING"},
        }

    def fake_create_run(agent_id, *, prompt, mode=None):
        return {"id": f"run-{prompt}"}

    def fake_wait(agent_id, run_id, *, timeout_seconds=180.0):
        if run_id == "run-init":
            return {"status": "FINISHED", "result": "ignored init"}
        return {"status": "FINISHED", "result": f"answer:{run_id}"}

    create_calls = {"count": 0}

    def counting_create_agent(**kwargs):
        create_calls["count"] += 1
        return fake_create_agent(**kwargs)

    monkeypatch.setattr("app.services.cursor_llm.cursor_client.create_agent", counting_create_agent)
    monkeypatch.setattr("app.services.cursor_llm.cursor_client.create_run", fake_create_run)
    monkeypatch.setattr("app.services.cursor_llm.cursor_client.wait_for_run", fake_wait)
    monkeypatch.setattr("app.config.settings.cursor_api_key", "crsr_test")

    first = cursor_llm.generate("first", quick=True)
    second = cursor_llm.generate("second", quick=True)

    assert first == "answer:run-first"
    assert second == "answer:run-second"
    assert create_calls["count"] == 1
