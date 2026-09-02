import asyncio
import json

from app.services.notifications.hub import NotificationHub


class FakeWs:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed: int | None = None

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int | None = None) -> None:
        self.closed = code


def test_kick_user_only_same_client() -> None:
    async def run() -> None:
        hub = NotificationHub()
        ctor = FakeWs()
        orch = FakeWs()
        hub.add("u-1", ctor, session_id="s-ctor", client="constructor")
        hub.add("u-1", orch, session_id="s-orch", client="orchestrator")

        await hub.kick_user("u-1", client="constructor")

        assert ctor.closed == 4001
        assert json.loads(ctor.sent[0])["type"] == "session_replaced"
        assert orch.closed is None
        assert orch.sent == []
        assert hub.is_online("u-1") is True

    asyncio.run(run())


def test_replace_keeps_other_app_socket() -> None:
    async def run() -> None:
        hub = NotificationHub()
        ctor_old = FakeWs()
        ctor_new = FakeWs()
        orch = FakeWs()
        hub.add("u-1", ctor_old, session_id="s-old", client="constructor")
        hub.add("u-1", orch, session_id="s-orch", client="orchestrator")

        await hub.replace("u-1", ctor_new, session_id="s-new", client="constructor")

        assert ctor_old.closed == 4001
        assert orch.closed is None
        assert ctor_new in hub._sockets["u-1"]
        assert orch in hub._sockets["u-1"]

    asyncio.run(run())
