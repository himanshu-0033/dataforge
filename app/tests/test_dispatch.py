import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from counselor import dispatch
from counselor.config import AGENT_NAME, Settings
from counselor.dispatch import Dispatcher


async def test_concurrent_reconnects_keep_first_replacement_dispatch(monkeypatch):
    remote = {
        "dispatches": [
            SimpleNamespace(id="retired", agent_name=AGENT_NAME, state=SimpleNamespace(deleted_at=0, jobs=[]))
        ],
        "created": 0,
    }

    class Service:
        async def __aenter__(self):
            self.room = self
            self.agent_dispatch = self
            return self

        async def __aexit__(self, *args):
            pass

        async def create_room(self, request):
            await asyncio.sleep(0)

        async def list_dispatch(self, room):
            return remote["dispatches"][:]

        async def delete_dispatch(self, ident, room):
            remote["dispatches"] = [d for d in remote["dispatches"] if d.id != ident]

        async def create_dispatch(self, request):
            remote["created"] += 1
            d = SimpleNamespace(
                id=f"fresh-{remote['created']}",
                agent_name=request.agent_name,
                state=SimpleNamespace(deleted_at=0, jobs=[]),
            )
            remote["dispatches"].append(d)
            return d

    monkeypatch.setattr(dispatch.api, "LiveKitAPI", lambda **kwargs: Service())
    dispatcher = Dispatcher(Settings(_env_file=None))
    failed = {"room": "heard-fixture", "worker_epoch": 1, "provider": {"status": "failed"}}
    await asyncio.gather(dispatcher.ensure(failed), dispatcher.ensure(failed))
    assert remote["created"] == 1
    assert remote["dispatches"][0].id == "fresh-1"


async def test_recovered_heartbeat_is_rechecked_before_dispatch_deletion(monkeypatch):
    existing = SimpleNamespace(
        id="healthy", agent_name=AGENT_NAME, state=SimpleNamespace(deleted_at=0, jobs=[])
    )

    class Service:
        def __init__(self):
            self.room = self.agent_dispatch = self
            self.create_room = AsyncMock()
            self.list_dispatch = AsyncMock(return_value=[existing])
            self.delete_dispatch = AsyncMock()
            self.create_dispatch = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    service = Service()
    monkeypatch.setattr(dispatch.api, "LiveKitAPI", lambda **kwargs: service)
    stale = {
        "room": "heard-fixture",
        "worker_epoch": 1,
        "ended": False,
        "provider": {"status": "disconnected"},
    }
    healthy = {**stale, "provider": {"status": "active"}}
    dispatcher = Dispatcher(Settings(_env_file=None))
    await dispatcher.ensure(stale, refresh=lambda: healthy)
    service.delete_dispatch.assert_not_called()
    service.create_dispatch.assert_not_called()
