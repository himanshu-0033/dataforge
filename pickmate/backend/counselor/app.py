"""Authenticated counselor sessions and the shared LiveKit voice bridge."""

import asyncio
import contextlib
import hmac
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pickmate.api.app import Metric, Playback, Provider, ProviderError, WorkerClaim
from pickmate.config import Settings
from pickmate.voice.dispatch import Dispatcher
from pydantic import BaseModel, Field

from .conversation import Conversation
from .sessions import Sessions


class Create(BaseModel):
    mode: Literal["live", "text"] = "live"


class Turn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    event_id: str = Field(min_length=1, max_length=100)


class Control(BaseModel):
    action: Literal["pause", "resume", "repeat", "interrupt", "retry", "recover", "end"]


def create_app(settings=None, sessions=None, dispatcher=None):
    cfg = settings or Settings()
    store = sessions or Sessions(Conversation(cfg) if cfg.groq_api_key else None)
    dispatch = dispatcher or Dispatcher(cfg, agent_name="heard")

    async def expire():
        while True:
            await asyncio.sleep(60)
            store.expire()

    @asynccontextmanager
    async def lifespan(app):
        cleanup = asyncio.create_task(expire())
        yield
        cleanup.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup
        await store.close()

    app = FastAPI(title="Heard - AI support", lifespan=lifespan)
    app.state.sessions = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.web_origin, "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def worker(sid, request, claim=False):
        if not cfg.worker_secret or not hmac.compare_digest(
            request.headers.get("x-worker-key", ""), cfg.worker_secret
        ):
            raise HTTPException(403, "Worker authentication required.")
        session = store.get(sid)
        if session.mode != "live" or request.headers.get("x-room-name") != session.room:
            raise HTTPException(403, "Worker room does not match this session.")
        lease = request.headers.get("x-worker-epoch")
        if not claim or lease is not None:
            if not session.worker_epoch or lease != str(session.worker_epoch):
                raise HTTPException(409, "Worker lease was superseded.")
            session.worker_seen = time.monotonic()
        return session

    @app.get("/api/health")
    async def health():
        return dict(
            product="counselor",
            name="Heard",
            mode="live",
            live_ready=not cfg.missing(),
            conversation_ready=store.conversation is not None,
            missing_config=cfg.missing(),
            transcript_retention="memory_only_until_end_or_one_hour_idle",
        )

    @app.post("/api/sessions")
    async def create(body: Create):
        if store.conversation is None:
            raise HTTPException(503, "The conversation service needs configuration.")
        if body.mode == "live" and cfg.missing():
            raise HTTPException(503, "Voice isn't ready yet. You can start a text conversation.")
        session, token = store.create(body.mode)
        return dict(session_id=session.session_id, token=token, snapshot=store.snapshot(session))

    @app.get("/api/sessions/{sid}")
    async def snapshot(sid: str, authorization: str | None = Header(default=None)):
        return store.snapshot(store.authorize(sid, authorization))

    @app.post("/api/sessions/{sid}/turn", status_code=202)
    async def turn(sid: str, body: Turn, authorization: str | None = Header(default=None)):
        session = store.authorize(sid, authorization)
        if not body.text.strip():
            raise HTTPException(422, "Please enter a message.")
        store.turn(session, body.text.strip(), body.event_id)
        return store.snapshot(session)

    @app.post("/api/sessions/{sid}/control")
    async def control(sid: str, body: Control, authorization: str | None = Header(default=None)):
        session = store.authorize(sid, authorization)
        store.control(session, body.action)
        return store.snapshot(session)

    @app.post("/api/sessions/{sid}/token")
    async def token(sid: str, authorization: str | None = Header(default=None)):
        session = store.authorize(sid, authorization)
        if session.ended or session.mode != "live":
            raise HTTPException(409, "An active voice session is required.")
        try:
            await dispatch.ensure(store.snapshot(session))
        except Exception:
            raise HTTPException(503, "Voice couldn't connect. You can keep typing, or retry voice.") from None
        from livekit import api

        jwt = (
            api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
            .with_identity(f"worker-{sid}")
            .with_ttl(timedelta(minutes=5))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=session.room,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                    can_publish_sources=["microphone"],
                )
            )
            .to_jwt()
        )
        return dict(url=cfg.livekit_url, token=jwt)

    @app.get("/api/internal/sessions/{sid}/snapshot")
    async def internal_snapshot(sid: str, request: Request):
        return store.snapshot(worker(sid, request, claim=True))

    @app.post("/api/internal/sessions/{sid}/claim")
    async def claim(sid: str, body: WorkerClaim, request: Request):
        session = worker(sid, request, claim=True)
        if session.ended:
            raise HTTPException(409, "Session has ended.")
        if session.worker_id != body.worker_id:
            if session.worker_epoch:
                store.cancel(session)
            session.worker_epoch += 1
            session.worker_id = body.worker_id
        session.worker_seen = time.monotonic()
        return dict(worker_epoch=session.worker_epoch)

    @app.post("/api/internal/sessions/{sid}/turn", status_code=202)
    async def internal_turn(sid: str, body: Turn, request: Request):
        session = worker(sid, request)
        if body.text.strip() and not session.paused:
            store.turn(session, body.text.strip(), body.event_id)
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/onset")
    async def onset(sid: str, request: Request):
        store.onset(worker(sid, request))
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/false-interruption")
    async def false_interruption(sid: str, request: Request):
        store.false_interruption(worker(sid, request))
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/playback")
    async def playback(sid: str, body: Playback, request: Request):
        store.playback(worker(sid, request), body.response_id, body.status)
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/provider")
    async def provider(sid: str, body: Provider, request: Request):
        session = worker(sid, request)
        session.provider = body.model_dump(exclude_none=True)
        session.revision += 1
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/recover")
    async def recover(sid: str, request: Request):
        store.control(worker(sid, request), "recover")
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/metrics")
    async def metrics(sid: str, body: Metric, request: Request):
        worker(sid, request)
        # Do not persist provider transcripts or diagnostics containing conversation text.
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/error")
    async def provider_error(sid: str, body: ProviderError, request: Request):
        session = worker(sid, request)
        session.provider["status"] = "failed"
        session.revision += 1
        return {"accepted": True}

    return app


app = create_app()
