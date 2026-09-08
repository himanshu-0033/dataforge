import hmac
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pickmate.config import Settings
from pickmate.domain.controller import Controller
from pickmate.domain.models import Faults
from pickmate.storage.database import Database, SupersededWorker, worker_lease
from pickmate.voice.dispatch import Dispatcher
from pydantic import BaseModel, ConfigDict, Field


class CreateSession(BaseModel):
    mode: Literal["fixture", "live"] = "fixture"


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    event_id: str = Field(min_length=1, max_length=100)


class Control(BaseModel):
    action: Literal["pause", "resume", "cancel", "end", "recover", "repeat"]


class Playback(BaseModel):
    response_id: str = Field(max_length=100)
    status: Literal["playing", "completed", "interrupted"]
    trusted: bool = False


class Provider(BaseModel):
    name: Literal["rime"] = "rime"
    status: Literal["connected", "active", "failed", "disconnected"]
    model: str | None = None
    speaker: str | None = None
    language: str | None = None
    endpoint: str | None = None
    error_category: str | None = None


class Metric(BaseModel):
    type: str = Field(max_length=100)
    data: dict = Field(default_factory=dict)


class ProviderError(BaseModel):
    provider: Literal["stt", "llm", "rime"]
    category: str = Field(max_length=100)


class WorkerClaim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)


