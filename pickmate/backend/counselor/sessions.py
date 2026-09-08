"""Bounded, memory-only sessions. No transcript or raw audio is written to disk."""

import asyncio
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException


def utc():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    mode: str
    owner_hash: str
    session_id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    response_epoch: int = 0
    worker_epoch: int = 0
    worker_id: str = ""
    worker_seen: float = 0
    touched: float = field(default_factory=time.monotonic)
    paused: bool = False
    ended: bool = False
    resolving: bool = False
    user_speaking: bool = False
    resume_query: bool = False
    error: str | None = None
    speech: dict | None = None
    messages: list = field(default_factory=list)
    inputs: set = field(default_factory=set)
    provider: dict = field(default_factory=lambda: {"name": "rime", "status": "awaiting_worker"})
    job: asyncio.Task | None = None

    @property
    def room(self):
        return f"heard-{self.session_id}"


class Sessions:
    def __init__(self, conversation):
        self.conversation = conversation
        self.sessions: dict[str, Session] = {}
        self.jobs: set[asyncio.Task] = set()

    def get(self, sid):
        if sid not in self.sessions:
            raise HTTPException(404, "This conversation has expired. Start a new one.")
        return self.sessions[sid]

    def authorize(self, sid, token):
        session = self.get(sid)
        if not token or not token.startswith("Bearer "):
            raise HTTPException(401, "Session authorization is required.")
        digest = hashlib.sha256(token[7:].encode()).hexdigest()
        if not hmac.compare_digest(digest, session.owner_hash):
            raise HTTPException(403, "This conversation belongs to another browser session.")
        return session

    def create(self, mode):
        self.expire()
        if len(self.sessions) >= 100:
            raise HTTPException(503, "All conversation spaces are occupied. Please try again shortly.")
        token = secrets.token_urlsafe(32)
        session = Session(mode=mode, owner_hash=hashlib.sha256(token.encode()).hexdigest())
        self.sessions[session.session_id] = session
        self.say(
            session,
            "Hi, I'm Heard, an AI here to listen and help you talk things through. What's on your mind today?",
        )
        return session, token

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.jobs.add(task)
        task.add_done_callback(self.jobs.discard)
        return task

    def cancel(self, session):
        session.response_epoch += 1
        if session.job and not session.job.done():
            session.job.cancel()
        session.job = None
        session.resolving = False
        if session.speech and session.speech["status"] in ("queued", "playing"):
            session.speech["status"] = "interrupted"
            for message in session.messages:
                if message["id"] == session.speech["response_id"]:
                    message["status"] = "interrupted"
        session.revision += 1

    def say(self, session, text):
        if session.ended:
            return
        rid = uuid4().hex
        use_audio = (
            session.mode == "live"
            and not session.paused
            and session.provider["status"] not in ("failed", "disconnected")
        )
        status = "queued" if use_audio else "completed"
        session.speech = dict(
            response_id=rid,
            response_epoch=session.response_epoch,
            text=text,
            status=status,
            task_id=None,
            task_version=None,
        )
        session.messages.append(dict(id=rid, role="assistant", text=text, utc=utc(), status=status))
        session.messages = session.messages[-200:]
        session.revision += 1

    def history(self, session):
        return [
            dict(role=m["role"], content=m["text"])
            for m in session.messages
            if m["role"] == "user" or m["status"] == "completed"
        ][-40:]

    def turn(self, session, text, event_id):
        if session.ended:
            raise HTTPException(409, "This conversation has ended.")
        if event_id in session.inputs:
            return
        if len(session.inputs) >= 1000:
            raise HTTPException(409, "Please start a new conversation to continue.")
        session.inputs.add(event_id)
        self.cancel(session)
        session.user_speaking = False
        session.resume_query = False
        session.error = None
        session.touched = time.monotonic()
        session.messages.append(dict(id=event_id, role="user", text=text, utc=utc(), status="completed"))
        session.messages = session.messages[-200:]
        self.generate(session)

    def generate(self, session):
        session.resolving = True
        session.revision += 1
        session.job = self.spawn(self._reply(session, session.response_epoch, self.history(session)))

    async def _reply(self, session, epoch, history):
        try:
            async with asyncio.timeout(30):
                reply = await self.conversation.reply(history)
            if session.ended or epoch != session.response_epoch:
                return
            session.resolving = False
            session.resume_query = False
            self.say(session, reply)
        except asyncio.CancelledError:
            pass
        except Exception:
            if epoch == session.response_epoch and not session.ended:
                session.resolving = False
                session.error = "The reply couldn't be completed. Please retry your last message."
                session.revision += 1

    def onset(self, session):
        if session.ended or session.paused:
            return
        session.resume_query = session.resume_query or session.resolving
        self.cancel(session)
        session.user_speaking = True

    def false_interruption(self, session):
        if session.ended or not session.user_speaking:
            return
        session.user_speaking = False
        session.revision += 1
        if session.resume_query:
            session.resume_query = False
            self.generate(session)
        elif session.speech and session.speech["status"] == "interrupted":
            self.say(session, session.speech["text"])

    def playback(self, session, rid, status):
        if session.ended or not session.speech or session.speech["response_id"] != rid:
            return
        if session.speech["response_epoch"] != session.response_epoch:
            return
        old = session.speech["status"]
        if old in ("completed", "interrupted"):
            return
        session.speech["status"] = status
        for message in session.messages:
            if message["id"] == rid:
                message["status"] = status
        session.revision += 1

    def control(self, session, action):
        if action == "end":
            self.cancel(session)
            session.ended = True
            session.messages.clear()
            session.inputs.clear()
            session.speech = None
            session.error = None
            session.resume_query = False
            session.user_speaking = False
            return
        if session.ended:
            raise HTTPException(409, "This conversation has ended.")
        session.touched = time.monotonic()
        if action == "pause":
            session.resume_query = session.resolving
            self.cancel(session)
            session.user_speaking = False
            session.paused = True
        elif action == "resume":
            session.paused = False
            if session.resume_query:
                session.resume_query = False
                self.generate(session)
        elif action == "interrupt":
            self.cancel(session)
            session.resume_query = False
            session.user_speaking = False
        elif action == "repeat":
            last = next((m for m in reversed(session.messages) if m["role"] == "assistant"), None)
            if last:
                self.cancel(session)
                self.say(session, last["text"])
        elif action == "retry":
            self.cancel(session)
            session.error = None
            if any(m["role"] == "user" for m in session.messages):
                self.generate(session)
        elif action == "recover":
            session.error = None
            if session.speech and session.speech["status"] == "interrupted" and not session.resolving:
                text = session.speech["text"]
                self.cancel(session)
                self.say(session, text)
        session.revision += 1

    def snapshot(self, session):
        provider = dict(session.provider)
        if session.mode == "live" and provider["status"] in ("connected", "active"):
            if time.monotonic() - session.worker_seen > 15:
                provider["status"] = "disconnected"
                session.provider["status"] = "disconnected"
                session.revision += 1
        return dict(
            session_id=session.session_id,
            revision=session.revision,
            mode=session.mode,
            room=session.room,
            ended=session.ended,
            paused=session.paused,
            resolving=session.resolving or session.user_speaking,
            thinking=session.resolving,
            user_speaking=session.user_speaking,
            response_epoch=session.response_epoch,
            worker_epoch=session.worker_epoch,
            speech=session.speech,
            provider=provider,
            messages=session.messages,
            error=session.error,
            task=None,
            inventory=[],
        )

    def expire(self):
        for sid, session in list(self.sessions.items()):
            if time.monotonic() - session.touched > 3600:
                self.control(session, "end")
                del self.sessions[sid]

    async def close(self):
        for session in self.sessions.values():
            self.control(session, "end")
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        self.sessions.clear()
        if self.conversation:
            await self.conversation.close()
