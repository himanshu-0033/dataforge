import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from counselor.app import create_app
from counselor.config import Settings
from counselor.sessions import Sessions
from counselor.worker import Bridge, transient_api_error


async def test_worker_retries_transient_transport_without_disconnect(monkeypatch):
    monkeypatch.setenv("WORKER_SECRET", "fixture-worker")
    calls = []

    def transport(request):
        calls.append(request.headers["x-voice-event"])
        if len(calls) < 3:
            raise httpx.ReadTimeout("fixture", request=request)
        return httpx.Response(200, json={"accepted": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        bridge = Bridge("fixture", "heard-fixture", http)
        assert await bridge.call("onset", {}) == {"accepted": True}
        assert len(calls) == 3 and len(set(calls)) == 1
        assert not bridge.closed and not bridge.failed


async def test_worker_poll_survives_exhausted_read_retry_then_recovers():
    bridge = Bridge("fixture", "heard-fixture", None)
    bridge.session = SimpleNamespace(interrupt=lambda **kwargs: pytest.fail("Healthy audio was stopped"))
    bridge.call = AsyncMock(side_effect=[httpx.ReadTimeout("fixture"), {"ended": True}])
    await bridge.poll()
    assert bridge.call.await_count == 2 and not bridge.failed and not bridge.closed


async def test_worker_waits_for_rejoin_but_releases_abandoned_room():
    bridge = Bridge("fixture", "heard-fixture", None)
    bridge.participant_present = False
    bridge.participant_left_at = time.monotonic() - 61
    bridge.call = AsyncMock(return_value={"response_epoch": 1})
    await bridge.poll()
    assert not bridge.failed


def test_authentication_and_retired_lease_errors_are_not_retried():
    for code in (401, 403, 404, 409):
        response = httpx.Response(code, request=httpx.Request("GET", "http://fixture"))
        assert not transient_api_error(
            httpx.HTTPStatusError("fixture", request=response.request, response=response)
        )


async def test_service_repair_is_authenticated_keeps_worker_and_dedupes_onset():
    store = Sessions(None)
    dispatcher = SimpleNamespace(ensure=AsyncMock())
    cfg = Settings(_env_file=None, worker_secret="fixture-worker")
    app = create_app(cfg, store, dispatcher)
    session, token = store.create("live")
    session.worker_epoch = 1
    session.worker_seen = time.monotonic()
    session.provider["status"] = "active"
    route = f"/api/sessions/{session.session_id}"
    auth = {"Authorization": f"Bearer {token}"}
    worker = {
        "X-Worker-Key": "fixture-worker",
        "X-Worker-Epoch": "1",
        "X-Room-Name": session.room,
        "X-Voice-Event": "onset-one",
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
        assert (await client.post(route + "/voice/recover")).status_code == 401
        state = (await client.post(route + "/voice/recover", headers=auth)).json()
        assert state["worker_epoch"] == 1 and state["provider"]["status"] == "active"
        assert dispatcher.ensure.call_args.kwargs["refresh"]()["provider"]["status"] == "active"
        endpoint = f"/api/internal/sessions/{session.session_id}/onset"
        assert (await client.post(endpoint, headers=worker, json={})).status_code == 200
        epoch = session.response_epoch
        session.user_speaking = False
        assert (await client.post(endpoint, headers=worker, json={})).status_code == 200
        assert session.response_epoch == epoch and not session.user_speaking
        await client.post(route + "/control", headers=auth, json={"action": "end"})
        assert (await client.post(route + "/voice/recover", headers=auth)).status_code == 409
    await store.close()
