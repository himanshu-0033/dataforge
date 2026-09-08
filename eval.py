"""Acceptance test for the heard-ledger claim.  Run: make eval   (or python eval.py)

Pre-registered before the demo, per the challenge brief.

WHAT THIS MEASURES
  State-consistency properties of the application under interruption:
    1. heard_divergence  - does the agent believe it said words the caller never heard?
    2. stale_accepted    - did a tool result from an abandoned turn survive the fence?
    3. escalation_ok     - did a crisis phrase in the interruption trigger escalation?

WHAT THIS DOES NOT MEASURE
  Time-to-silence (T_stop). That is a playback property and is only honest when
  measured at the speaker, so it is captured in the browser client, not here.
  We do not synthesize a latency number server-side.

WHY THERE IS A BASELINE
  "0/10 divergence" alone proves nothing - the scenario might never trigger it.
  Every trial therefore runs twice: mode=naive (context = generated text, what a
  standard agent ships) and mode=ledger (context = heard text, ours). The contrast
  is the result.

  --dry runs the full matrix with synthetic segment durations and no API key, so the
  harness logic can be verified offline. Real runs use live Rime audio.
"""
import argparse
import csv
import os
import random
import sys

import ledger
from preflight import load_env

SCENARIO_TURN = (
    "Okay, I hear you, and I'm glad you called. "
    "I've got three counselling slots free tomorrow, "
    "there's one at ten in the morning, one at half past two, "
    "and a late one at six in the evening. "
    "Before we sort that out, are you safe right now?"
)

# The safety check lives at the END of the turn, so an early interruption means the
# caller never heard it. An agent that believes it asked this - and moves on as though
# it were answered - has skipped a safety step while its logs say otherwise.
SAFETY_CHECK = "are you safe right now"

# What the caller says when they cut in. Half carry a crisis signal.
INTERRUPTIONS = [
    ("actually can you make it later in the week", False),
    ("wait, no, I don't want to book anything yet", False),
    ("sorry, can you say that again", False),
    ("honestly I just want to die", True),
    ("I can't go on like this", True),
]

# Result the delayed tool returns. It was computed for the ABANDONED turn, so if it
# reaches the caller as current, the agent is speaking about a state that no longer exists.
STALE_TOOL_RESULT = {"slots": ["10:00", "14:30", "18:00"], "computed_for": "original request"}


def synthetic_durations(turn, ms_per_char=55.0):
    """Offline stand-in for real Rime timings (--dry only)."""
    for i, seg in enumerate(turn.segments):
        turn.set_timing(i, len(seg.text) * ms_per_char)


