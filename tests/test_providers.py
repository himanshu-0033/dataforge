import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from pickmate.voice.providers import RimeConfig, validate_catalog
from pickmate.voice.worker import Bridge, eligible_speech, inventory_keyterms


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
        "task": {"task_id": "new", "task_version": 3},
        "speech": {
            "response_id": "r2",
            "response_epoch": 2,
            "task_id": "new",
            "task_version": 3,
            "status": "queued",
        },
    }


@pytest.mark.parametrize(
    "change", ["epoch", "version", "identity", "paused", "resolving", "ended", "completed"]
)
def test_scheduler_rejects_obsolete_speech(change):
    state = snapshot()
    assert eligible_speech(state)["response_id"] == "r2"
    if change == "epoch":
        state["response_epoch"] += 1
    elif change == "version":
        state["task"]["task_version"] += 1
    elif change == "identity":
        state["task"]["task_id"] = "replacement"
    elif change == "completed":
        state["speech"]["status"] = "completed"
    else:
        state[change] = True
    assert eligible_speech(state) is None


def test_controller_can_explicitly_allow_current_pause_acknowledgment():
    state = snapshot()
    state["paused"] = True
    state["speech"]["allow_while_paused"] = True
    assert eligible_speech(state)
    state["response_epoch"] += 1
    assert eligible_speech(state) is None


@pytest.mark.asyncio
async def test_false_interruption_is_idempotent_and_does_not_override_transcript():
    bridge = Bridge("s", "pickmate-s", None)
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
    bridge = Bridge("s", "pickmate-s", None)
    seen = []
    gate = asyncio.Event()

    async def call(route, data=None):
        seen.append(route)
        if route == "onset":
            await gate.wait()

    bridge.call = call
    onset = bridge.submit("onset", {})
    turn = bridge.submit("turn", {"text": "four red cartons"})
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
    bridge = Bridge("s", "pickmate-s", None)
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
    bridge = Bridge("s", "pickmate-s", None)
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
    bridge = Bridge("s", "pickmate-s", None)
    interruptions = []
    bridge.session = SimpleNamespace(interrupt=lambda **kwargs: interruptions.append(kwargs))
    calls = []

    async def call(route, data=None):
        calls.append((route, data))
        if route == "onset":
            raise TimeoutError()

    bridge.call = call
    onset = bridge.submit("onset", {})
    turn = bridge.submit("turn", {"text": "four red cartons"})
    await asyncio.wait_for(bridge.controls(), timeout=1)
    await asyncio.wait_for(bridge.poll(), timeout=1)
    await bridge.failure_task
    assert not await onset and not await turn
    assert bridge.closed and bridge.failed
    assert bridge.pending_controls == 0
    assert interruptions == [{"force": True}]
    assert [route for route, _ in calls] == ["onset", "metrics"]
    assert calls[-1][1]["data"]["source"] == "api_transport"


@pytest.mark.asyncio
async def test_delivery_estimate_uses_sdk_handle_identity_after_response_replacement():
    from livekit.agents import llm
    from livekit.agents.voice.speech_handle import SpeechHandle

    bridge = Bridge("s", "pickmate-s", None)
    bridge.current = "new-response"
    handle = SpeechHandle.create()
    item = llm.ChatMessage(role="assistant", content=["Bin B"], interrupted=True)
    # Mirrors SDK _say_task ordering: handle item is recorded before session event.
    handle._item_added([item])
    bridge.handles[handle.id] = (handle, {"response_id": "old-response", "response_epoch": 2})
    bridge.delivery_estimate(item)
    route, data, _ = bridge.queue.get_nowait()
    assert route == "metrics"
    assert data["data"]["response_id"] == "old-response"
    assert data["data"]["text"] == "Bin B"
    assert data["data"]["interrupted"]
    assert data["data"]["trusted"] is False
    unknown = llm.ChatMessage(role="assistant", content=["Unbound message"])
    bridge.delivery_estimate(unknown)
    assert bridge.queue.empty()


@pytest.mark.asyncio
async def test_worker_lease_is_attached_to_control_and_snapshot_requests(monkeypatch):
    import httpx

    monkeypatch.setenv("WORKER_SECRET", "fixture-worker-secret")
    headers = []

    def respond(request):
        headers.append(dict(request.headers))
        return httpx.Response(200, json={"worker_epoch": 7})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        bridge = Bridge("s", "pickmate-s", http)
        lease = await bridge.call("claim", {"worker_id": "job-fixture"})
        bridge.worker_epoch = lease["worker_epoch"]
        await bridge.call("snapshot")
        await bridge.call("onset", {})
    assert "x-worker-epoch" not in headers[0]
    assert all(header["x-worker-epoch"] == "7" for header in headers[1:])
    assert all(header["x-room-name"] == "pickmate-s" for header in headers)


def test_stt_keyterms_derive_from_inventory_names_and_aliases_only():
    terms = inventory_keyterms(
        {
            "inventory": [
                {"name": "Work gloves", "aliases": ["gloves", "Work gloves"]},
                {"name": "Blue cartons", "aliases": ["blue boxes"]},
            ]
        }
    )
    assert terms == ["Work gloves", "gloves", "Blue cartons", "blue boxes"]
    assert "nitrile gloves" not in terms
