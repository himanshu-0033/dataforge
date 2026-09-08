import asyncio
import time

import httpx
import pytest
from counselor.app import create_app
from counselor.config import Settings
from counselor.sessions import Sessions


class FakeConversation:
    def __init__(self):
        self.histories = []

    async def reply(self, history, **kwargs):
        self.histories.append(history)
        return "We can take this one step at a time. What feels hardest today?"

    async def close(self):
        pass


@pytest.fixture
async def counselor():
    brain = FakeConversation()
    store = Sessions(brain)
    cfg = Settings(
        _env_file=None,
        groq_api_key="fixture-groq",
        deepgram_api_key="fixture-stt",
        livekit_api_key="fixture-lk",
        livekit_api_secret="x" * 32,
        livekit_url="wss://example.invalid",
        rime_api_key="fixture-rime",
        worker_secret="fixture-worker",
    )
    app = create_app(cfg, store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, store, brain
    await store.close()


async def begin(client, mode="text"):
    response = await client.post("/api/sessions", json={"mode": mode})
    assert response.status_code == 200
    created = response.json()
    return "/api/sessions/" + created["session_id"], {"Authorization": "Bearer " + created["token"]}


async def idle(store):
    while store.jobs:
        await asyncio.gather(*list(store.jobs))


async def test_open_conversation_ownership_context_and_duplicate_inputs(counselor):
    client, store, brain = counselor
    route, auth = await begin(client)
    assert (await client.get(route)).status_code == 401
    assert (await client.get(route, headers={"Authorization": "Bearer wrong"})).status_code == 403
    turn = {"text": "I'm overwhelmed by exams", "event_id": "same-input"}
    await client.post(route + "/turn", headers=auth, json=turn)
    await client.post(route + "/turn", headers=auth, json=turn)
    await idle(store)
    first = (await client.get(route, headers=auth)).json()
    assert len(first["messages"]) == 3
    assert first["messages"][-1]["status"] == "completed"
    await client.post(
        route + "/turn", headers=auth, json={"text": "Mostly the pressure to do well", "event_id": "followup"}
    )
    await idle(store)
    assert any(m["content"] == turn["text"] for m in brain.histories[-1])
    assert any(m["role"] == "assistant" and "one step" in m["content"] for m in brain.histories[-1])
    assert "owner_hash" not in first and "inputs" not in first


async def test_live_typing_works_while_voice_failed_or_paused(counselor):
    client, store, _ = counselor
    route, auth = await begin(client, "live")
    session = store.get(route.split("/")[-1])
    session.provider["status"] = "failed"
    await client.post(route + "/turn", headers=auth, json={"text": "I'd rather type", "event_id": "one"})
    await idle(store)
    assert session.messages[-1]["status"] == "completed"
    await client.post(route + "/control", headers=auth, json={"action": "pause"})
    await client.post(route + "/turn", headers=auth, json={"text": "Can we talk?", "event_id": "two"})
    await idle(store)
    assert session.paused and session.messages[-1]["status"] == "completed"
    await client.post(route + "/control", headers=auth, json={"action": "resume"})
    assert not session.paused


async def test_interrupted_speech_is_excluded_and_stale_completion_is_ignored():
    brain = FakeConversation()
    store = Sessions(brain)
    session, _ = store.create("live")
    interrupted = session.speech["response_id"]
    store.onset(session)
    store.turn(session, "Hello", "one")
    await idle(store)
    store.playback(session, interrupted, "completed")
    assert brain.histories[0] == [{"role": "user", "content": "Hello"}]
    assert session.messages[0]["status"] == "interrupted"
    current = session.speech["response_id"]
    store.playback(session, current, "playing")
    store.playback(session, current, "completed")
    store.playback(session, current, "interrupted")
    assert session.messages[-1]["status"] == "completed"
    await store.close()


async def test_late_generation_cannot_override_a_correction_or_ended_session():
    started = asyncio.Event()
    release = asyncio.Event()

    class Slow(FakeConversation):
        async def reply(self, history, **kwargs):
            if history[-1]["content"] == "old concern":
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # Simulate a cancellation-ignoring provider.
                return "Obsolete answer"
            return "Current answer"

    store = Sessions(Slow())
    session, _ = store.create("text")
    store.turn(session, "old concern", "old")
    await started.wait()
    store.turn(session, "corrected concern", "new")
    await asyncio.sleep(0)
    release.set()
    await idle(store)
    assert session.messages[-1]["text"] == "Current answer"
    assert not any(m["text"] == "Obsolete answer" for m in session.messages)
    started.clear()
    release.clear()
    store.turn(session, "old concern", "late")
    await started.wait()
    store.control(session, "end")
    release.set()
    await idle(store)
    assert session.messages == [] and session.speech is None and not session.inputs
    await store.close()


async def test_worker_replacement_fences_retired_callbacks_and_browser_cannot_ack_audio(counselor):
    client, store, _ = counselor
    route, auth = await begin(client, "live")
    sid = route.split("/")[-1]
    base = f"/api/internal/sessions/{sid}"
    worker = {"X-Worker-Key": "fixture-worker", "X-Room-Name": "heard-" + sid}
    assert (await client.post(base + "/claim", json={"worker_id": "a"})).status_code == 403
    first = await client.post(base + "/claim", headers=worker, json={"worker_id": "a"})
    assert first.json()["worker_epoch"] == 1
    # The first claim must not interrupt or duplicate the introduction.
    assert len(store.get(sid).messages) == 1 and store.get(sid).speech["status"] == "queued"
    lease1 = {**worker, "X-Worker-Epoch": "1"}
    await client.post(base + "/provider", headers=lease1, json={"status": "connected"})
    await client.post(base + "/recover", headers=lease1)
    assert len(store.get(sid).messages) == 1
    await client.post(base + "/claim", headers=worker, json={"worker_id": "b"})
    assert (await client.post(base + "/onset", headers=lease1)).status_code == 409
    assert (
        await client.post(base + "/turn", headers=lease1, json={"text": "stale text", "event_id": "old"})
    ).status_code == 409
    assert (
        await client.post(route + "/playback", headers=auth, json={"response_id": "x", "status": "completed"})
    ).status_code == 404


async def test_end_clears_transcript_and_inactive_sessions_expire(counselor):
    client, store, _ = counselor
    route, auth = await begin(client)
    await client.post(
        route + "/turn", headers=auth, json={"text": "Synthetic private concern", "event_id": "first"}
    )
    await idle(store)
    ended = (await client.post(route + "/control", headers=auth, json={"action": "end"})).json()
    assert ended["ended"] and ended["messages"] == [] and ended["speech"] is None
    assert (
        await client.post(route + "/turn", headers=auth, json={"text": "too late", "event_id": "second"})
    ).status_code == 409
    session = store.get(route.split("/")[-1])
    session.touched = time.monotonic() - 3601
    store.expire()
    assert (await client.get(route, headers=auth)).status_code == 404


async def test_worker_timeout_updates_actual_state_so_typing_still_completes():
    store = Sessions(FakeConversation())
    session, _ = store.create("live")
    session.provider["status"] = "active"
    session.worker_seen = time.monotonic() - 16
    assert store.snapshot(session)["provider"]["status"] == "disconnected"
    store.turn(session, "I'll type instead", "fallback")
    await idle(store)
    assert session.messages[-1]["status"] == "completed"
    await store.close()


async def test_failed_generation_can_be_retried_without_duplicate_user_message():
    class Flaky(FakeConversation):
        calls = 0

        async def reply(self, history, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return "Thanks for waiting. What's on your mind?"

    store = Sessions(Flaky())
    session, _ = store.create("text")
    store.turn(session, "Hi", "input")
    await idle(store)
    assert session.error and not session.resolving
    store.control(session, "retry")
    await idle(store)
    assert not session.error
    assert len([m for m in session.messages if m["role"] == "user"]) == 1
    assert session.messages[-1]["role"] == "assistant"
    await store.close()
