"""Actual controller/SQLite corpus. No audio or provider latency is simulated as evidence."""

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pickmate.domain.controller import Controller
from pickmate.storage.database import Database


async def trial(index, output):
    with tempfile.TemporaryDirectory(prefix="pickmate-stress-") as directory:
        c = Controller(Database(Path(directory) / "trial.sqlite"))
        await c.initialize()
        sid, _ = await c.create_session("fixture")
        delay = 5000 if index in (1, 2) else 80 + index
        ignores = index % 2 == 1
        await c.faults(sid, lookup_delay_ms=delay, ignore_cancellation=ignores)
        await c.turn(sid, "Find six blue cartons", event_id="initial")
        await asyncio.sleep(0.02)
        await c.speech_onset(sid)
        await c.faults(sid, lookup_delay_ms=0)
        await c.turn(sid, "Wait make that four red cartons", event_id="correction")
        await c.wait_idle()
        await c.turn(sid, "I picked them", event_id="complete")
        await c.turn(sid, "Confirm four red cartons", event_id="confirm")
        await c.turn(sid, "Confirm four red cartons", event_id="confirm")
        await c.control(sid, "recover")
        await c.turn(sid, "I picked them", event_id="reconnect")
        snapshot = await c.snapshot(sid)
        events = await c.db.export_events(sid)
        corrected = next(
            e["seq"] for e in events if e["type"] == "task_version_changed" and e["task_version"] == 2
        )
        leaked = [
            e
            for e in events
            if e["seq"] > corrected and e["type"] == "speech_queued" and e["task_version"] != 2
        ]
        picks = snapshot["history"]
        inventory = {i["sku"]: i["available"] for i in snapshot["inventory"]}
        ok = (
            len(picks) == 1
            and picks[0]["sku"] == "CT-RED"
            and picks[0]["quantity"] == 4
            and inventory["CT-BLU"] == 40
            and inventory["CT-RED"] == 28
            and not leaked
        )
        folder = output / f"trial-{index:02}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        (folder / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        row = dict(
            trial=index,
            mode="fixture",
            passed=ok,
            lookup_delay_ms=delay,
            ignores_cancellation=ignores,
            corrected_task_success=ok,
            stale_instruction_leaks=len(leaked),
            stale_results_rejected=sum(e["type"] == "stale_result_rejected" for e in events),
            duplicate_writes=max(0, len(picks) - 1),
            commits=len(picks),
            audio_trials=0,
            events=f"trial-{index:02}/events.jsonl",
            snapshot=f"trial-{index:02}/snapshot.json",
        )
        await c.close()
        return row


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(6)

    async def run(index):
        async with gate:
            return await trial(index, args.output)

    rows = await asyncio.gather(*(run(i) for i in range(1, args.trials + 1)))
    (args.output / "trials.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    record = dict(
        utc=datetime.now(timezone.utc).isoformat(),
        mode="fixture",
        count=len(rows),
        passed=sum(r["passed"] for r in rows),
        failed=sum(not r["passed"] for r in rows),
        audio_trials=0,
        physical_barge_in="unverified",
        quantile_method="nearest-rank; no audio samples",
        delayed_lookup_trials=[r["trial"] for r in rows if r["lookup_delay_ms"] == 5000],
    )
    (args.output / "summary.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    return int(record["failed"] > 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("evidence/stress"))
    args = parser.parse_args()
    if not 1 <= args.trials <= 100:
        parser.error("--trials must be between 1 and 100")
    raise SystemExit(asyncio.run(main(args)))
