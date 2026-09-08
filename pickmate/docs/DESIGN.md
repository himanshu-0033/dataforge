# PickMate interface

The interface takes its cues from stockroom signs and picking slips: condensed headings, a large bin label, short instructions, and structural borders. React and the existing CSS system remain in use.

## Three-color system

| Role | Color | Use |
|---|---|---|
| Navy ink | `#2b2e42` | Text, welcome panel, bin location, completed state |
| Chalk paper | `#f4f5f1` | Page surface and text on dark backgrounds |
| Crimson | `#d9202a` | Primary actions, selected controls, attention |

These retain the navy and crimson from the supplied Coastal palette, with a chalk surface following the subsequent three-color brief. Muted text, borders, and hover states mix these same colors. There are no gradients or decorative blobs. Labels and icons accompany state colors.

Calculated solid-color contrast: paper/navy **12.20:1** and paper/crimson **4.58:1**. This verifies the principal text pairs, not a claim of complete WCAG certification.

## Typography and structure

- **Barlow Condensed 700** for the welcome headline and wordmark; **600** for section headings and bin/quantity figures.
- **Public Sans 400–700** for instructions, forms, inventory, and small labels. Body copy uses 400; controls and key labels use 500/600.
- Three local WOFF2 assets total 56,368 bytes. Google Fonts sources and redistribution licenses are in [`web/public/fonts`](../web/public/fonts/README.md). The application makes no runtime font-service request.
- An offset navy welcome panel sits beside the session form. The real request/locate/confirm sequence appears as stacked rows, with explanatory text alongside it.
- In a session, the current pick occupies the larger column. The bin has a distinct dark field. Inventory and completed picks remain secondary, switching to separate views on narrow screens.
- Breakpoints adapt the two-column view, heading sizes, task metrics, and controls. Keyboard focus, minimum 44 px action targets, and reduced-motion support remain in place.

## Verification

Run `make test-web` and `make test-browser`. Browser checks exercise the actual fixture API and SQLite database; they also verify local font loading and horizontal overflow on the welcome and task screens. Screenshots are written to `web/test-results/`. The final 2026-09-08 run passed six unit tests, six browser tests, and the production build; [saved output and screenshots](../evidence/browser/design-20260908/README.md) include additional 320, 768, and 1440 px layout checks.

The visual change does not establish any new live-audio performance claim. Rime, Groq, microphone input, interruption correctness, and confirmation authorization remain governed by the existing voice/controller implementation and its separate evidence.
