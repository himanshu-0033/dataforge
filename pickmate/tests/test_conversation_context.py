import asyncio
import base64
import json

import httpx
import pytest
from counselor.config import Settings
from counselor.context import MAX_CONTEXT_BYTES, build_messages
from counselor.dialogue import connection_reply, is_voice_fragment
from counselor.sessions import Sessions
from counselor.vertex import VertexConversation


def test_context_keeps_early_details_beyond_forty_messages():
    history = [{"role": "user", "content": "My sister is Meera. I don't want journaling suggestions."}]
    history += [{"role": "user", "content": f"Another detail {i}"} for i in range(60)]
    result = build_messages(history, focus="Please help me talk about work.")
    assert history[0] in result and history[-1] == result[-1]
    assert result[1]["role"] == "user"
    assert "Please help me" not in result[0]["content"]


def test_long_multilingual_context_preserves_complete_latest_input():
    history = [{"role": "user", "content": "मन " * 1300} for _ in range(100)]
    history.append({"role": "user", "content": "Actually I'm safe now; that was last year."})
    result = build_messages(history)
    assert result[-1] == history[-1]
    assert len(result) < len(history)
    assert sum(len(m["content"].encode("utf-8")) + 32 for m in result[1:]) <= MAX_CONTEXT_BYTES
    assert all(m in history for m in result[1:])


@pytest.mark.parametrize("value", ["not-base64!", base64.b64encode(b"{}").decode()])
def test_invalid_base64_credentials_are_reported_without_echoing_them(value):
    settings = Settings(_env_file=None, counselor_provider="vertex", google_credentials_base64=value)
    assert settings.conversation_missing() == ["GOOGLE_CREDENTIALS_BASE64"]
    assert value not in repr(settings)


def test_service_account_project_and_provider_specific_requirements():
    info = {
        "type": "service_account",
        "project_id": "test-project",
        "client_email": "test@example.invalid",
        "private_key": "test-key",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    settings = Settings(
        _env_file=None,
        counselor_provider="vertex",
        google_credentials_base64=base64.b64encode(json.dumps(info).encode()).decode(),
    )
    assert settings.vertex_project == "test-project"
    assert not settings.conversation_missing()
    assert "GROQ_API_KEY" not in settings.missing()
    info["token_uri"] = "https://example.invalid/collect"
    settings.google_credentials_base64 = type(settings.google_credentials_base64)(
        base64.b64encode(json.dumps(info).encode()).decode()
    )
    assert settings.conversation_missing() == ["GOOGLE_CREDENTIALS_BASE64"]


class Auth:
    def __init__(self):
        self.requests = 0

    def before_request(self, request, method, url, headers):
        self.requests += 1
        headers["authorization"] = f"Bearer fixture-{self.requests}"


@pytest.mark.parametrize("finish", ["STOP", "MAX_TOKENS", "SAFETY"])
async def test_vertex_stream_preserves_roles_filters_thoughts_and_requires_completion(finish):
    seen = []

    def respond(request):
        seen.append(request)
        events = [
            {"candidates": [{"content": {"parts": [{"text": "private thought", "thought": True}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "You wanted "}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "room to talk."}]}, "finishReason": finish}]},
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    auth = Auth()
    adapter = VertexConversation(
        Settings(_env_file=None, google_cloud_project="test-project"), client=client, credentials=auth
    )
    messages = build_messages(
        [
            {"role": "user", "content": "I'm hurt."},
            {"role": "assistant", "content": "What happened?"},
            {"role": "user", "content": "Please just listen."},
        ],
        focus="No journaling.",
        support="listen",
    )
    deltas = []
    try:
        if finish == "STOP":
            assert await adapter.reply(messages, on_delta=deltas.append) == "You wanted room to talk."
            await adapter.reply(messages)
            assert seen[-1].headers["authorization"] == "Bearer fixture-2"
        else:
            with pytest.raises(ValueError, match="Incomplete"):
                await adapter.reply(messages, on_delta=deltas.append)
        assert deltas == ["You wanted ", "room to talk."]
        payload = json.loads(seen[0].content)
        assert [m["role"] for m in payload["contents"]] == ["user", "model", "user"]
        assert "No journaling." not in json.dumps(payload["systemInstruction"])
        assert "No journaling." in json.dumps(payload["contents"])
        assert seen[0].url.host == "aiplatform.googleapis.com"
        assert "gemini-3.1-pro-preview:streamGenerateContent" in seen[0].url.path
    finally:
        await adapter.close()


async def test_preferences_and_end_fence_late_streaming_results():
    started, release = asyncio.Event(), asyncio.Event()

    class Streaming:
        async def reply(self, history, *, focus, on_delta, **options):
            if focus == "Old note":
                on_delta("Unfinished old response")
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                on_delta("must be ignored")
                return "Obsolete reply"
            on_delta("Current reply")
            return "Current reply"

        async def close(self):
            pass

    store = Sessions(Streaming())
    session, _ = store.create("text")
    store.preferences(session, focus="Old note")
    store.turn(session, "Can we talk?", "one")
    await started.wait()
    assert session.draft and all("Unfinished" not in m["content"] for m in store.history(session))
    store.preferences(session, support="listen", focus="Corrected note")
    release.set()
    while store.jobs:
        await asyncio.gather(*list(store.jobs))
    assert session.messages[-1]["text"] == "Current reply" and not session.draft
    assert not any(m["text"] == "Obsolete reply" for m in session.messages)
    store.control(session, "end")
    assert not session.focus and not session.draft
    await store.close()


@pytest.mark.parametrize("text", ["No.", "Yes", "help", "I feel like giving up", "Please stop", "I'm fine"])
def test_meaningful_short_or_distressed_input_is_never_treated_as_filler(text):
    assert not is_voice_fragment(text)


def test_connection_check_is_grounded_and_does_not_swallow_disclosure():
    history = [{"role": "user", "content": "Can I can you listen me?"}]
    assert connection_reply(history, "live") == "Yes, your words are coming through. Take your time."
    assert connection_reply(history, "text") is None
    assert (
        connection_reply([{"role": "user", "content": "Can you listen to me? Nobody cares."}], "live") is None
    )


async def test_voice_filler_waits_without_triggering_a_reply_or_replaying_old_speech():
    class Recording:
        def __init__(self):
            self.calls = []

        async def reply(self, history, **options):
            self.calls.append(history)
            return "Go ahead."

        async def close(self):
            pass

    brain = Recording()
    store = Sessions(brain)
    session, _ = store.create("live")
    store.onset(session)
    store.turn(session, "Like,", "filler", source="voice")
    assert session.awaiting_continuation and not session.resolving and not store.jobs
    assert session.messages[-1]["text"] == "Like,"  # Visible, not silently deleted.
    store.onset(session)
    store.false_interruption(session)
    store.control(session, "recover")  # A reconnect must also leave space to finish.
    assert session.messages[-1]["role"] == "user"
    store.turn(session, "I don't know where to start", "thought", source="voice")
    while store.jobs:
        await asyncio.gather(*list(store.jobs))
    assert len(brain.calls) == 1 and not session.awaiting_continuation
    assert brain.calls[0][-1]["content"] == "I don't know where to start"
    store.control(session, "end")
    assert not session.awaiting_continuation
    await store.close()
