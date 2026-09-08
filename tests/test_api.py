import json
from datetime import datetime, timezone

import httpx
import jwt
import pytest
from pickmate.api.app import create_app
from pickmate.config import Settings
from pickmate.domain.controller import Controller
from pickmate.storage.database import Database


@pytest.fixture
async def http(tmp_path):
    c = Controller(Database(tmp_path / "api.sqlite"))
    await c.initialize()
    app = create_app(Settings(_env_file=None), c)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, c
    await c.close()


async def test_session_ownership_and_fixture_flow(http):
    client, c = http
    created = (await client.post("/api/sessions", json={"mode": "fixture"})).json()
    route = "/api/sessions/" + created["session_id"]
    auth = {"Authorization": "Bearer " + created["token"]}
    assert (await client.get(route)).status_code == 401
    assert (await client.get(route, headers={"Authorization": "Bearer wrong"})).status_code == 403
    assert (await client.get(route, headers=auth)).json()["provider"]["name"] == "fixture"
    await client.post(
        route + "/turn", headers=auth, json={"text": "Find six blue cartons", "event_id": "first"}
    )
    await c.wait_idle()
    result = (await client.get(route, headers=auth)).json()
    assert result["task"]["item"]["bin"] == "A-03"
    await client.post(
        route + "/turn", headers=auth, json={"text": "Confirm six blue cartons", "event_id": "confirm"}
    )
    await client.post(
        route + "/turn", headers=auth, json={"text": "Confirm six blue cartons", "event_id": "confirm"}
    )
    result = (await client.get(route, headers=auth)).json()
    assert len(result["history"]) == 1
    assert result["history"][0]["quantity"] == 6
    exported = await client.get(route + "/events", headers=auth)
    assert any(json.loads(line)["type"] == "write_committed" for line in exported.text.splitlines())
    await client.post(route + "/control", headers=auth, json={"action": "end"})
    assert (
        await client.post(
            route + "/turn", headers=auth, json={"text": "Find six blue cartons", "event_id": "after"}
        )
    ).status_code == 409


async def test_missing_live_credentials_and_internal_auth(http):
    client, _ = http
    assert (await client.post("/api/sessions", json={"mode": "live"})).status_code == 503
    assert (await client.get("/api/internal/sessions/unknown/snapshot")).status_code == 403
    assert (await client.get("/api/health")).json()["live_ready"] is False


async def test_live_readiness_requires_groq_and_initializes_groq_without_openai(tmp_path, monkeypatch):
    for key in ("GROQ_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    kwargs = dict(
        _env_file=None,
        database_path=str(tmp_path / "groq.sqlite"),
        livekit_url="wss://example.invalid",
        livekit_api_key="test",
        livekit_api_secret="x" * 32,
        worker_secret="y" * 32,
        rime_api_key="test-rime",
        deepgram_api_key="test-stt",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-unused")
    assert Settings(**kwargs).missing() == ["GROQ_API_KEY"]
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("GROQ_API_KEY", "fixture-groq")
    app = create_app(Settings(**kwargs))
    async with app.router.lifespan_context(app):
        assert app.state.controller.interpreter is not None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            health = (await client.get("/api/health")).json()
            assert health["live_ready"] is True and health["missing_config"] == []


async def test_scoped_tokens_and_live_controls_cannot_forge_playback(tmp_path):
    cfg = Settings(
        _env_file=None,
        database_path=str(tmp_path / "live.sqlite"),
        livekit_url="wss://example.invalid",
        livekit_api_key="test",
        livekit_api_secret="x" * 32,
        worker_secret="y" * 32,
        rime_api_key="test-rime",
        deepgram_api_key="test-stt",
        groq_api_key="test-llm",
    )
    c = Controller(Database(cfg.database_path))
    await c.initialize()

    class DispatchFixture:
        async def ensure(self, session):
            assert session["mode"] == "live"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(cfg, c, dispatcher=DispatchFixture())),
        base_url="http://test",
    ) as client:
        session = (await client.post("/api/sessions", json={"mode": "live"})).json()
        route = "/api/sessions/" + session["session_id"]
        auth = {"Authorization": "Bearer " + session["token"]}
        token = (await client.post(route + "/token", headers=auth)).json()["token"]
        payload = jwt.decode(
            token, cfg.livekit_api_secret, algorithms=["HS256"], options={"verify_aud": False}
        )
        assert payload["video"]["room"] == "pickmate-" + session["session_id"]
        assert payload["video"]["canPublishSources"] == ["microphone"]
        assert 0 < payload["exp"] - datetime.now(timezone.utc).timestamp() <= 300
        assert (
            await client.post(
                route + "/playback",
                headers=auth,
                json={"response_id": "old", "status": "completed", "trusted": True},
            )
        ).status_code == 403
        internal = "/api/internal/sessions/" + session["session_id"] + "/snapshot"
        assert (
            await client.get(internal, headers={"X-Worker-Key": cfg.worker_secret, "X-Room-Name": "another"})
        ).status_code == 403
    await c.close()


async def test_faults_disabled_outside_demo(tmp_path):
    c = Controller(Database(tmp_path / "prod.sqlite"))
    await c.initialize()
    sid, token = await c.create_session("fixture")
    app = create_app(Settings(_env_file=None, demo_enabled=False), c)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/api/sessions", json={"mode": "fixture"})).status_code == 403
        r = await client.post(
            f"/api/sessions/{sid}/faults",
            headers={"Authorization": "Bearer " + token},
            json={"lookup_delay_ms": 5000},
        )
        assert r.status_code == 403
    await c.close()
