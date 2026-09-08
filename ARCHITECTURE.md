# Architecture — heard ledger

Four views: what the pieces are, what happens on a barge-in, how the heard/unheard
cut is decided, and how the thing is run and evaluated.

## 1. Context

```mermaid
flowchart LR
  subgraph BROWSER["browser — static/index.html, no deps"]
    MIC["mic<br/>getUserMedia, echo cancellation on"]
    RMS["RMS gate<br/>above 0.045 for N frames<br/>ponytail: not a real VAD"]
    ASR["Web Speech API<br/>interruption text, optional"]
    CLK["Web Audio clock<br/>playedMs = ctx.currentTime - playStart"]
    STOP["stopAudio<br/>8 ms gain ramp, then src.stop"]
    VIEW["split-screen view<br/>heard / cut / unheard + flags"]
  end

  subgraph SERVER["server.py — stdlib ThreadingHTTPServer, port 8765"]
    SAY["POST /api/say"]
    BARGE["POST /api/bargein"]
    RESET["POST /api/reset<br/>mode = ledger or naive"]
    STATE["GET /api/state"]
    BRAIN["brain()<br/>risk short-circuit, then Claude or scripted"]
    TOOL["delayed tool<br/>TOOL_DELAY_S = 3s, tagged with epoch"]
  end

  subgraph LEDGER["ledger.py — pure logic, no I/O"]
    TURN["Turn<br/>segments, char offsets, real durations"]
    HIST["history<br/>state of record = what was HEARD"]
    FENCE["accept_tool_result<br/>drop if result_epoch below current"]
    RISK["risk_signal<br/>regex over heard text, outside the LLM"]
  end

  subgraph EXT["external"]
    RIME["Rime TTS<br/>mistv2 / ritu / eng<br/>one HTTPS POST per segment"]
    ANTH["Anthropic API<br/>optional, context = heard transcript"]
  end

  MIC --> RMS --> BARGE
  ASR --> BARGE
  CLK --> BARGE
  RMS --> STOP
  SAY --> BRAIN --> TURN
  BRAIN -.optional.-> ANTH
  SAY --> TOOL
  TURN --> RIMECL["rime.py<br/>synth per segment<br/>ms = bytes / bps / rate"]
  RIMECL --> RIME
  RIME -- "L16 16k or PCMU 8k" --> RIMECL
  RIMECL -- "set_timing per segment" --> TURN
  SAY -- "segments + audio_b64 + t_start_ms" --> CLK
  BARGE --> HIST
  TOOL --> FENCE
  BARGE --> RISK
  BARGE -- "heard, unheard, believes, flags" --> VIEW
  STATE --> VIEW
  RESET --> LEDGER
```

## 2. Workflow — the stress case

The delayed tool and the barge-in are timed to collide. That collision is the test.

```mermaid
sequenceDiagram
  autonumber
  participant C as caller
  participant B as browser
  participant S as server.py
  participant L as ledger.py
  participant R as Rime

  C->>B: speaks
  B->>S: POST /api/say {text}
  S->>L: user_said(text)
  S->>L: start_turn(reply) — epoch N
  Note over S: dispatch slot lookup, tagged epoch N, ready in 3s
  loop one call per clause-sized segment
    S->>R: POST /v1/rime-tts
    R-->>S: audio bytes
    S->>L: set_timing(i, dur_ms from byte count)
  end
  S-->>B: segments, char offsets, t_start_ms, total_ms, provider
  B->>C: playback via Web Audio

  C-->>B: interrupts mid-turn
  Note over B: RMS gate fires, stopAudio ramps gain to 0 in 8 ms
  Note over B: playedMs read from the audio clock BEFORE stopping
  B->>S: POST /api/bargein {played_ms, user_text, t_stop_ms}
  S->>L: barge_in(played_ms)
  L->>L: char_at_ms, snap back to whitespace
  L->>L: history += heard prefix + "[interrupted mid-sentence]"
  L->>L: epoch = N+1 — fence closes
  Note over S: the 3s tool result now lands, stamped epoch N
  S->>L: accept_tool_result(N, payload)
  L-->>S: FENCED, N is below N+1, counted in dropped_results
  S->>L: user_said(interruption)
  S->>L: risk_signal over heard text — deterministic
  S-->>B: heard, unheard, believes, escalated, false_safety_claim, dropped_results
  B->>C: recovery turn, continuing from what was actually heard
```

In `mode=naive` the same run appends the **full generated** text to history and has no
fence — that is the baseline `eval.py` measures against, not a strawman.

## 3. The heard/unheard cut

Every branch biases toward *unheard*. We never claim the caller heard more than they did.

```mermaid
flowchart TD
  A["played_ms from the audio clock"] --> B{"played_ms is 0 or less"}
  B -- yes --> Z0["char 0 — heard nothing"]
  B -- no --> C{"played_ms >= total_ms"}
  C -- yes --> ZF["char = len(full_text) — heard everything"]
  C -- no --> D["find the segment where<br/>played_ms falls inside this segment"]
  D --> E["exact at the segment boundary"]
  E --> F["interpolate inside the segment<br/>linear over max 60 chars"]
  F --> G["snap BACK to the last whitespace<br/>a half-spoken word counts as unheard"]
  G --> H["clamp: never snap past this segment's start"]
  H --> I["heard = full_text up to cut<br/>unheard = the rest"]
  I --> J["history gets heard only"]
  J --> K["LLM context, risk classifier and<br/>agent_believes_said all read history"]
```

## 4. Run and evaluate

```mermaid
flowchart LR
  ENV[".env from .env.example<br/>RIME_API_KEY"] --> PF["python preflight.py<br/>key, live catalog, one real synth per format"]
  PF -- pass --> DEV["python server.py<br/>localhost:8765"]
  PF -- fail --> FIX["fix key or model choice<br/>before 22:00, not at 22:00"]
  DEV --> DEMO["browser demo<br/>ledger vs naive toggle"]

  T["make test<br/>ledger.py self-check, asserts only"] --> CLAIM["proves the claim offline"]
  ED["make eval-dry<br/>synthetic durations, no key"] --> MATRIX
  EV["make eval<br/>live Rime audio"] --> MATRIX["paired A/B matrix<br/>naive vs ledger, L16 vs PCMU"]
  MATRIX --> CSV["out/eval.csv<br/>heard_divergence, stale_accepted,<br/>false_safety_claim, escalation_ok"]
  CSV --> DOC["RIME_EVIDENCE.md"]

  STUB["RIME_DEV_STUB=1<br/>local hum, provider = STUB (NOT RIME)"] -.never the judged path.-> DEV
```
