import asyncio

import pytest
from pickmate.domain.controller import Controller
from pickmate.domain.models import Intent
from pickmate.storage.database import Database
from test_workflow import ready


async def test_old_model_operation_after_correction_is_rejected(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    old = await app.snapshot(sid)
    await ready(app, sid, "Wait make that four red cartons")
    await app.accept_intent(
        sid,
        Intent(action="confirm", explicit=True, query="blue cartons", quantity=6),
        "Confirm six blue cartons",
        old["input_id"],
        old["response_epoch"],
    )
    s = await app.snapshot(sid)
    assert not s["history"]
    assert s["task"]["item"]["sku"] == "CT-RED"
    assert any(e["type"] == "stale_result_rejected" and e["data"]["source"] == "llm" for e in s["events"])


@pytest.mark.parametrize("action", ["cancel", "correction"])
async def test_control_wins_before_old_write_attempt(app, action):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    old = await app.snapshot(sid)
    if action == "cancel":
        await app.control(sid, "cancel")
    else:
        await ready(app, sid, "Wait make that four red cartons")
    await app.accept_intent(
        sid, Intent(action="confirm"), "Confirm six blue cartons", old["input_id"], old["response_epoch"]
    )
    assert not (await app.snapshot(sid))["history"]


async def test_commit_wins_before_cancel_or_interrupted_receipt(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    await app.turn(sid, "Confirm six blue cartons")
    await app.speech_onset(sid)
    await app.control(sid, "cancel")
    s = await app.snapshot(sid)
    assert len(s["history"]) == 1
    assert s["task"]["status"] == "committed"
    assert "recorded" in s["speech"]["text"].lower()


async def test_concurrent_confirms_decrement_once(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    await asyncio.gather(
        *(app.turn(sid, "Confirm six blue cartons", f"retry-{i}") for i in range(10)), return_exceptions=True
    )
    s = await app.snapshot(sid)
    assert len(s["history"]) == 1
    assert next(i["available"] for i in s["inventory"] if i["sku"] == "CT-BLU") == 34


async def test_current_question_expires(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    await app.turn(sid, "I picked them")
    s = await app.snapshot(sid)
    await app.playback(sid, s["speech"]["response_id"], "playing", trusted=True)
    await app.playback(sid, s["speech"]["response_id"], "completed", trusted=True)
    await app.db.change(sid, lambda s, c, e: setattr(s.confirmation, "expires_at", 1))
    await app.turn(sid, "Yes")
    assert not (await app.snapshot(sid))["history"]


@pytest.mark.parametrize("provider", ["rime", "stt", "llm", "lookup"])
async def test_dependency_failure_preserves_state_and_recovery(app, provider):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    await app.faults(sid, fail_provider=provider)
    if provider == "lookup":
        await ready(app, sid, "Find four red cartons")
    elif provider != "rime":
        await app.turn(sid, "Confirm six blue cartons")
    s = await app.snapshot(sid)
    assert not s["history"]
    assert any(e["type"] == "provider_error" for e in s["events"])
    await app.faults(sid, fail_provider=None)
    await app.control(sid, "recover")
    await ready(app, sid, "Find four red cartons")
    await app.turn(sid, "Confirm four red cartons")
    assert (await app.snapshot(sid))["history"][0]["sku"] == "CT-RED"


async def test_simultaneous_sessions_recheck_stock_inside_commit(app):
    a, _ = await app.create_session("fixture")
    b, _ = await app.create_session("fixture")
    await ready(app, a, "Find twenty red cartons")
    await ready(app, b, "Find twenty red cartons")
    await asyncio.gather(app.turn(a, "Confirm twenty red cartons"), app.turn(b, "Confirm twenty red cartons"))
    sa, sb = await app.snapshot(a), await app.snapshot(b)
    assert len(sa["history"]) + len(sb["history"]) == 1
    assert next(i["available"] for i in sa["inventory"] if i["sku"] == "CT-RED") == 12


async def test_unknown_or_partial_confirm_cannot_be_upgraded_by_model(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    s = await app.snapshot(sid)
    await app.accept_intent(
        sid,
        Intent(action="confirm", explicit=True, query="blue cartons", quantity=6),
        "maybe confirm six",
        s["input_id"],
        s["response_epoch"],
    )
    assert not (await app.snapshot(sid))["history"]


async def test_restart_drops_unheard_confirmation(tmp_path):
    c = Controller(Database(tmp_path / "restart.sqlite"))
    await c.initialize()
    sid, _ = await c.create_session("fixture")
    await ready(c, sid)
    await c.turn(sid, "I picked them")
    s = await c.snapshot(sid)
    await c.playback(sid, s["speech"]["response_id"], "playing", trusted=True)
    await c.playback(sid, s["speech"]["response_id"], "completed", trusted=True)
    await c.close()
    c = Controller(Database(tmp_path / "restart.sqlite"))
    await c.initialize()
    await c.control(sid, "recover")
    await c.turn(sid, "Yes")
    assert not (await c.snapshot(sid))["history"]
    await c.close()


async def test_new_speech_onset_fences_pending_confirmation_before_final_transcript(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid)
    old = await app.snapshot(sid)
    await app.speech_onset(sid)
    await app.accept_intent(
        sid,
        Intent(action="confirm", explicit=True, quantity=6, query="blue cartons"),
        "Confirm six blue cartons",
        old["input_id"],
        old["response_epoch"],
    )
    s = await app.snapshot(sid)
    assert s["history"] == []
    assert s["resolving"] is True
    assert s["task"]["status"] == "ready"


async def test_decimal_confirmation_cannot_merge_digits_into_different_quantity(app):
    sid, _ = await app.create_session("fixture")
    await ready(app, sid, "Find ten red cartons")
    s = await app.snapshot(sid)
    await app.accept_intent(
        sid,
        Intent(action="confirm", explicit=True, quantity=10, query="red cartons"),
        "Confirm 1.0 red cartons",
        s["input_id"],
        s["response_epoch"],
    )
    assert not (await app.snapshot(sid))["history"]
