"""Natural conversation, with application-owned and interruption-aware history."""

from openai import AsyncOpenAI

from .config import GROQ_BASE_URL
from .context import build_messages
from .dialogue import connection_reply
from .vertex import VertexConversation


class GroqConversation:
    def __init__(self, settings):
        self.model = settings.llm_model
        self.client = AsyncOpenAI(
            api_key=settings.groq_api_key, base_url=GROQ_BASE_URL, timeout=20, max_retries=0
        )

    async def reply(self, messages, *, on_delta=None):
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.6,
            max_completion_tokens=2048,
            stream=True,
        )
        chunks = []
        finish = None
        try:
            async for chunk in stream:
                if chunk.choices:
                    choice = chunk.choices[0]
                    finish = choice.finish_reason or finish
                    if choice.delta.content:
                        chunks.append(choice.delta.content)
                        if on_delta:
                            on_delta(choice.delta.content)
        finally:
            await stream.close()
        text = "".join(chunks).strip()
        if not text or finish != "stop":
            raise ValueError("Incomplete conversation response")
        return text

    async def close(self):
        await self.client.close()


class Conversation:
    def __init__(self, settings):
        self.provider = settings.counselor_provider
        self.backend = (
            VertexConversation(settings) if self.provider == "vertex" else GroqConversation(settings)
        )
        self.model = self.backend.model

    async def reply(self, messages, *, support="explore", mode="text", focus="", on_delta=None):
        acknowledgement = connection_reply(messages, mode)
        if acknowledgement:
            return acknowledgement
        context = build_messages(messages, support=support, mode=mode, focus=focus)
        return await self.backend.reply(context, on_delta=on_delta)

    async def close(self):
        await self.backend.close()
