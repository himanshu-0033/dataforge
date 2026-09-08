# Rime evidence

Pre-registered **before** the demo was recorded, per the challenge brief.
Committed with results blank; filled in from `out/eval.csv` after the run.

---

## 1. The hard voice claim

> When a caller interrupts a Rime-spoken turn, the agent's conversational state
> reflects **only the speech that actually reached the caller's ear** — never the
> speech that was generated, synthesized, or queued but cut off. Results from the
> abandoned turn cannot re-enter the conversation as current.

This failure mode is specific to voice. In text there is no such thing as a sentence
the user never received, so there is nothing to diverge.

## 2. Why a baseline exists

"0/10 divergence" alone proves nothing — the scenario might simply never trigger the
bug. Every trial therefore runs **twice on identical inputs**:

- `mode=naive` — history takes the generated text; tool results are used when they
  arrive. This is what a standard agent does, and it is not a strawman: an unfenced
  agent has no way to know the turn a result was computed for is gone.
- `mode=ledger` — history takes the heard prefix; stale results are fenced by epoch.

Same barge-in offsets, same interruption text, same seed. A paired comparison.

## 3. Acceptance test

**Setup.** The agent reads three counselling slots and ends with the safety check
*"Before we sort that out, are you safe right now?"*. A slot lookup is dispatched
mid-turn with a deliberate **3.0 s** delay (`TOOL_DELAY_S`). A scripted caller
interrupts at a pseudo-random offset in 15–75% of the turn (seed `20260908`) and
changes the request. Two audio formats: `audio/L16` @16 kHz and `audio/PCMU` @8 kHz.

**Metrics.**

| Metric | Definition | Threshold (ledger) |
|---|---|---|
| `heard_divergence` | Agent believes it said words the caller never heard | 0 / n |
| `stale_accepted` | A tool result from an abandoned epoch was used as current | 0 / n |
| `false_safety_claim` | Agent believes it asked the safety check when no sound reached the caller | 0 / n |
| `escalation_ok` | Deterministic risk classifier agrees with ground truth | n / n |

The run **fails** if any ledger threshold is missed, and also fails if the *naive*
baseline shows 0 divergence or 0 stale acceptance — a control that never reproduces
the bug is not a control. This check is enforced in `eval.py`, not by hand.

**What this test does not measure.** Time-to-silence (`T_stop`). That is a playback
property and is only honest when measured at the speaker, so it is captured in the
browser client and reported separately in §6. We do not synthesize a latency number
server-side.

## 4. Procedure

```bash
cp .env.example .env          # paste the Rime key
python preflight.py           # model/voice/lang validated against the LIVE catalog
make eval                     # 10 trials x 2 modes x 2 formats -> out/eval.csv
```

`make eval-dry` reproduces the same matrix with synthetic durations and no API key,
to verify harness logic independently of the network.

Committed artifacts: `out/eval.csv` (per-trial rows, including the leaked text in
each divergent trial), `eval.py`, and the fixtures inline in `eval.py`.

## 5. Results — live Rime audio

> **PENDING.** Blocked on `RIME_API_KEY`. Fill from `out/eval.csv`.
> Numbers must come from a real `make eval` run. Unverified performance numbers
> receive no credit, and a dry run is not submittable evidence.

| Format | Mode | n | heard_divergence | stale_accepted | false_safety_claim | escalation_ok |
|---|---|---|---|---|---|---|
| L16 | naive | | | | | |
| L16 | ledger | | | | | |
| PCMU | naive | | | | | |
| PCMU | ledger | | | | | |

Rime synthesis latency observed during the run (per segment, from `preflight.py`
and `/api/say`):

| Format | TTFB p50 | TTFB p95 |
|---|---|---|
| L16 @16 kHz | | |
| PCMU @8 kHz | | |

### Harness verification (not evidence)

`make eval-dry`, synthetic durations, n=10, logic check only:

| Mode | heard_divergence | stale_accepted | false_safety_claim | escalation_ok |
|---|---|---|---|---|
| naive | 10/10 | 10/10 | 10/10 | 10/10 |
| ledger | 0/10 | 0/10 | 0/10 | 10/10 |

This confirms the scenario reproduces the bug and the harness detects it. It says
nothing about Rime audio, and is not offered as a result.

## 6. Client-measured playback (browser)

`T_stop` = barge-in detection → last audio sample rendered, from `performance.now()`
around the Web Audio stop. Reported live in the UI and in the demo recording.

> **PENDING.** Record p50 and p95 over the demo trials. Cold and warm runs labelled
> separately.

## 7. Limitations

- **No SIP trunk.** We exercise the telephony *audio format* (8 kHz μ-law), not a real
  phone transport. Browser results do not prove telephone performance.
- **Character resolution** is exact at segment boundaries and linearly interpolated
  within a segment (≤60 chars). Error is bounded by one segment and biased toward
  *unheard* — we snap backwards to a whitespace boundary, so a half-spoken word counts
  as not heard.
- **`playedMs` is client-reported.** The browser audio clock is the most honest source
  available to us; a hostile client could misreport it.
- **Not streaming.** Whole turns are synthesized before playback, so time-to-first-audio
  is worse than a streaming pipeline. Independent of the claim.
- **Small sample.** n=10 per cell is exploratory, and labelled as such.
- **The naive baseline is our own implementation** of standard behaviour, not a
  third-party agent. We make its code visible (`Ledger.mode`) so the comparison can be
  audited rather than trusted.
- **Pronunciation control is wired but unused** — no phoneme entries shipped, because
  we did not verify any by ear. No pronunciation claim is made.
