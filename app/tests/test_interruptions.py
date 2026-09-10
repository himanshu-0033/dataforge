import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from counselor.context import MAX_CONTEXT_BYTES, build_messages
from counselor.dialogue import is_voice_fragment
from counselor.sessions import Sessions
from counselor.worker import INTERRUPTION_SECONDS, VAD_ONSET_SECONDS, Bridge


async def settle(store):
    while store.jobs:
        await asyncio.gather(*list(store.jobs))


async def test_interruption_fuses_original_partial_output_and_new_correction():
    calls = []
    release = asyncio.Event()

    class Brain:
        async def reply(self, history, **options):
            calls.append((history, options))
            if len(calls) > 1:
                await release.wait()
            return "You felt pushed into that choice. What mattered most to you?"

        async def close(self):
            pass

    store = Sessions(Brain())
    session, _ = store.create("live")
    store.playback(session, session.speech["response_id"], "completed")
    store.turn(session, "My manager made that decision for me.", "original", source="voice")
    await settle(store)
    original = dict(session.speech)
    store.playback(session, original["response_id"], "playing")
    store.onset(session)
    assert session.speech["status"] == "interrupted"
    assert store.snapshot(session)["ui"]["status"] == "LISTENING"
    assert store.snapshot(session)["ui"]["interruption_id"] == 1
    store.playback(session, original["response_id"], "interrupted", "You felt pushed")
    store.turn(session, "No, I mean my brother, not my manager.", "correction", source="voice")
    assert store.snapshot(session)["ui"]["phase"] == "PROCESSING_FUSED_CONTEXT"
    await asyncio.sleep(0)
    history, options = calls[-1]
    assert [m["content"] for m in history if m["role"] == "user"] == [
        "My manager made that decision for me.",
        "No, I mean my brother, not my manager.",
    ]
    assert all(m["content"] != original["text"] for m in history)
    assert options["interrupted"][0]["played_text"] == "You felt pushed"
    assert options["interrupted"][0]["delivery"] == "playout_estimate"
    fused = build_messages(history, interrupted=options["interrupted"], mode="live")
    assert "You felt pushed" in fused[-2]["content"]
    assert fused[-1] == history[-1] and fused[-2]["role"] == "user"
    assert original["text"] not in fused[0]["content"]
    # Late old callbacks cannot mark the cancelled reply completed or resume it.
    store.playback(session, original["response_id"], "completed")
    assert session.speech["status"] == "interrupted"
    release.set()
    await settle(store)
    assert not session.interrupted_context
    new_speech = dict(session.speech)
    store.playback(session, original["response_id"], "interrupted", "Late old text")
    assert session.speech == new_speech and not session.interrupted_context
    await store.close()


async def test_generation_is_cancelled_and_unspoken_draft_is_explicitly_labeled():
    started, cancelled = asyncio.Event(), asyncio.Event()

    class Brain:
        async def reply(self, history, *, on_delta, **options):
            on_delta("Unspoken partial thought")
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                on_delta("Obsolete delta")
                return "Obsolete reply"

        async def close(self):
            pass

    store = Sessions(Brain())
    session, _ = store.create("live")
    store.playback(session, session.speech["response_id"], "completed")
    store.turn(session, "I want to explain.", "original")
    await started.wait()
    store.onset(session)
    await settle(store)
    assert cancelled.is_set() and session.draft == ""
    assert session.interrupted_context[-1]["delivery"] == "not_spoken"
    assert session.interrupted_context[-1]["generated_text"] == "Unspoken partial thought"
    assert not any(m["text"] == "Obsolete reply" for m in session.messages)
    store.control(session, "end")
    assert not session.interrupted_context
    await store.close()


def test_interrupted_context_is_bounded_and_keeps_latest_multilingual_input():
    latest = {"role": "user", "content": "\U0001f331" * 8000}
    background = [
        {
            "generated_text": "\U0001f331" * 16000,
            "played_text": "\U0001f331" * 16000,
            "delivery": "playout_estimate",
        }
        for _ in range(5)
    ]
    result = build_messages([{"role": "user", "content": "old" * 20000}, latest], interrupted=background)
    assert result[-1] == latest
    assert sum(len(m["content"].encode()) + 32 for m in result[1:]) <= MAX_CONTEXT_BYTES


async def test_worker_clears_audio_before_cancelling_generation_and_reports_played_fragment():
    bridge = Bridge("fixture", "heard-fixture", None)
    events = []
    bridge.session = SimpleNamespace(
        output=SimpleNamespace(audio=SimpleNamespace(clear_buffer=lambda: events.append("clear"))),
        interrupt=lambda **kwargs: events.append("cancel"),
    )
    bridge.interrupt()
    assert events == ["clear", "cancel"]
    bridge.playback = AsyncMock()
    handle = SimpleNamespace(
        id="fixture",
        interrupted=True,
        wait_for_playout=AsyncMock(),
        chat_items=[
            SimpleNamespace(role="assistant", text_content="You felt"),
            SimpleNamespace(role="user", text_content="This is not counselor speech"),
        ],
    )
    await bridge.finish(handle, "reply")
    bridge.playback.assert_awaited_once_with("reply", "interrupted", "You felt")
    assert not bridge.failed
    assert 0 < VAD_ONSET_SECONDS < 0.2 and 0 < INTERRUPTION_SECONDS < 0.2
    assert not is_voice_fragment("wait") and not is_voice_fragment("no")
