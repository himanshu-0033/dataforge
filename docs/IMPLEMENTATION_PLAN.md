# PickMate implementation plan

Goal: a reproducible hands-free stockroom prototype with transaction-safe corrections.
Spec: the supplied Rime_Codex_Build_Prompt.md; acceptance in ACCEPTANCE.md.
Stack: React/TypeScript/Vite, FastAPI, LiveKit Agents with Rime/Deepgram/Silero, streaming Groq text interpretation, SQLite.

The user authorizes routine decisions and continuous implementation. This empty workspace has no unrelated code or existing branch to isolate. Keep source here. The missing PDF is an external review gate, not invented competition evidence.

- [x] Domain/storage: write failing behavioral tests, implement typed intents, durable sessions/tasks/confirmations/operations, async lookup fencing and output epochs; run pytest against actual SQLite.
- [x] API/voice: session bearer ownership, scoped LiveKit tokens, worker authentication, event polling, verified SDK integrations, Rime preflight and explicit provider states; exercise HTTP and provider boundaries.
- [x] Frontend: implement responsive task-first interface and real LiveKit browser connection with fixture transcript controls; test controls, errors, task changes, provider disclosure and persistence. Six unit tests and four desktop/mobile browser cases passed; live audio remains unverified.
- [x] Evidence: run deterministic stress corpus, export database snapshots and JSONL; generate honest metrics report; finish setup, architecture, positioning, demo, live procedure and manifest.

API contract for web: `/api/health` returns `{mode, live_ready, missing_config, demo_enabled}`; `POST /api/sessions` body `{mode: 'fixture'|'live'}` returns `{session_id, token, snapshot}`. Session calls use `Authorization: Bearer <token>` and `/api/sessions/{id}`. GET snapshot returns `{session_id, room, mode, ended, paused, resolving, response_epoch, task, speech, provider, events, history, inventory}`. Task includes `{task_id, task_version, item: {sku,name,bin,available}, quantity, status, operation_id}` or null; speech includes `{response_id, response_epoch, task_version, text, status}` or null. Provider includes `{name,status,model,speaker,language,endpoint}`. Event includes `{seq,type,utc,monotonic_ms,clock_domain,session_id,task_id,task_version,response_epoch,data}`.

POST `/turn` body `{text, event_id}` accepts fixture final text asynchronously; POST `/control` body `{action:'pause'|'resume'|'cancel'|'end'|'recover'|'repeat'}`; POST `/faults` body `{lookup_delay_ms,ignore_cancellation,fail_provider:null|'lookup'|'rime'|'stt'|'llm'}` development only; POST `/token` returns `{url, token, room}` for live sessions; POST `/playback` fixture-only body `{response_id,status:'playing'|'completed'|'interrupted'}`. Fixture completion is explicitly simulated. Live playback acknowledgements are worker-only and conservative. Errors have `{detail}`. Snapshot polling every 250–500ms, sequence check, never resurrect older snapshots.

Visual design: cool neutral background #f3f5f6, white surface #ffffff, ink #20302c, muted #62726c, green accent #287655, border #dce3df. Humanist sans typography, left-aligned task/voice workspace and a narrow inventory rail. Large bin/quantity are functional picking information. No decorative performance figures. Fixture has no synthesized speech and never claims Rime activity.
