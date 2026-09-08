# Heard Ledger — a voice triage line that knows what the caller actually heard

A student can call at 2 a.m. with no app, no login and no name. The line listens,
and when risk appears it bridges to a human counsellor.

**This is a triage and bridging tool. It is not therapy, and it does not claim to be.**

---

## The problem we chose

Not "students need mental health support" — that is already known, and on our campus
it is already funded. The specific, measurable failure is the **threshold**:

| Why students who need help don't go (IIT Bombay SWC survey, May 2025) | % |
|---|---|
| "Nobody could help me" | 53.3 |
| "My issue isn't severe enough to justify a visit" | 51.0 |
| Lack of trust in the system | 35.7 |
| Ashamed or embarrassed to talk to a counsellor | 27.8 |
| Worried about anonymity — booking requires LDAP ID | 27.3 |

Half of distressed students triage themselves *out* because their problem feels too
small to justify booking a formal appointment, with a named human, using their
institute login. A voice line costs nothing to start. A web form does not.

## Why voice is necessary

Two reasons, and the second is the engineering one:

1. **Voice removes the booking act.** Remove speech and this is a mental-health web
   form — precisely the artifact half of those students already refuse.
2. **The failure mode we solve cannot exist in text.** In a chat UI there is no such
   thing as "a sentence the user never received". Unheard speech is purely acoustic.

## The hard voice problem: heard-state consistency

Standard voice agents keep conversation history from **generated** text — what the LLM
produced and handed to TTS. That is wrong the instant a caller interrupts, because
generation runs ahead of playback. The agent then believes it said things nobody heard.

In a distress conversation that divergence is not a UX bug. If the agent believes it
asked *"are you safe right now?"* and the caller never heard a sound, a safety step has
been skipped while the logs say it happened.

**We make the conversation's state of record what the caller actually heard.**

How:

1. Each turn is split into clause-sized segments, synthesized **one Rime call per
   segment**, so the text ↔ audio alignment is exact at segment boundaries.
2. The browser plays audio through the Web Audio clock and reports the true playback
   position. `playedMs` comes from audio rendered to the output device — not from
   bytes we handed to the network.
3. On barge-in, `playedMs` maps back to a character offset. We snap **backwards** to a
   whitespace boundary, so a partly-spoken word counts as unheard. We never claim the
   caller heard more than they did.
4. Only the heard prefix enters history, tagged `[interrupted mid-sentence]`.
5. Every turn carries a monotonically increasing **epoch**. Tool results from an
   abandoned turn are fenced: dropped, never spoken as current.
6. Escalation runs a **deterministic classifier over the heard transcript**, outside
   the LLM's control. The model can neither suppress nor invent it.

## Architecture

```
browser (static/index.html)          server.py (stdlib HTTP)
  mic ──► RMS gate ──► barge-in       /api/say      brain ─► ledger.start_turn
  Web Audio clock ─► playedMs  ──────► /api/bargein  ledger.barge_in(playedMs)
  split-screen ledger view            /api/state     epoch fence on tool results
                                                            │
                                                     rime.py ─► Rime TTS
```

**No WebSocket, deliberately.** Barge-in must stop playback at the speaker, so
cancellation is client-side and must not wait for a server round trip. The server only
reconciles state afterwards. That split is the honest architecture for this claim — and
it happens to need zero dependencies.

**No LiveKit, deliberately.** Its runtime cancels TTS for you, which hides the exact
mechanism we are claiming to have built. The brief permits any orchestration stack.

## Rime configuration (the judged path)

| Field | Value |
|---|---|
| Model ID | `mistv2` |
| Speaker | `ritu` — "smart, serious Indian female voice, measured and steady" |
| Language | `eng` |
| Endpoint | `https://users.rime.ai/v1/rime-tts` |
| Audio format | `audio/L16` @ 16000 Hz (browser), `audio/PCMU` @ 8000 Hz (telephony) |
| Transport | HTTPS POST, one call per segment |
| Speed control | `speedAlpha`, used on the recovery re-speak |
| Pronunciation | `phonemizeBetweenBrackets` — wired in `rime.py`, see limitations |

**Why `mistv2` specifically.** We pulled the live catalog rather than trusting docs:

| Model | Latency | Hindi voices | Inline pronunciation control |
|---|---|---|---|
| `coda` | sub-100 ms | 3 | no |
| `mistv3` | ~37 ms p50 | 0 | no |
| `mistv2` | ~175 ms median | 0 | **yes — only model** |
| `arcana` | — | 3 | no |

Hindi and pronunciation control are mutually exclusive. We resolved it by not needing
Hindi: `mistv2` carries Indian-accented **English** voices (`ritu`, `hawk`, `ironwood`,
`rohan`). We pay ~140 ms of time-to-first-audio versus `mistv3`, which is the right
trade — our claim is cancellation and state consistency, not time-to-first-audio, and
the two are independent.

