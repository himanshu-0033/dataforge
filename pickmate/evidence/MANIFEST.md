# Evidence manifest

All inventory and input text in committed tests/evaluation files are synthetic. No real worker audio or provider credentials are included.

| Artifact | What it contains |
|---|---|
| `pytest.xml` | Final backend pytest JUnit results; test count and timings from actual execution |
| `stress/trials.jsonl` | 30 item-level controller/database outcomes |
| `stress/trial-NN/events.jsonl` | Complete actual event trace for that isolated trial |
| `stress/trial-NN/snapshot.json` | Final session, stock, and durable receipts |
| `stress/summary.json` / `report.json` | Aggregate fixture results, explicit empty audio strata |
| `preflight/preflight-*.json` | Dated actual catalog/configuration/secret scan checks, missing credentials and live gate status |
| `preflight-live.log` | Strict live preflight diagnostic with missing names, no secrets |
| `browser/pickmate-session.png` | Visually checked running fixture UI; screenshot does not prove audio behavior |
| `browser/playwright.json` | Actual final browser run: four passed, zero failed, skipped, or flaky; desktop Chromium and Pixel 7 emulation |
| `../fixtures/rime-catalog-2026-09-08.json` | Public catalog fetched during explicit preflight, retained for reproducibility |

Two provider-generated Rime WAV clips now exist in `preflight/bin-variant-1.wav` and `preflight/bin-variant-2.wav`, with timing/configuration in `preflight/preflight-20260908T142529Z.json`. They are synthetic standalone wording fixtures; no real-operator or shared-clock audio recording exists. Future operator recordings belong in ignored `recordings/` and an operator-owned export location. Record the exact file, SHA-256, size, device/network setup and export location here only after capture. See `docs/LIVE_TESTS.md` for the collection procedure.

The older preflight records preserve earlier missing-credential states. Use the latest timestamp for configuration status; a catalogue-only preflight success is not a live gate success.

Publication check: the user explicitly requested committing the populated `.env` to this public repository. `preflight/published-check/preflight-20260908T143043Z.json` correctly flags `.env` and exits nonzero. The secret-exposure gate is failing; earlier clean scans were of the local source checkout where `.env` was ignored. This does not invalidate the provider synthesis or controller test observations.

Final verification: 70 backend tests passed; 6 frontend unit tests passed; 4 Playwright scenarios passed across desktop Chromium and Pixel 7 emulation; frontend production build passed. Browser tests start their own temporary SQLite/API instance on port 8001 and Vite on 5173 and have been rerun successfully. LiveKit bundle size has a Vite advisory (>500 KB); it is not a build failure.
