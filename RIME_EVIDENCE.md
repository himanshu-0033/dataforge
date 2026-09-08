# Rime evidence

## Claim

For a browser voice prototype, an interrupted response contributes only completed audio segments to history. Work from an obsolete turn is cancelled or fenced. A caller's finalized correction is recorded once, and the next response uses the updated preference.

Client playback timestamps are estimates; completed segments are not independent proof of acoustic reception. Partially played segments remain unconfirmed. The earlier character-interpolation implementation and its precision claims have been replaced.

## Acceptance tests

| Test | Expected result |
|---|---|
| Normal response completes | Full text enters history once |
| Interrupt in a segment | Partial segment excluded |
| Morning lookup interrupted with evening correction | Old lookup cancelled; evening option returned |
| Interrupt an in-flight synthesis request | Returned old audio never becomes playable |
| Duplicate request/completion | No duplicate transcript entries |
| Separate sessions | No shared transcript or preference |
| Speech-provider error | Visible error; subsequent retry succeeds |
| Risk keyword | Explicit unavailable handoff status; no false transfer claim |

Run `python -m unittest -v test_workflow` and `python ledger.py`.

## Offline A/B harness

`python eval.py --dry -n 10 -o out/eval-dry.csv`

| Mode | Divergence | Stale accepted | False safety claim | Fixture escalation agreement |
|---|---|---|---|---|
| naive | 10/10 | 10/10 | 10/10 | 10/10 |
| ledger | 0/10 | 0/10 | 0/10 | 10/10 |

Synthetic durations only. This is a narrow logic regression check, not listening evidence or clinical validation. The baseline is implemented in this repository, not measured against a third-party agent. Browser naive mode varies history commitment; cancellation remains enabled in both browser modes.

## Live Rime evidence: PENDING

Conversation update: OpenAI now generates replies from committed history and synthetic lookup results. Both OpenAI and Rime credentials are required. Fourteen offline regression tests pass with mocked providers. Browser speech uses sentence-sized segments up to 180 characters, leaving a larger unconfirmed portion after interruption than the older 60-character chunks. Live naturalness, microphone accuracy, and latency remain unverified.

Run `python preflight.py`, then `python eval.py -n 10 --formats L16,PCMU -o out/eval-live.csv` with real credentials. Record exact model, voice, language, endpoint, format, and transport from the shipped path. Listen to the output to verify decoding and intelligibility. Preserve the CSV and generated audio separately from dry runs. The live evaluator measures state logic using synthesized durations; it does not play or transcribe a real conversation.

No live Rime performance numbers are claimed by this update.

## Browser test procedure

1. Run the server with real Rime enabled and the provider visibly identified as RIME.
2. Start a fresh session. Enable the microphone and use a synthetic morning appointment request.
3. First complete a normal interaction.
4. Start another lookup with the configured three-second delay, interrupt, and request evening only.
5. Save evidence of the cancelled old lookup, one finalized correction, and the final evening response.
6. Repeat during playback and synthesis; include an early interruption and a segment-boundary interruption.
7. Test microphone denial, unavailable recognition, synthesis failure, repeated interruptions, and session restart.
8. Record browser/device, headphones versus speakers, provider, cold/warm and cached/uncached conditions, and all failures.

The local stub browser check demonstrates the typed workflow, audio lifecycle, cancellation, and visible provider labeling only. It cannot establish speech intelligibility, microphone recognition, or real Rime behavior.

## Acoustic time-to-silence: PENDING

The UI reports stop scheduling overhead, not time-to-silence. Do not submit it as an acoustic latency result. For acoustic evidence, record playback output and a synchronized interruption marker through an appropriate loopback/capture arrangement, identify the last output sample, and report the measurement method, trial data, p50/p95, and device/output latency limitations. No such acoustic experiment has been run here.

## Limitations

Whole-turn synthesis; client-reported timing; no word alignment; basic RMS gate and English browser recognition; narrow deterministic request handling; regex risk detection; no real handoff, booking, or telephony. Dev-stub output is explicitly labeled and is not submission evidence. See README for setup and the shipped workflow.
