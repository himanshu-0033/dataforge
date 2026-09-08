# Heard — AI support

Heard is a voice and text conversation app with paid Vertex Gemini support and an explicit Groq option. LiveKit, Deepgram, and Rime handle voice. The API keeps conversation history in memory and fences interrupted or obsolete responses.

## First-time setup

Requires Python 3.11–3.13, Node.js 22.12+ or 24, and npm.

```powershell
python -m pip install uv
uv sync --frozen --directory app
npm.cmd ci --prefix app/web
if (-not (Test-Path app/.env)) {
    Copy-Item app/.env.example app/.env
}
```

Fill in `app/.env` locally. For Vertex, set `COUNSELOR_PROVIDER=vertex` and `GOOGLE_CREDENTIALS_BASE64` to the encoded service account JSON, or use Application Default Credentials with `GOOGLE_CLOUD_PROJECT`. The configured Vertex model is `gemini-3.1-pro-preview` in `global`. To use Groq explicitly, set `COUNSELOR_PROVIDER=groq` and `GROQ_API_KEY`. Voice also needs the LiveKit, Deepgram, Rime, and worker credentials listed in the example. Local environment files are ignored by Git; `.env.example` contains placeholders only.

## Run

On Windows, from the repository root:

```powershell
.\start-counselor.ps1 -Restart
```

Open **http://localhost:5173**. Choose **Start talking** or **I prefer to type**. Choose **Just listen**, **Talk it through**, or **One small step** to guide the conversation. An optional session note keeps your preferences or current focus available throughout the session. **Quiet view** offers a calmer space with the current reply; the transcript remains available. Voice sessions also accept typed input.

To run the services separately, use one terminal for each command:

```sh
uv run --frozen --directory app uvicorn counselor.app:app --host 127.0.0.1 --port 8000
uv run --frozen --directory app python -m counselor.worker dev
npm run dev --prefix app/web
```

## Checks

```sh
uv run --frozen --directory app python -m pytest -q
uv run --frozen --directory app ruff check backend tests scripts web/tests
uv run --frozen --directory app ruff format --check backend tests scripts web/tests
npm test --prefix app/web
npm run build --prefix app/web
npm exec --prefix app/web -- playwright install chromium
npm run test:e2e --prefix app/web
```

Browser tests run the real API with a deterministic conversation provider on ports **8001** and **4173**. They cover text conversation, recovery after reload, interruption, transcript cleanup, and the privacy dialog on desktop and mobile. They do not use live provider credentials.

For configuration checks without network access:

```sh
uv run --frozen --directory app python scripts/preflight.py --offline
```

Use `--live` to check the configured catalog, synthesize sample speech, and generate a synthetic conversation reply. Outputs go to the ignored `app/.cache/preflight/` directory. Live provider calls require credentials.

The root `Makefile` provides equivalent `install`, `api`, `worker`, `web`, `test`, `test-web`, `test-browser`, `check`, `preflight`, and `preflight-live` targets.

## Source layout

- `app/backend/counselor/`: authenticated API, session state, conversation provider, and voice worker.
- `app/web/src/`: React application, API client, shared UI primitives, and styles.
- `app/tests/`: backend conversation and voice regression tests.
- `app/web/tests/`: browser tests and their local API fixture.
- `app/scripts/preflight.py`: provider configuration and optional live smoke checks.
- [Conversation behavior and data handling](docs/COUNSELOR.md).

The earlier browser prototype, inventory app, planning documents, and generated demo evidence have been retired. Their history remains in Git.

Heard identifies itself as AI support. It cannot provide therapy, emergency assistance, appointments, or human transfers. Transcripts stay in process memory until the session ends or expires after one hour of inactivity. Use synthetic scenarios for evaluation.
