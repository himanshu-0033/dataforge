import asyncio

import pytest
from pickmate.domain.controller import Controller
from pickmate.storage.database import Database


async def ready(c, sid, text="Find six blue cartons"):
    await c.turn(sid, text)
    await c.wait_idle()
    return await c.snapshot(sid)


async def test_confirmed_pick_is_atomic_and_retry_safe(app):
    sid, _ = await app.create_session("fixture")
    s = await ready(app, sid)
    assert s["task"]["item"]["sku"] == "CT-BLU"
    assert s["task"]["quantity"] == 6
    await app.turn(sid, "I picked them")
    await app.turn(sid, "Yes")
    assert (await app.snapshot(sid))["history"] == []
    await app.turn(sid, "Confirm six blue cartons")
    await app.turn(sid, "Confirm six blue cartons")
    s = await app.snapshot(sid)
    assert len(s["history"]) == 1
    assert next(i for i in s["inventory"] if i["sku"] == "CT-BLU")["available"] == 34


async def test_late_lookup_ignoring_cancellation_cannot_replace_correction(app):
    sid, _ = await app.create_session("fixture")
    await app.faults(sid, lookup_delay_ms=80, ignore_cancellation=True)
    await app.turn(sid, "Find six blue cartons")
    await asyncio.sleep(0.01)
    await app.faults(sid, lookup_delay_ms=0)
    await app.turn(sid, "Wait, make that four red cartons")
    await app.wait_idle()
    s = await app.snapshot(sid)
    assert s["task"]["item"]["sku"] == "CT-RED"
    assert s["task"]["task_version"] == 2
    assert "red cartons" in s["speech"]["text"].lower()
    assert any(e["type"] == "stale_result_rejected" for e in s["events"])
    await app.turn(sid, "Confirm four red cartons")
    s = await app.snapshot(sid)
    assert [(p["sku"], p["quantity"]) for p in s["history"]] == [("CT-RED", 4)]


async def test_status_retains_current_lookup(app):
    sid, _ = await app.create_session("fixture")
    await app.faults(sid, lookup_delay_ms=50)
    await app.turn(sid, "Find six blue cartons")
    await app.turn(sid, "What are we picking?")
    await app.wait_idle()
    s = await app.snapshot(sid)
    assert s["task"]["status"] == "ready"
    assert s["task"]["task_version"] == 1
    assert s["speech"]["response_epoch"] == s["response_epoch"]


async def test_interrupted_confirmation_and_stale_playback_cannot_authorize(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    await app.turn(sid, "I picked them")
    old = (await app.snapshot(sid))["speech"]
    await app.playback(sid, old["response_id"], "playing", trusted=True)
    await app.speech_onset(sid)
    await app.playback(sid, old["response_id"], "completed", trusted=True)
    await app.turn(sid, "Yes")
    assert not (await app.snapshot(sid))["history"]


async def test_delivered_current_question_allows_yes(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    await app.turn(sid, "I picked them")
    s = await app.snapshot(sid)
    await app.playback(sid, s["speech"]["response_id"], "playing", trusted=True)
    await app.playback(sid, s["speech"]["response_id"], "completed", trusted=True)
    await app.turn(sid, "Yes")
    assert len((await app.snapshot(sid))["history"]) == 1


async def test_restart_keeps_committed_outcome_and_owner(app):
    sid, token = await app.create_session("fixture")
    await ready(app, sid)
    await app.turn(sid, "Confirm six blue cartons")
    other = Controller(Database(app.db.path))
    await other.initialize()
    assert await other.authorize(sid, token)
    await other.control(sid, "recover")
    await other.turn(sid, "I picked them")
    assert len((await other.snapshot(sid))["history"]) == 1
    await other.close()


@pytest.mark.parametrize(
    "text",
    [
        "Find negative six blue cartons",
        "Find zero blue cartons",
        "Find 10001 blue cartons",
        "Find six cartons",
        "Find two unicorns",
        "Find six green cartons",
        "Find four yellow cartons",
    ],
)
async def test_invalid_or_unavailable_pick_never_writes(app, text):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid, text)
    await app.turn(sid, "Yes")
    s = await app.snapshot(sid)
    assert not s["history"]
    assert not s["task"] or s["task"]["status"] != "committed"


async def test_end_fences_callbacks_and_sessions_are_isolated(app):
    a, _ = await app.create_session("fixture")
    b, _ = await app.create_session("fixture")
    await app.faults(a, lookup_delay_ms=30, ignore_cancellation=True)
    await app.turn(a, "Find six blue cartons")
    await app.control(a, "end")
    await app.wait_idle()
    assert (await app.snapshot(a))["ended"]
    assert (await app.snapshot(b))["task"] is None
    assert not (await app.snapshot(a))["history"]


async def test_pause_holds_result_and_false_interruption_preserves_task(app):
    sid, _ = await app.create_session("fixture")
    await app.faults(sid, lookup_delay_ms=30)
    await app.turn(sid, "Find six blue cartons")
    await app.control(sid, "pause")
    await app.wait_idle()
    s = await app.snapshot(sid)
    assert s["paused"] and s["task"]["status"] == "ready"
    await app.control(sid, "resume")
    await app.speech_onset(sid)
    await app.false_interruption(sid)
    s = await app.snapshot(sid)
    assert s["task"]["task_version"] == 1
    assert "blue cartons" in s["speech"]["text"].lower()
