"""Vertex Gemini streaming with renewable, server-side Application Default Credentials."""

import asyncio
import json
from functools import partial
from threading import Lock

import httpx


class VertexConversation:
    def __init__(self, settings, *, client=None, credentials=None):
        self.model = settings.vertex_model
        self.project = settings.vertex_project
        self.location = settings.google_cloud_location
        self.thinking_level = settings.vertex_thinking_level
        host = (
            "aiplatform.googleapis.com"
            if self.location == "global"
            else (f"{self.location}-aiplatform.googleapis.com")
        )
        self.url = (
            f"https://{host}/v1/projects/{self.project}/locations/{self.location}"
            f"/publishers/google/models/{self.model}:streamGenerateContent?alt=sse"
        )
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(45, connect=10))
        self.credentials = credentials
        self.credential_info = settings.service_account_info()
        self.auth_lock = Lock()

    def _headers(self):
        # Refresh in a thread. The lock also protects a refresh that outlives a
        # cancelled reply; access tokens are never cached in settings or the UI.
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        with self.auth_lock:
            if self.credentials is None:
                scopes = ["https://www.googleapis.com/auth/cloud-platform"]
                if self.credential_info:
                    self.credentials = service_account.Credentials.from_service_account_info(
                        self.credential_info, scopes=scopes, quota_project_id=self.project
                    )
                    self.credential_info = None
                else:
                    self.credentials, _ = google.auth.default(scopes=scopes, quota_project_id=self.project)
            headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
            self.credentials.before_request(partial(Request(), timeout=10), "POST", self.url, headers)
            return headers

    async def reply(self, messages, *, on_delta=None):
        contents = []
        system = []
        for message in messages:
            if message["role"] == "system":
                system.append({"text": message["content"]})
                continue
            role = "model" if message["role"] == "assistant" else "user"
            part = {"text": message["content"]}
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": role, "parts": [part]})
        payload = {
            "systemInstruction": {"parts": system},
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": 8192,
                "thinkingConfig": {"thinkingLevel": self.thinking_level, "includeThoughts": False},
            },
        }
        chunks = []
        finish = None

        def consume(event):
            nonlocal finish
            data = json.loads(event)
            candidates = data.get("candidates", [])
            if not candidates:
                return
            candidate = candidates[0]
            finish = candidate.get("finishReason", finish)
            for part in candidate.get("content", {}).get("parts", []):
                text = part.get("text")
                if isinstance(text, str) and text and not part.get("thought"):
                    chunks.append(text)
                    if on_delta:
                        on_delta(text)

        headers = await asyncio.to_thread(self._headers)
        async with self.client.stream("POST", self.url, headers=headers, json=payload) as response:
            response.raise_for_status()
            event = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    event.append(line[5:].lstrip())
                elif not line and event:
                    consume("\n".join(event))
                    event = []
            if event:
                consume("\n".join(event))
        text = "".join(chunks).strip()
        if not text or finish != "STOP":
            raise ValueError("Incomplete conversation response")
        return text

    async def close(self):
        await self.client.aclose()
