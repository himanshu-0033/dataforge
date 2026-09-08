# PickMate acceptance specification v1

Frozen before experiments, 2026-09-08. Targets are not measurements.

1. Audible barge-in stop: p95 <= 300 ms, at least 30 valid trials where old speech was audible at onset, on a declared English/headset/device/network setup.
2. Delayed lookup corrections: zero obsolete results in current instructions, UI, or writes in the executed corpus, including a five-second lookup that ignores cancellation.
3. Every completed stress trial records the corrected item and quantity.
4. Zero duplicate decrements across retry, reconnect, event replay, and process restart.
5. A stale or interrupted generic confirmation cannot authorize a write.
6. Verify real Rime model, speaker, language, endpoint and audible playback in the judged path.

Tests cover both commit/correction orderings, late LLM/TTS work, current status during lookup, false interruption, invalid quantities, ambiguity, availability, ownership, session end, and dependency recovery. Fixture results only support application-state claims.

Timing procedure: collect shared-clock input/output recordings; annotate onset and final old-output sample. Keep rendered-loopback proxies separate from physical audible measurements. Waiting trials are excluded from speech-stop distribution, never counted as zeros. Use nearest-rank quantiles; report sample count, failures, timeouts, exclusions and reasons, cold/warm and cached/uncached strata. Record first response and first substantive answer separately. Keep raw rows. No threshold changes after observing results.

External gates: Rime PS.pdf was not supplied at the referenced path or found by filename in workspace/Downloads/Desktop. Competition-brief reconciliation and organizer checker remain pending. No provider credentials were configured at inspection. The product specification explicitly permits completing independent fixture work in this condition. Real synthesis, operator recording, and audible metrics must remain unverified until performed.
