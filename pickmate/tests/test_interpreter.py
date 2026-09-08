import asyncio
import json

import httpx
import pytest
from openai import AsyncOpenAI
from pickmate.voice.interpreter import Interpreter


def chunk(arguments="", name=None, finish=None):
    return {
        "id": "fixture-stream",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "fixture",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_fixture",
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ]
                },
                "finish_reason": finish,
            }
        ],
    }


def sse(chunks):
    return "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"


async def test_default_adapter_sends_groq_key_only_to_groq_and_validates_stream(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.invalid/v1")

    async def send(request):
        assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fixture-groq"
        body = json.loads(request.content)
        assert body["model"] == "openai/gpt-oss-120b"
        assert body["stream"] is True and body["parallel_tool_calls"] is False
        assert "strict" not in body["tools"][0]["function"]
        assert body["tool_choice"]["function"]["name"] == "propose_operation"
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            text=sse(
                [
                    chunk('{"action":"request",', name="propose_operation"),
                    chunk('"query":"red cartons","quantity":4}', finish="tool_calls"),
                ]
            ),
        )

    monkeypatch.setattr(
        "pickmate.voice.interpreter.AsyncOpenAI",
        lambda **kwargs: AsyncOpenAI(
            **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(send))
        ),
    )
    adapter = Interpreter("fixture-groq")
    try:
        result = await adapter.interpret("Find four red cartons", None, [])
        assert result.action == "request" and result.quantity == 4 and result.query == "red cartons"
    finally:
        await adapter.close()


async def test_real_openai_sdk_stream_adapter_assembles_only_complete_tool_arguments():
    async def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True and body["parallel_tool_calls"] is False
        assert body["tools"][0]["function"]["parameters"]["additionalProperties"] is False
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                [
                    chunk('{"action":"request",', name="propose_operation"),
                    chunk('"query":"red cartons","quantity":4,"explicit":false}', finish="tool_calls"),
                ]
            ),
        )

    client = AsyncOpenAI(
        api_key="fixture-not-real", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    adapter = Interpreter("fixture-not-real", client=client)
    try:
        result = await adapter.interpret("Wait make that four red cartons", None, [])
        assert result.action == "request" and result.query == "red cartons" and result.quantity == 4
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "args,finish",
    [
        ('{"action":"confirm"', "tool_calls"),
        ('{"action":"request","quantity":-4}', "tool_calls"),
        ('{"action":"confirm","admin":true}', "tool_calls"),
        ('{"action":"confirm"}', "length"),
    ],
)
async def test_partial_invalid_or_truncated_stream_cannot_become_operation(args, finish):
    client = AsyncOpenAI(
        api_key="fixture-not-real",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    text=sse([chunk(args, name="propose_operation", finish=finish)]),
                )
            )
        ),
    )
    adapter = Interpreter("fixture-not-real", client=client)
    try:
        with pytest.raises(ValueError):
            await adapter.interpret("uncertain", None, [])
    finally:
        await adapter.close()


async def test_cancelling_model_stream_closes_transport_before_more_tokens():
    started = asyncio.Event()
    released = asyncio.Event()
    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ("data: " + json.dumps(chunk("{", name="propose_operation")) + "\n\n").encode()
            started.set()
            await released.wait()
            yield b"data: [DONE]\n\n"

        async def aclose(self):
            closed.set()

    client = AsyncOpenAI(
        api_key="fixture-not-real",
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=Stream()
                )
            )
        ),
    )
    adapter = Interpreter("fixture-not-real", client=client)
    task = asyncio.create_task(adapter.interpret("Find blue cartons", None, []))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    await adapter.close()
