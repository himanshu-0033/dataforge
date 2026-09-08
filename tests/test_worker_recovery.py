import asyncio

import httpx
import pytest
from pickmate.api.app import create_app
from pickmate.config import Settings
from pickmate.domain.controller import Controller
from pickmate.storage.database import Database, SupersededWorker, worker_lease
from pickmate.voice.dispatch import Dispatcher


async def test_concurrent_reconnects_keep_first_replacement_dispatch(monkeypatch):
    from types import SimpleNamespace

    from pickmate.voice import dispatch

    remote = {
        "dispatches": [
            SimpleNamespace(id="retired", agent_name="pickmate", state=SimpleNamespace(deleted_at=0, jobs=[]))
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
    d = Dispatcher(Settings(_env_file=None))
    failed = {"room": "pickmate-fixture", "worker_epoch": 1, "provider": {"status": "failed"}}
    await asyncio.gather(d.ensure(failed), d.ensure(failed))
    assert remote["created"] == 1
    assert remote["dispatches"][0].id == "fresh-1"


async def test_retiring_worker_cannot_overwrite_new_provider_or_turn(tmp_path):
    cfg = Settings(_env_file=None, worker_secret="fixture-worker-secret")
    c = Controller(Database(tmp_path / "lease.sqlite"))
    await c.initialize()
    sid, _ = await c.create_session("live")
    auth = {"X-Worker-Key": cfg.worker_secret, "X-Room-Name": f"pickmate-{sid}"}
    base = f"/api/internal/sessions/{sid}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(cfg, c)), base_url="http://test"
    ) as client:
        a = (await client.post(base + "/claim", headers=auth, json={"worker_id": "old-job"})).json()[
            "worker_epoch"
        ]
        old = auth | {"X-Worker-Epoch": str(a)}
        await client.post(base + "/provider", headers=old, json={"status": "failed", "name": "rime"})
        b = (await client.post(base + "/claim", headers=auth, json={"worker_id": "new-job"})).json()[
            "worker_epoch"
        ]
        new = auth | {"X-Worker-Epoch": str(b)}
        assert b == a + 1
        await client.post(base + "/provider", headers=new, json={"status": "connected", "name": "rime"})
        await client.post(base + "/recover", headers=new, json={})
        assert (
            await client.post(
                base + "/provider", headers=old, json={"status": "disconnected", "name": "rime"}
            )
        ).status_code == 409
        assert (
            await client.post(
                base + "/turn", headers=old, json={"text": "Confirm four red cartons", "event_id": "obsolete"}
            )
        ).status_code == 409
        s = (await client.get(base + "/snapshot", headers=new)).json()
        assert s["provider"]["status"] == "connected"
        assert s["speech"]["status"] == "queued"
        assert not s["paused"]
    await c.close()


async def test_lease_is_revalidated_inside_transaction_after_http_auth(tmp_path):
    c = Controller(Database(tmp_path / "atomic-lease.sqlite"))
    await c.initialize()
    sid, _ = await c.create_session("live")
    a = (await c.claim_worker(sid, "old"))["worker_epoch"]
    start = asyncio.Event()
    release = asyncio.Event()

    async def old_callback():
        token = worker_lease.set((sid, a))
        try:
            start.set()
            await release.wait()
            with pytest.raises(SupersededWorker):
                await c.provider(sid, {"status": "failed"})
        finally:
            worker_lease.reset(token)

    pending = asyncio.create_task(old_callback())
    await start.wait()
    await c.claim_worker(sid, "new")
    await c.provider(sid, {"status": "connected"})
    release.set()
    await pending
    assert (await c.snapshot(sid))["provider"]["status"] == "connected"
    await c.close()
