# PickMate

A hands-free inventory assistant for a stockroom worker carrying or sorting items. Ask for an item and quantity, hear its bin, correct the request while work is running, and explicitly confirm the completed pick. The database records one completion and decrements stock once.

**Inventory is synthetic.** The app includes 20 deterministic items and a real SQLite database. The live path uses Rime for every spoken response; fixture mode uses typed input and simulated playback acknowledgements with no speech provider.

## Run locally

Requirements: Python 3.11–3.13, Node 20.19+ or 22.12+, npm, and network access for installation. Tested here on macOS arm64, Python 3.13. All commands below run from this directory (`pickmate/` in the dataforge repository).

```sh
make install
cp .env.example .env     # only when .env does not already exist
make seed               # migrates and seeds; never resets existing stock
make api                # terminal 1: http://127.0.0.1:8000
make web                # terminal 2: http://localhost:5173
```

Open the web URL, choose **Fixture**, and start a session. Type `Find six blue cartons`, then `I picked them` and `Confirm six blue cartons`. A repeated confirmation returns the durable outcome. Use the Developer panel to set a five-second lookup delay and return a result after cancellation; correct to `Wait make that four red cartons` while the lookup runs.

## Live voice setup

Keep credentials in the ignored **`.env`** file on the API/worker host. In particular, put your Rime key in `RIME_API_KEY=...`; never in a frontend file or a `VITE_` variable. Configure `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, and a random `WORKER_SECRET` shared by the API and worker. Generate the latter with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` and place it only in `.env`.

```sh
make preflight          # current catalog, pairing, secret scan; synthesize if Rime key exists
make preflight-live     # strict credentials + real Rime synthesis gate
make worker             # terminal 3; keep running while using voice
```

Restart the API after changing `.env`; it loads configuration at startup. Choose **Live voice** and grant microphone access. LiveKit must be configured and reachable; a hosted LiveKit project is the simplest service configuration. This project does not provision a LiveKit server or cloud accounts.

Use English and a headset for the first evaluation. Say `Find six blue cartons`, `Repeat the location`, `Wait make that four red cartons`, `I picked them`, and `Confirm four red cartons`. `Pause` retains the task and microphone so `Resume` works. `Cancel this pick` cancels only uncommitted work. A committed pick remains recorded; reversal and partial fulfillment are unsupported.

**Live confirmation is deliberately conservative:** SDK playout completion cannot prove the full question was heard. In live mode the assistant requests a self-contained confirmation with exact item and quantity. Generic `Yes` is exercised only in fixture tests with explicit simulated full-delivery acknowledgement and a 30-second validity window. This is a disclosed gap against the requested live generic-yes journey.

## Configuration and actual dependencies

| Component | Configuration / installed version |
|---|---|
| Rime | `coda`, `astra`, `en` (catalog key `eng`), `bySentence` |
| Rime endpoint | base `wss://users-ws.rime.ai`; plugin resolves `/ws3` once |
| Region | US West / `us-west-2`, provisional; deployed-worker region comparison not run |
| Rime audio | JSON WebSocket with base64 signed 16-bit mono PCM, 24,000 Hz |
| Browser audio | LiveKit WebRTC audio; negotiated codec/buffering must be measured in live run |
| LiveKit | Agents and Rime/Deepgram/Silero/OpenAI plugins `1.5.17`; Python RTC `1.1.8`; API `1.2.1` |
| STT | Deepgram `nova-3`, English `en-US`, 16,000 Hz input integration; inventory keyterms |
| VAD | LiveKit Silero, VAD endpointing/interruption through the installed SDK |
| Text LLM | OpenAI `gpt-4.1-mini-2025-04-14`; SDK `3.8.0`; streamed structured tool arguments |
| API / models | FastAPI `0.141.1`, Pydantic `2.13.5`, httpx `0.28.1` |
| Frontend | React/TypeScript/Vite and official `livekit-client`; exact resolved versions in `web/package-lock.json` |
| Storage | SQLite, WAL, migrations, transactional compare-and-decrement and unique task/operation receipts |

Python dependencies are pinned transitively in `uv.lock`; JavaScript dependencies in `web/package-lock.json`. `docs/PROVIDERS.md` records inspected SDK APIs and provider behavior. Catalog compatibility has been verified; it does not prove synthesis or live voice performance.

## Verification and evidence

```sh
make test
make test-web
cd web && npx playwright install chromium && cd ..
make test-browser       # starts isolated test API on 8001 and Vite on 5173; keep these ports free
make check
make stress            # 30 fixture trials with isolated real databases
make report
```

Actual outputs and limitations are indexed in [RIME_EVIDENCE.md](RIME_EVIDENCE.md), [evidence/report.json](evidence/report.json), [evidence/stress/summary.json](evidence/stress/summary.json), and [evidence/MANIFEST.md](evidence/MANIFEST.md). These fixture measurements establish executed application-state behavior only. No audio performance values or operator recording are claimed without corresponding files.

## Architecture and operating limits

React publishes microphone audio directly to LiveKit. A long-running Python worker handles STT/VAD and Rime output. The FastAPI service interprets final transcripts through a streaming text adapter and validates typed proposals in the workflow controller. API polling carries state/events, not audio chunks. Each speech, lookup, confirmation, worker generation and inventory action has an application-owned identity.

Run **one API process** for this MVP. SQLite persists at `DATABASE_PATH` (default `data/pickmate.sqlite`) and must be on a durable local disk. The API alone owns the controller and asynchronous lookups. API restarts and worker recovery invalidate transient confirmations and recover receipts. Do not scale to multiple API replicas without redesigning scheduling/leases and storage. Independent sessions have separate owner tokens, tasks and events while sharing real stock.

Rime failure stops output and preserves the task; no alternate speech provider is configured. STT/LLM failure cannot execute guessed writes. The live worker stops on terminal transport/provider failure; reconnect explicitly dispatches a replacement where required. Old workers cannot mutate a newly claimed session generation. Model calls have a 12-second controller deadline; SDK retries and timeouts are bounded. Writes are never retried with new operation identities.

For hosting, serve the frontend over HTTPS and use a secure LiveKit URL; localhost is the browser microphone exception. Host the API with a persistent disk and the worker as a separate continuous service with outbound provider access. Set `WEB_ORIGIN` to the exact frontend origin, `API_URL` to the worker-accessible API, and proxy frontend `/api` requests to FastAPI. Set `DEMO_ENABLED=false` outside controlled demo environments. Session tokens expire after five minutes for room joining and are scoped to one room/microphone identity. The session bearer is stored only in tab sessionStorage for recovery and must be treated as a credential. No public deployment was performed.

## Submission documents and remaining gates

- [Architecture and interruption protocol](docs/ARCHITECTURE.md)
- [Frozen acceptance targets](docs/ACCEPTANCE.md) (initial commit `ae1be64`)
- [Four-to-five-minute demo script](docs/DEMO_SCRIPT.md)
- [Live measurement and recording procedure](docs/LIVE_TESTS.md)
- [Catalog positioning review](docs/POSITIONING.md)

`Rime PS.pdf` and the organizer checker were not supplied/found, so brief reconciliation and the organizer gate remain pending. The public project catalog was reviewed; no uniqueness claim is made. Live STT/LLM/Rime session validation, operator recording, region selection, physical audible-stop measurements and deployment remain pending unless subsequently recorded in the evidence manifest.