Rime provides text-to-speech. We own input, ASR, reasoning, orchestration, state,
transport, tools, safety and evaluation.

## Setup

```bash
cp .env.example .env       # paste your Rime key into .env
python preflight.py        # gate: key, live catalog, one real synth in both formats
python server.py           # http://localhost:8765
```

Python 3.9+. **No pip install** — standard library only. Chrome recommended (Web Speech
API for interruption text; the acoustic barge-in works in any browser).

```bash
make test       # pure-logic self-check of the ledger
make eval-dry   # full A/B matrix, synthetic durations, no API key
make eval       # acceptance test against live Rime audio -> out/eval.csv
```

### Dev stub (not the judged path)

`RIME_DEV_STUB=1 python server.py` replaces Rime with a locally generated hum of the
correct duration, so the playback clock, barge-in and split-screen view can be worked
on without a key or API spend.

It is **off unless that variable is set explicitly**, it reports
`provider = "STUB (NOT RIME)"`, and the UI renders that label in red. Every demo and
every measured result uses `provider = "RIME"`. The provider is returned on every
`/api/say` response so the active engine is observable at all times, per the brief's
requirement that fallback behaviour be disclosed.

## Third-party services

| Service | Used for | Required |
|---|---|---|
| Rime | **all spoken output** | yes |
| Browser Web Speech API | interruption transcript | no — degrades to blank text |
| Anthropic API | optional LLM brain | no — scripted brain by default |

## Failure behaviour

| Condition | Behaviour |
|---|---|
| `RIME_API_KEY` missing/invalid | `/api/say` returns 503 with an actionable message; page still loads |
| Rime request fails | `RimeError` surfaced to the client; no silent fallback provider |
| Mic denied | Acoustic barge-in disabled; space bar / INTERRUPT button still work |
| No Web Speech API | Barge-in still fires; interruption text is blank |
| LLM unreachable | Falls back to the scripted brain and logs `brain_fallback` |
| Tool result arrives late | Fenced by epoch; counted in `dropped_results` |

There is **no fallback speech provider**. Rime is the only path to audio, so the active
provider is unambiguous.

## Known limitations

Stated plainly, because undisclosed limits are worse than disclosed ones:

- **No real telephony.** We test the telephony *audio path* (`audio/PCMU`, 8 kHz μ-law)
  but not a SIP trunk, jitter, packet loss, or carrier codecs. Browser results do not
  prove telephone performance.
- **Character resolution.** The ms→character mapping is exact at segment boundaries and
  linearly interpolated inside a segment (~60 chars). Error is bounded by one segment
  and biased toward *unheard*.
- **`playedMs` trusts the client.** It comes from the browser's audio clock. That is the
  most honest source available to us, but a hostile client could lie.
- **Not streaming.** Whole turns are synthesized before playback, so time-to-first-audio
  is worse than a streaming pipeline. Our claim is unaffected; a production build would
  stream.
- **English only.** Hinglish ASR carries a documented 30–50% relative WER increase on
  code-switched speech; we did not attempt it.
- **Pronunciation control is wired but unused.** `PRONOUNCE` in `rime.py` is empty on
  purpose: an unverified phoneme sounds worse than the default, and we did not have time
  to listen to enough candidates to ship any.
- **The RMS barge-in gate is not a real VAD.** Echo cancellation does the heavy lifting.
  Marked in-code for a Silero swap.
- **Scripted brain by default.** Deterministic behaviour is a feature for a distress
  line and for reproducible judging, not a stand-in for reasoning.

## Safety

- Never described to the caller as a counsellor, therapist, or AI therapy. Illinois'
  Wellness and Oversight for Psychological Resources Act (Aug 2025) bars AI from
  providing therapy without licensed clinician oversight; we treat that as the design
  floor, not a jurisdictional question.
- Escalation is deterministic and outside the model's control, so multi-turn prompt
  injection cannot talk the line out of escalating.
- All fixtures are synthetic. No real student audio was recorded, stored, or used.

## Repository

| File | Purpose |
|---|---|
| `ledger.py` | The claim. Heard/unheard mapping, epoch fencing, risk classifier. Self-checking. |
| `rime.py` | Rime client — per-segment synthesis, exact byte→ms accounting |
| `server.py` | Agent loop, delayed tool, reconciliation |
| `static/index.html` | Mic, playback clock, split-screen generated-vs-heard view |
| `eval.py` | Paired A/B acceptance test vs a naive baseline |
| `preflight.py` | Config gate — run first |
| `RIME_EVIDENCE.md` | The claim, test, procedure, results, limitations |
| `ARCHITECTURE.md` | Mermaid diagrams — context, barge-in flow, heard/unheard cut, eval |
| `research-brief.tex` | Background research and build plan |
