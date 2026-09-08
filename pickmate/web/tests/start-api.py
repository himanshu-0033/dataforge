"""Run the real counselor API with deterministic replies for browser tests."""

import asyncio
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from counselor.app import create_app  # noqa: E402
from counselor.config import Settings  # noqa: E402
from counselor.sessions import Sessions  # noqa: E402


class TestConversation:
    async def reply(self, history, **kwargs):
        text = history[-1]["content"]
        if text == "Watch the reply arrive":
            kwargs["on_delta"]("A reply is arriving")
            await asyncio.sleep(1)
        await asyncio.sleep(5 if text == "Please wait" else 0.1)
        turns = sum(message["role"] == "user" for message in history)
        if text == "Use my preferences":
            return f"Preference received: {kwargs['support']}; {kwargs['focus']}"
        return f"Test reply {turns}: {text}"

    async def close(self):
        pass


if __name__ == "__main__":
    settings = Settings(
        _env_file=None,
        counselor_provider="groq",
        groq_api_key="",
        livekit_url="",
        livekit_api_key="",
        livekit_api_secret="",
        deepgram_api_key="",
        rime_api_key="",
        worker_secret="",
        web_origin="http://127.0.0.1:4173",
    )
    uvicorn.run(
        create_app(settings, Sessions(TestConversation())), host="127.0.0.1", port=8001, log_level="warning"
    )
