# PickMate evidence

Hard claim under evaluation: a worker can interrupt speech or an inventory lookup, correct the request, and continue without obsolete instructions, stale confirmations, or duplicate inventory updates.

The original acceptance specification is [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md), committed as `ae1be64` before experiments. The audio target remains **p95 <= 300 ms over at least 30 valid spoken interruptions in a declared setup**. It is not a measured result.

## Results from this environment

| Check | Actual result | Scope / evidence |
|---|---|---|
| Controller stress corpus | 30/30 passed; zero obsolete queued instructions; zero duplicate writes | Fixture text input and actual isolated SQLite databases. [Rows](evidence/stress/trials.jsonl), [summary](evidence/stress/summary.json), individual event traces and final snapshots in each trial directory |
| Five-second delay | Two configured trials, including one that ignores cancellation and actually returns late | Trials 01 and 02; a cancelled silent lookup does not count as an audible interruption trial |
| Backend / SDK boundary tests | 70 passed; [pytest.xml](evidence/pytest.xml) | Domain, API ownership/tokens, race/recovery, provider configuration, real SDK parsing with fixture transport, measurement exclusions |
| Browser workflow | 4/4 passed: desktop Chromium and mobile Chromium fixture scenarios; 6/6 frontend unit tests; production build passed | See [manifest](evidence/MANIFEST.md) and saved browser results; UI tests do not prove audible stopping |
| Rime catalog | `coda` / `astra` / `eng` pairing validated against downloaded live catalog | [Dated preflight records](evidence/preflight/), [catalog snapshot](fixtures/rime-catalog-2026-09-08.json); SHA-256 `3a4146ba98584c54bab9f66e8cf9b04c8d0281a976bcf5d4efc8831e836578dd` |
| Rime synthesis | Two real streaming clips generated with coda/astra/en | [Actual preflight](evidence/preflight/preflight-20260908T142529Z.json); [variant 1](evidence/preflight/bin-variant-1.wav), [variant 2](evidence/preflight/bin-variant-2.wav). Human listening comparison pending; these are standalone wording fixtures, not current inventory instructions |
| LiveKit credential check | Passed: authenticated read-only room-list request | Trusted certifi CA bundle was required on this macOS Python installation. No room audio test performed |
| Groq streaming tool calling | Passed: one real request produced a validated four-red-carton operation | [Actual result](evidence/preflight/groq-live-20260908T143614Z.json); 1,340 ms for this one interpretation, not full voice latency |
| LiveKit worker registration | Passed | Local macOS worker registered as `pickmate`; [record](evidence/preflight/worker-registration-20260908.json). Registration does not prove room audio |
| Live STT and complete voice session | Not run | Credentials configured; real microphone, transcription and browser audio still require a session test |
| Audible barge-in stop | Unverified; **n=0** | No real operator shared-clock recording; no p50/p95 reported |
| End of user turn to first audio / substantive answer | Not run; **n=0** | No timing value inferred from fixture queue events |
| STT / reasoning / TTS first byte / playback buffers | Live measurements not run | Supported worker metrics/preflight instrumentation is present |
| False interruption, acoustics, network recovery | Deterministic behavior tested; live rate/quality unverified | Headset proposed as first configuration; no speakerphone/noisy-room claim |
| Operator demo recording | Pending | The script and screenshots do not fulfill the recording requirement |

## Configuration

Rime: `coda`, `astra`, `en` (catalog normalization `eng`), `use_websocket=True`, sentence segmentation `bySentence`, base `wss://users-ws.rime.ai`, resolved `/ws3`, signed 16-bit mono PCM at 24,000 Hz in JSON/base64 WebSocket frames. US West (`us-west-2`) is provisional; selection using measurements from a deployed worker remains pending. The browser receives negotiated LiveKit WebRTC audio; actual codec and physical buffering are unverified.

Installed LiveKit Agents and Rime/Deepgram/Silero/OpenAI plugins: `1.5.17`; Python RTC: `1.1.8`; LiveKit API: `1.2.1`. Deepgram: `nova-3`, `en-US`, 16,000 Hz integration with inventory keyterms. Text LLM: Groq-hosted `openai/gpt-oss-120b` at `https://api.groq.com/openai/v1`, using OpenAI SDK `3.8.0` as a compatible client; no OpenAI credentials. React `19.2.8`, TypeScript `5.9.3`, Vite `7.3.6`, LiveKit browser SDK `2.22.3`, Playwright `1.63.0`. Exact transitive versions are in the committed lockfiles.

Two synthesis observations reached their first decoded frame after 1.765 s and 0.425 s respectively (n=2, sequential requests). These are provider-stream observations, not end-to-end response latency or audible-stop measurements; no percentile or cold/warm claim is made. Earlier certificate failures are retained in the preflight records.

## Repeat the checks

```sh
make test
make test-web
make test-browser
make stress
make report
make preflight
make preflight-live
```

The fixture stress run seeds a separate real database for every trial, starts six blue cartons, corrects to four red cartons, allows late work to finish, confirms, replays the same event, recovers, and inspects durable results. Valid corrected trials end with blue stock 40 and red stock 28, exactly one red-carton receipt, and no old-version speech queued after correction. Controller timing is not an audible proxy and is not reported as one. No weakened production mode or cross-provider benchmark is present.

For real recordings, follow [docs/LIVE_TESTS.md](docs/LIVE_TESTS.md). Use the recording clock for onset/output annotations; retain failed, timed-out, and excluded trials with reasons. Use nearest-rank percentiles and separate warm/cold and cached/uncached groups. Only trials with old speech playing at onset belong in the stop distribution. Rendered loopback is labeled a proxy; physical speaker audibility needs an acoustic/hardware check.

## Practical limitations

- Live generic `Yes` is disabled without trusted full delivery. The live assistant asks for self-contained exact item/quantity confirmation. Fixture tests model complete versus interrupted delivery with bounded confirmation expiry.
- SDK/adapter contract tests verify construction, cancellation fences and stream parsing; live provider behavior, network buffering and browser audible stopping need real runs.
- One API process with persistent SQLite; no distributed worker scheduling guarantee beyond the documented API-owned leases. Independent worker sessions share stock but cannot access each other's tasks/events without authorization.
- No enterprise warehouse connection, partial picks, automatic reversals, multilingual, noisy-room or telephony claims.
- `Rime PS.pdf`, organizer checker, deployed-worker region comparison, hosted deployment and real operator recording remain pending. The public project catalog review is documented in [POSITIONING.md](docs/POSITIONING.md); originality is not asserted.
