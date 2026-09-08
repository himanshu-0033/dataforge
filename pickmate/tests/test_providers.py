import asyncio
import runpy
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from counselor.providers import RimeConfig, validate_catalog
from counselor.worker import Bridge, eligible_speech


def test_worker_cli_reads_local_env_before_constructing_the_server(monkeypatch, tmp_path):
    from livekit import agents

    values = {
        "LIVEKIT_URL": "wss://fixture.example.invalid",
        "LIVEKIT_API_KEY": "fixture-key",
        "LIVEKIT_API_SECRET": "fixture-secret",
    }
    for name in values:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("\n".join(f"{key}={value}" for key, value in values.items()))
    seen = []
    monkeypatch.setattr(
        agents.cli,
        "run_app",
        lambda server: seen.append((server._ws_url, server._api_key, server._api_secret)),
    )
    monkeypatch.delitem(sys.modules, "counselor.worker")
    runpy.run_module("counselor.worker", run_name="__main__")
    assert seen == [tuple(values.values())]


def test_catalog_checks_exact_model_language_voice_pairing():
    catalog = {"coda": {"eng": ["astra"], "spa": ["other"]}, "mistv2": {"eng": ["only-mist"]}}
    assert validate_catalog(catalog, RimeConfig())["catalog_language"] == "eng"
    with pytest.raises(ValueError):
        validate_catalog(catalog, RimeConfig(speaker="only-mist"))
    with pytest.raises(ValueError):
        validate_catalog(catalog, RimeConfig(speaker="other"))
    with pytest.raises(ValueError):
        validate_catalog({"coda": ["astra"]}, RimeConfig())


@pytest.mark.parametrize(
    "url",
    [
        "wss://users-ws.rime.ai/ws3",
        "wss://users-ws.rime.ai?token=abc",
        "https://users.rime.ai",
        "wss://user:pass@users-ws.rime.ai",
        "wss://attacker.example",
    ],
)
def test_endpoint_rejects_duplicated_paths_or_credentials(url):
    with pytest.raises(ValueError):
        RimeConfig(base_url=url).validate()


@pytest.mark.asyncio
async def test_actual_plugin_builds_explicit_wire_configuration():
    provider = RimeConfig().make_tts(api_key="fixture-key-not-real")
    try:
        url = urlsplit(provider._ws_url())
        assert url.path == "/ws3"
        query = parse_qs(url.query)
        assert {
            k: query[k] for k in ("modelId", "speaker", "lang", "segment", "samplingRate", "audioFormat")
        } == {
            "modelId": ["coda"],
            "speaker": ["astra"],
            "lang": ["en"],
            "segment": ["bySentence"],
            "samplingRate": ["24000"],
            "audioFormat": ["pcm"],
        }
        assert "fixture-key-not-real" not in provider._ws_url()
    finally:
        await provider.aclose()


def snapshot():
    return {
        "response_epoch": 2,
        "speech": {
            "response_id": "r2",
            "response_epoch": 2,
            "status": "queued",
        },
    }


@pytest.mark.parametrize("change", ["epoch", "paused", "resolving", "ended", "completed"])
def test_scheduler_rejects_obsolete_speech(change):
    state = snapshot()
    assert eligible_speech(state)["response_id"] == "r2"
    if change == "epoch":
        state["response_epoch"] += 1
    elif change == "completed":
        state["speech"]["status"] = "completed"
    else:
        state[change] = True
    assert eligible_speech(state) is None


@pytest.mark.asyncio
async def test_false_interruption_is_idempotent_and_does_not_override_transcript():
    bridge = Bridge("s", "heard-s", None)
    bridge.input_resolved = False
    bridge.false_interruption()
    bridge.false_interruption()
    assert bridge.queue.qsize() == 1
    bridge.input_resolved = False
    bridge.transcript_seen = True
    bridge.false_interruption()
    assert bridge.queue.qsize() == 1


@pytest.mark.asyncio
async def test_onset_is_processed_before_final_turn_and_fences_inflight_control():
    bridge = Bridge("s", "heard-s", None)
    seen = []
    gate = asyncio.Event()

    async def call(route, data=None):
        seen.append(route)
        if route == "onset":
            await gate.wait()

    bridge.call = call
    onset = bridge.submit("onset", {})
    turn = bridge.submit("turn", {"text": "I feel overwhelmed"})
    runner = asyncio.create_task(bridge.controls())
    await asyncio.sleep(0)
    assert seen == ["onset"]
    assert bridge.pending_controls == 2
    gate.set()
    await turn
    assert await onset
    assert seen == ["onset", "turn"]
    assert bridge.pending_controls == 0
    runner.cancel()
    await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
async def test_late_playback_callback_retains_original_response_identity():
    bridge = Bridge("s", "heard-s", None)
    bridge.current = "new-response"
    events = []

    async def playback(response_id, status):
        events.append((response_id, status))

    bridge.playback = playback

    class Handle:
        interrupted = True

        async def wait_for_playout(self):
            await asyncio.sleep(0)

    await bridge.finish(Handle(), "old-response")
    assert events == [("old-response", "interrupted")]
    assert bridge.current == "new-response"


@pytest.mark.asyncio
async def test_recovery_clears_failed_provider_before_asking_controller_to_speak():
    bridge = Bridge("s", "heard-s", None)
    calls = []
    status = "failed"

    async def call(route, data):
        nonlocal status
        calls.append(route)
        if route == "provider":
            status = data["status"]
        elif route == "recover":
            assert status == "connected"

    bridge.call = call
    await bridge.recover()
    assert calls == ["provider", "recover"]


@pytest.mark.asyncio
async def test_api_failure_exits_control_and_poll_without_false_rime_failure():
    bridge = Bridge("s", "heard-s", None)
    interruptions = []
    bridge.session = SimpleNamespace(interrupt=lambda **kwargs: interruptions.append(kwargs))
    calls = []

    async def call(route, data=None):
        calls.append((route, data))
        if route == "onset":
            raise TimeoutError()

    bridge.call = call
    onset = bridge.submit("onset", {})
    turn = bridge.submit("turn", {"text": "I feel overwhelmed"})
    await asyncio.wait_for(bridge.controls(), timeout=1)
    await asyncio.wait_for(bridge.poll(), timeout=1)
    await bridge.failure_task
    assert not await onset and not await turn
    assert bridge.closed and bridge.failed
    assert bridge.pending_controls == 0
    assert interruptions == [{"force": True}]
    assert [route for route, _ in calls] == ["onset"]


@pytest.mark.asyncio
async def test_worker_lease_is_attached_to_control_and_snapshot_requests(monkeypatch):
    import httpx

    monkeypatch.setenv("WORKER_SECRET", "fixture-worker-secret")
    headers = []

    def respond(request):
        headers.append(dict(request.headers))
        return httpx.Response(200, json={"worker_epoch": 7})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        bridge = Bridge("s", "heard-s", http)
        lease = await bridge.call("claim", {"worker_id": "job-fixture"})
        bridge.worker_epoch = lease["worker_epoch"]
        await bridge.call("snapshot")
        await bridge.call("onset", {})
    assert "x-worker-epoch" not in headers[0]
    assert all(header["x-worker-epoch"] == "7" for header in headers[1:])
    assert all(header["x-room-name"] == "heard-s" for header in headers)
