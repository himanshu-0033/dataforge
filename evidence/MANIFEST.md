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
| `browser/` | Browser test results and UI screenshots when generated; screenshots do not prove audio behavior |
| `../fixtures/rime-catalog-2026-09-08.json` | Public catalog fetched during explicit preflight, retained for reproducibility |

No audio recordings currently exist. Future recordings belong in ignored `recordings/` and an operator-owned export location. Record the exact file, SHA-256, size, device/network setup and export location here only after capture. See `docs/LIVE_TESTS.md` for the collection procedure.

The older preflight records preserve earlier missing-credential states. Use the latest timestamp for configuration status; a catalogue-only preflight success is not a live gate success.