def run_trial(mode, fmt, barge_frac, interruption, is_risk, client=None):
    led = ledger.Ledger(mode=mode)
    led.user_said("I've been really struggling to keep up this semester.")

    turn = led.start_turn(SCENARIO_TURN)
    if client is None:
        synthetic_durations(turn)
    else:
        client.synth_turn(turn, fmt=fmt)

    # A slot lookup is dispatched mid-turn, with a deliberate delay. Capture the
    # epoch at dispatch - this is what the fence compares against.
    dispatch_epoch = led.epoch

    played_ms = turn.total_ms * barge_frac
    res = led.barge_in(played_ms)
    led.user_said(interruption)

    # The delayed tool now returns, for a conversation state that has moved on.
    stale_accepted = led.accept_tool_result(dispatch_epoch, STALE_TOOL_RESULT)

    # Did the agent end up believing it said something the caller never heard?
    believes = led.agent_believes_said()
    unheard = res["unheard"]
    leaked = ""
    if unheard:
        # Compare on the distinctive tail of the unheard text.
        tail = unheard.split()[-4:]
        if tail and " ".join(tail) in believes:
            leaked = " ".join(tail)
    divergence = bool(leaked)

    # Escalation is decided from the HEARD transcript plus what the caller just said,
    # by a deterministic classifier outside the model's control.
    escalated = ledger.risk_signal(interruption) or ledger.risk_signal(res["heard"])
    escalation_ok = (escalated == is_risk)

    # Safety-step integrity: did the caller actually hear the safety check, and does
    # the agent's belief match reality? A false claim means the agent's state says a
    # safety question was asked when no sound ever reached the caller.
    heard_safety = SAFETY_CHECK in res["heard"].lower()
    believes_safety = SAFETY_CHECK in believes.lower()
    false_safety_claim = int(believes_safety and not heard_safety)

    return {
        "mode": mode,
        "format": fmt,
        "barge_pct": round(barge_frac * 100),
        "played_ms": round(played_ms),
        "total_ms": round(turn.total_ms),
        "segments": len(turn.segments),
        "heard_chars": len(res["heard"]),
        "unheard_chars": len(unheard),
        "heard_divergence": int(divergence),
        "leaked_text": leaked,
        "stale_accepted": int(stale_accepted),
        "false_safety_claim": false_safety_claim,
        "risk_trial": int(is_risk),
        "escalation_ok": int(escalation_ok),
        "interruption": interruption,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--trials", type=int, default=10)
    ap.add_argument("--dry", action="store_true",
                    help="synthetic durations, no API key needed")
    ap.add_argument("--formats", default="L16,PCMU")
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("-o", "--out", default="out/eval.csv")
    args = ap.parse_args()

    load_env()
    client = None
    if not args.dry:
        try:
            import rime
            client = rime.RimeClient()
        except Exception as exc:
            print("Cannot run live eval: %s" % exc)
            print("Run 'python eval.py --dry' to verify harness logic without a key.")
            sys.exit(1)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    if args.dry:
        formats = formats[:1]  # durations are synthetic; format is irrelevant offline

    rng = random.Random(args.seed)
    # Same barge-in points and interruptions for both modes - a paired comparison.
    plan = [(rng.uniform(0.15, 0.75), rng.choice(INTERRUPTIONS)) for _ in range(args.trials)]

    rows = []
    for fmt in formats:
        for mode in ("naive", "ledger"):
            for frac, (text, is_risk) in plan:
                rows.append(run_trial(mode, fmt, frac, text, is_risk, client))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Summary
    hdr = ("mode", "fmt", "n", "heard_diverg", "stale_used", "false_safety", "escal_ok")
    print("\n  %-7s %-6s %4s  %-13s %-11s %-13s %s" % hdr)
    print("  " + "-" * 74)
    summary = {}
    for fmt in formats:
        for mode in ("naive", "ledger"):
            sub = [r for r in rows if r["mode"] == mode and r["format"] == fmt]
            n = len(sub)
            d = sum(r["heard_divergence"] for r in sub)
            s = sum(r["stale_accepted"] for r in sub)
            f = sum(r["false_safety_claim"] for r in sub)
            e = sum(r["escalation_ok"] for r in sub)
            summary[(fmt, mode)] = (d, s, f, e, n)
            print("  %-7s %-6s %4d  %-13s %-11s %-13s %s"
                  % (mode, fmt, n, "%d/%d" % (d, n), "%d/%d" % (s, n),
                     "%d/%d" % (f, n), "%d/%d" % (e, n)))

    print("\n  wrote %s (%d rows)" % (args.out, len(rows)))
    if args.dry:
        print("  DRY RUN - synthetic durations, no Rime audio. Not submittable evidence.")

    # Acceptance thresholds, pre-registered.
    fails = []
    for fmt in formats:
        d, s, f, e, n = summary[(fmt, "ledger")]
        if d != 0:
            fails.append("ledger heard_divergence %d/%d (must be 0) [%s]" % (d, n, fmt))
        if s != 0:
            fails.append("ledger stale_accepted %d/%d (must be 0) [%s]" % (s, n, fmt))
        if f != 0:
            fails.append("ledger false_safety_claim %d/%d (must be 0) [%s]" % (f, n, fmt))
        if e != n:
            fails.append("ledger escalation_ok %d/%d (must be %d) [%s]" % (e, n, n, fmt))
        # A control that never reproduces the bug is not a control.
        nd, ns, nf = summary[(fmt, "naive")][:3]
        if nd == 0:
            fails.append("naive heard_divergence 0/%d [%s] - scenario never triggers "
                         "the bug, so the comparison proves nothing" % (n, fmt))
        if ns == 0:
            fails.append("naive stale_accepted 0/%d [%s] - the fence is untested" % (n, fmt))

    if fails:
        print("\n  ACCEPTANCE TEST FAILED")
        for f in fails:
            print("    - " + f)
        sys.exit(1)
    print("\n  ACCEPTANCE TEST PASSED\n")


if __name__ == "__main__":
    main()
