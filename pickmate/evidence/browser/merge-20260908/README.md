# Heard + PickMate merge verification — 8 September 2026

This run integrates the PickMate redesign with GitHub main `32e8bee` (Heard as the primary app). The page metadata conflict was resolved by preserving Heard at `/` and adding the redesigned PickMate at `/pickmate.html`. Vite builds both HTML entries and separate app styles.

- **78 backend tests passed**, including the incoming counselor tests: `pytest.xml`.
- **6 frontend unit tests passed**: `unit.log`.
- **8 browser tests passed**, no failures, skips, or flaky results: `playwright.json`. Desktop Chromium and emulated Pixel 7 cover both entry points and style isolation, plus the six existing inventory workflow cases.
- **Production build passed**, producing `index.html` and `pickmate.html`: `build.log`. The shared React/LiveKit/motion JavaScript chunk still triggers Vite's 500 kB advisory (884.09 kB before gzip).
- Final PickMate welcome/task screenshots are included for desktop and mobile. These are actual unedited fixture UI captures, not recorded speech.

The initial full backend run had one failure (77 passed): importing the worker during test collection loaded local credentials into the process, so a fixture that only disabled dotenv-file loading was no longer unconfigured. `tests/test_api.py` now supplies explicit empty credentials for that fixture. The original result is retained as `pytest-initial.xml`; the complete suite then passed.

Both application APIs use `/api` and default to port 8000. Start the API and worker for the app being demonstrated. The current default commands run one app API at a time, not both simultaneously. The tests use an isolated inventory API on 8001; the Heard entry check verifies its page and styles, not a real counselor conversation. Live audio and mental-health response quality were not evaluated in this merge run.

Repeat from `pickmate/` in the shared GitHub repository (or the standalone PickMate root):

```sh
make test
make test-web
make test-browser
```

Keep 5173 and 8001 free for browser checks. Start PickMate with `make api`, `make worker`, and `make web`, then open `http://127.0.0.1:5173/pickmate.html`. Heard's launch procedure is in the shared repository's `docs/COUNSELOR.md`.
