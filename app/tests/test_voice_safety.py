import asyncio

import pytest
from counselor.safety import CRISIS_MARKER, SAFETY_REPLY, explicit_crisis
from counselor.sessions import Sessions


class Brain:
    async def reply(self, history, **kwargs):
        return "What would feel helpful right now?"

    async def close(self):
        pass


@pytest.mark.parametrize(
    "text",
    [
        "I want to die",
        "I'm suicidal",
        "I am thinking about suicide",
        "I plan to end my life tonight",
        "I just overdosed",
        "I might hurt myself",
        "I was safe last year, but I want to kill myself now",
    ],
)
def test_explicit_current_disclosures(text):
    assert explicit_crisis(text)


@pytest.mark.parametrize(
    "text",
    [
        "I'm not suicidal",
        "I don't want to die",
        "I no longer want to die",
        "I used to want to die",
        "Last year I wanted to die",
        'The book says "I want to die"',
        "What should I do if someone says I want to die?",
        "My friend said I'm suicidal",
        "I'm overwhelmed by work",
        "I cut myself while cooking",
    ],
)
def test_fast_path_leaves_negation_history_quotes_and_ambiguity_to_context(text):
    assert not explicit_crisis(text)


async def test_crisis_bypasses_provider_and_interrupts_previous_audio():
    store = Sessions(None)
    session, _ = store.create("live")
    original = session.speech["response_id"]
    store.turn(session, "I want to die", "crisis")
    snapshot = store.snapshot(session)
    assert snapshot["ui"]["overlay"] == "CRISIS_MODE"
    assert snapshot["ui"]["crisis_id"] == "crisis"
    assert session.messages[0]["status"] == "interrupted"
    assert session.speech["text"] == SAFETY_REPLY and session.speech["status"] == "queued"
    store.playback(session, original, "completed")
    assert session.messages[0]["status"] == "interrupted"
    assert not store.jobs
    store.control(session, "retry")
    assert not store.jobs and session.speech["text"] == SAFETY_REPLY
    store.control(session, "end")
    assert store.snapshot(session)["ui"] == {
        "status": "PAUSED",
        "phase": "PAUSED",
        "interruption_id": 0,
        "overlay": None,
        "crisis_id": None,
        "acknowledgement": None,
    }
    await store.close()


@pytest.mark.parametrize("fail", [False, True])
async def test_contextual_crisis_signal_never_leaks_into_draft_or_speech(fail):
    class Contextual(Brain):
        async def reply(self, history, *, on_delta, **kwargs):
            for part in ("[CRI", "SIS_", "MODE]"):
                on_delta(part)
                assert session.draft == ""
            assert store.snapshot(session)["ui"]["overlay"] == "CRISIS_MODE"
            if fail:
                raise RuntimeError("Provider lost")
            on_delta(" You deserve support.")
            assert session.draft == "You deserve support."
            return CRISIS_MARKER + " You deserve support."

    store = Sessions(Contextual())
    session, _ = store.create("text")
    store.turn(session, "An indirect disclosure interpreted in context", "context")
    await asyncio.gather(*store.jobs)
    assert session.speech["text"] == (SAFETY_REPLY if fail else "You deserve support.")
    assert CRISIS_MARKER not in str(store.history(session))
    await store.close()


async def test_obsolete_crisis_signal_cannot_open_overlay_for_newer_turn():
    ready, release = asyncio.Event(), asyncio.Event()

    class Late(Brain):
        async def reply(self, history, *, on_delta, **kwargs):
            if history[-1]["content"] == "Old input":
                ready.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                on_delta(CRISIS_MARKER)
                return CRISIS_MARKER + " Obsolete"
            return "Current"

    store = Sessions(Late())
    session, _ = store.create("text")
    store.turn(session, "Old input", "old")
    await ready.wait()
    store.turn(session, "New input", "new")
    release.set()
    await asyncio.gather(*store.jobs)
    assert not session.crisis_id and session.messages[-1]["text"] == "Current"
    await store.close()


async def test_status_precedence_and_acknowledgement_cleanup():
    class Slow(Brain):
        async def reply(self, history, **kwargs):
            await asyncio.sleep(5)

    store = Sessions(Slow())
    session, _ = store.create("live")
    store.playback(session, session.speech["response_id"], "playing")
    assert store.snapshot(session)["ui"]["status"] == "SPEAKING"
    store.onset(session)
    assert store.snapshot(session)["ui"]["status"] == "LISTENING"
    store.turn(session, "A long account of a difficult day. " * 6, "long")
    assert store.snapshot(session)["ui"]["status"] == "PROCESSING"
    assert store.snapshot(session)["ui"]["acknowledgement"]
    store.control(session, "pause")
    assert store.snapshot(session)["ui"]["status"] == "PAUSED"
    assert not store.snapshot(session)["ui"]["acknowledgement"]
    await store.close()
