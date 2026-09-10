import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from counselor.config import Settings
from counselor.conversation import Conversation
from counselor.latency import voice_reply
from counselor.worker import Bridge


async def test_voice_uses_fast_profile_with_the_same_safety_context(monkeypatch):
    instances = []

    class Backend:
        def __init__(self, settings):
            self.model = settings.vertex_model
            self.thinking = settings.vertex_thinking_level
            self.reply = AsyncMock(return_value="What would help right now?")
            self.close = AsyncMock()
            instances.append(self)

    monkeypatch.setattr("counselor.conversation.VertexConversation", Backend)
    conversation = Conversation(Settings(_env_file=None, counselor_provider="vertex"))
    history = [{"role": "user", "content": "I've had a difficult day."}]
    await conversation.reply(history, mode="live")
    text, voice = instances
    assert voice.model == "gemini-3-flash-preview" and voice.thinking == "MINIMAL"
    assert text.model == "gemini-3.1-pro-preview" and text.thinking == "MEDIUM"
    text.reply.assert_not_called()
    context = voice.reply.call_args.args[0]
    assert "[CRISIS_MODE]" in context[0]["content"]
    assert "This reply will be spoken" in context[0]["content"]
    assert context[-1] == history[-1]
    await conversation.reply(history, mode="text")
    text.reply.assert_awaited_once()
    await conversation.close()
    text.close.assert_awaited_once()
    voice.close.assert_awaited_once()


@pytest.mark.parametrize("cancel_reason", ["ready", "onset", "pause"])
async def test_acknowledgement_never_holds_up_ready_reply_or_interruption(cancel_reason):
    bridge = Bridge("fixture", "heard-fixture", None)
    ack = SimpleNamespace(interrupt=lambda **kwargs: events.append("ack interrupted"))
    bridge.ack_handle = ack
    bridge.ack_epoch = 4
    bridge.ack_started = float("inf")  # Exercise state change, not the timeout.
    events = []
    handle = SimpleNamespace(id="handle", interrupt=lambda **kwargs: None)

    def say(text, **kwargs):
        events.append("reply started")
        bridge.closed = True
        return handle

    bridge.session = SimpleNamespace(user_state="listening", say=say, interrupt=lambda **kwargs: None)
    speech = {"response_epoch": 4, "response_id": "reply", "text": "A full reply.", "status": "queued"}
    state = {"response_epoch": 4, "speech": speech, "thinking": False}
    if cancel_reason == "pause":
        state["paused"] = True
    if cancel_reason == "onset":
        state.update(user_speaking=True, resolving=True)

    async def call(route, data=None):
        if cancel_reason != "ready":
            bridge.closed = True
        return state

    bridge.call = call
    bridge.finish = AsyncMock()
    await bridge.poll()
    assert events == (
        ["ack interrupted", "reply started"] if cancel_reason == "ready" else ["ack interrupted"]
    )
    assert not bridge.failed
    if bridge.tasks:
        await asyncio.gather(*bridge.tasks)


async def test_worker_cleanup_survives_session_already_closed():
    bridge = Bridge("fixture", "heard-fixture", None)

    def stopped(**kwargs):
        raise RuntimeError("AgentSession isn't running")

    bridge.session = SimpleNamespace(interrupt=stopped)
    bridge.report_failure = AsyncMock()
    bridge.fail("api_transport", RuntimeError("Lost connection"))
    await bridge.failure_task
    assert bridge.closed and bridge.failed
    bridge.report_failure.assert_awaited_once()


async def test_stalled_voice_attempt_is_replaced_without_duplicate_or_late_text():
    calls = 0
    cancelled = asyncio.Event()
    deltas = []

    class Backend:
        async def reply(self, messages, *, on_delta):
            nonlocal calls
            calls += 1
            if calls == 1:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    on_delta("Obsolete text")
                    cancelled.set()
                    return "Obsolete text"
            on_delta("Current reply")
            return "Current reply"

    reply = await voice_reply(Backend(), [], on_delta=deltas.append, retry_delay=0.01)
    assert reply == "Current reply" and deltas == ["Current reply"]
    assert calls == 2 and cancelled.is_set()


async def test_voice_does_not_retry_after_first_text_or_mix_failed_streams():
    calls = 0

    class Backend:
        async def reply(self, messages, *, on_delta):
            nonlocal calls
            calls += 1
            on_delta("Already started")
            await asyncio.sleep(0.02)
            raise ValueError("Incomplete stream")

    with pytest.raises(ValueError, match="Incomplete"):
        await voice_reply(Backend(), [], retry_delay=0.001)
    assert calls == 1


async def test_cancelling_voice_cancels_both_requests_and_suppresses_late_deltas():
    calls = 0
    both_started = asyncio.Event()
    deltas = []

    class Backend:
        async def reply(self, messages, *, on_delta):
            nonlocal calls
            calls += 1
            if calls == 2:
                both_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                on_delta("Late")
                return "Late"

    task = asyncio.create_task(voice_reply(Backend(), [], on_delta=deltas.append, retry_delay=0.001))
    await both_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert deltas == []