def create_app(settings=None, controller=None, dispatcher=None):
    cfg = settings or Settings()
    c = controller or Controller(Database(cfg.database_path))
    dispatch = dispatcher or Dispatcher(cfg)

    @asynccontextmanager
    async def lifespan(app):
        if not controller and cfg.openai_api_key:
            from pickmate.voice.interpreter import Interpreter

            c.interpreter = Interpreter(cfg.openai_api_key, cfg.llm_model)
        await c.initialize()
        yield
        await c.close()

    app = FastAPI(title="PickMate", version="0.1.0", lifespan=lifespan)
    app.state.controller = c

    @app.middleware("http")
    async def isolate_worker_lease(request, call_next):
        lease_token = worker_lease.set(None)
        try:
            return await call_next(request)
        finally:
            worker_lease.reset(lease_token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cfg.web_origin, "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": "Session not found."})

    @app.exception_handler(SupersededWorker)
    async def stale_worker(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": "Worker lease was superseded."})

    async def owner(sid, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Session authorization required.")
        if not await c.authorize(sid, authorization[7:]):
            raise HTTPException(403, "This session belongs to another worker.")

    async def worker(sid, request, require_lease=True):
        supplied = request.headers.get("x-worker-key", "")
        if not cfg.worker_secret or not hmac.compare_digest(supplied, cfg.worker_secret):
            raise HTTPException(403, "Worker authentication required.")
        snapshot = await c.snapshot(sid)
        if snapshot["mode"] != "live" or request.headers.get("x-room-name") != snapshot["room"]:
            raise HTTPException(403, "Worker room does not match session.")
        supplied_epoch = request.headers.get("x-worker-epoch")
        if require_lease or supplied_epoch is not None:
            if supplied_epoch != str(snapshot["worker_epoch"]) or not snapshot["worker_epoch"]:
                raise HTTPException(409, "Worker lease was superseded.")
            worker_lease.set((sid, snapshot["worker_epoch"]))

    @app.get("/api/health")
    async def health():
        return dict(
            mode=cfg.app_mode,
            live_ready=not cfg.missing(),
            missing_config=cfg.missing(),
            demo_enabled=cfg.demo_enabled,
        )

    @app.post("/api/sessions")
    async def create(body: CreateSession):
        if body.mode == "live" and cfg.missing():
            raise HTTPException(503, f"Live voice needs server configuration: {', '.join(cfg.missing())}.")
        if body.mode == "fixture" and not cfg.demo_enabled:
            raise HTTPException(403, "Fixture sessions are disabled on this server.")
        sid, token = await c.create_session(body.mode)
        return dict(session_id=sid, token=token, snapshot=await c.snapshot(sid))

    @app.get("/api/sessions/{sid}")
    async def snapshot(sid: str, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        return await c.snapshot(sid)

    @app.get("/api/sessions/{sid}/events")
    async def events(sid: str, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        import json

        from fastapi.responses import Response

        return Response(
            "\n".join(json.dumps(e) for e in await c.db.export_events(sid)) + "\n",
            media_type="application/x-ndjson",
        )

    @app.post("/api/sessions/{sid}/turn", status_code=202)
    async def turn(sid: str, body: Turn, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        s = await c.snapshot(sid)
        if s["mode"] != "fixture":
            raise HTTPException(403, "Use the LiveKit microphone for live turns.")
        if s["ended"]:
            raise HTTPException(409, "Session has ended. Start another session.")
        await c.turn(sid, body.text, body.event_id)
        return await c.snapshot(sid)

    @app.post("/api/sessions/{sid}/control")
    async def control(sid: str, body: Control, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        await c.control(sid, body.action)
        return await c.snapshot(sid)

    @app.post("/api/sessions/{sid}/playback")
    async def playback(sid: str, body: Playback, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        if (await c.snapshot(sid))["mode"] != "fixture":
            raise HTTPException(403, "Live playback estimates come from the voice worker.")
        await c.playback(sid, body.response_id, body.status, trusted=True)
        return await c.snapshot(sid)

    @app.post("/api/sessions/{sid}/faults")
    async def faults(sid: str, body: Faults, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        if not cfg.demo_enabled:
            raise HTTPException(403, "Fault injection is disabled.")
        await c.faults(sid, **body.model_dump())
        return await c.snapshot(sid)

    @app.post("/api/sessions/{sid}/token")
    async def token(sid: str, authorization: str | None = Header(default=None)):
        await owner(sid, authorization)
        s = await c.snapshot(sid)
        if s["ended"] or s["mode"] != "live":
            raise HTTPException(409, "An active live session is required.")
        try:
            await dispatch.ensure(s)
        except Exception:
            raise HTTPException(
                503, "LiveKit room setup failed. Check server credentials and retry."
            ) from None
        from livekit import api

        jwt = (
            api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
            .with_identity(f"worker-{sid}")
            .with_ttl(timedelta(minutes=5))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=s["room"],
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,
                    can_publish_sources=["microphone"],
                )
            )
            .to_jwt()
        )
        return dict(url=cfg.livekit_url, token=jwt, room=s["room"])

    @app.get("/api/internal/sessions/{sid}/snapshot")
    async def internal_snapshot(sid: str, request: Request):
        await worker(sid, request, require_lease=False)
        return await c.snapshot(sid)

    @app.post("/api/internal/sessions/{sid}/claim")
    async def claim(sid: str, body: WorkerClaim, request: Request):
        await worker(sid, request, require_lease=False)
        if (await c.snapshot(sid))["ended"]:
            raise HTTPException(409, "Session has ended.")
        return await c.claim_worker(sid, body.worker_id)

    @app.post("/api/internal/sessions/{sid}/turn", status_code=202)
    async def internal_turn(sid: str, body: Turn, request: Request):
        await worker(sid, request)
        c.spawn(c.turn(sid, body.text, body.event_id))
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/onset")
    async def onset(sid: str, request: Request):
        await worker(sid, request)
        await c.speech_onset(sid)
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/false-interruption")
    async def false_interrupt(sid: str, request: Request):
        await worker(sid, request)
        await c.false_interruption(sid)
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/playback")
    async def internal_playback(sid: str, body: Playback, request: Request):
        await worker(sid, request)
        await c.playback(sid, body.response_id, body.status, trusted=False)
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/provider")
    async def provider(sid: str, body: Provider, request: Request):
        await worker(sid, request)
        await c.provider(sid, body.model_dump(exclude_none=True))
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/recover")
    async def recover(sid: str, request: Request):
        await worker(sid, request)
        await c.control(sid, "recover")
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/metrics")
    async def metrics(sid: str, body: Metric, request: Request):
        await worker(sid, request)
        await c.metric(sid, "worker_" + body.type, body.data)
        return {"accepted": True}

    @app.post("/api/internal/sessions/{sid}/error")
    async def provider_error(sid: str, body: ProviderError, request: Request):
        await worker(sid, request)
        await c.provider_error(sid, body.provider, body.category)
        return {"accepted": True}

    return app


app = create_app()
