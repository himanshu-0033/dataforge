# Stockroom design verification — 8 September 2026

This run verifies frontend appearance and fixture behavior. It is not a voice recording or live audio measurement.

- **6/6 unit tests**: `unit.log`.
- **Production build passed**: `build.log`. Vite also emitted the existing warning about a JavaScript chunk above 500 kB (918.61 kB before gzip); this remains a performance improvement opportunity.
- **6/6 browser tests**, zero failed, skipped, or flaky: `playwright.json`. `playwright.log` preserves the raw npm output; the JSON file removes only npm's leading command banner.
- Desktop Chromium and emulated Pixel 7 exercise real fixture sessions, confirmed stock updates, correction during a five-second lookup, and controls. Both also verify loaded local font faces and absence of horizontal overflow.
- `welcome-chromium.png`, `welcome-mobile.png`, `guided-pick-chromium.png`, and `guided-pick-mobile.png` come from that final browser run.
- `welcome-320.png`, `welcome-768.png`, `welcome-1440.png`, and `layout.json` are additional read-only Chromium captures against the running local API. All three widths loaded the bundled fonts and had no horizontal overflow. No voice session was started for these captures.
- Screenshots capture actual UI; they have not been visually edited. Fixture browser tests intentionally expose voice as unconfigured; the additional local welcome captures show configured live credentials. Neither establishes live provider health.

Repeat from the repository root with `make test-web` and `make test-browser`; the browser suite writes fresh screenshots under `web/test-results/`. To save a clean JSON report, use `npm run --silent test:e2e --prefix web -- --reporter=json > evidence/browser/design-20260908/playwright.json` with port 5173 free.

Design decisions and font licenses are linked from [`docs/DESIGN.md`](../../../docs/DESIGN.md).
