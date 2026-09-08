# PickMate demo: 4 minutes 30 seconds

Use a real operator with a headset, English input, and the declared device/network configuration. Inventory is synthetic. A script or screenshot is not the required operator recording.

| Time | Action and narration |
|---|---|
| 0:00–0:30 | Show a worker holding cartons. Explain that hands and eyes are occupied. State that the inventory is synthetic and the database is real. |
| 0:30–1:00 | Start Live voice; grant microphone permission. Open the developer panel briefly to show backend-reported Rime activity and the configured model/voice. If live preflight has not passed, label this a fixture demonstration and do not present it as judged live voice. |
| 1:00–1:45 | Say “Find six blue cartons.” Hear aisle A, bin 3. Ask “Repeat the location.” Say “I picked them.” After readback, say “Confirm six blue cartons.” Show the one durable receipt. |
| 1:45–2:10 | Explain that a later correction can otherwise leave an old instruction or duplicate update. Enable five-second lookup delay and return-after-cancellation in the development panel. |
| 2:10–3:00 | Start a new request for six blue cartons. While waiting or speaking, say “Wait, make that four red cartons.” Set subsequent lookup delay to zero if needed. Let the old lookup finish. Point out the stale-result rejection event; the active task remains four red cartons. |
| 3:00–3:40 | Say “I picked them,” then “Confirm four red cartons.” Repeat the confirmation. Show one corrected task receipt and unchanged blue stock for this stress trial. Reconnect and demonstrate the existing outcome. |
| 3:40–4:10 | Show the actual event trace and database receipt. State executed fixture counts separately from live audio results. If no recording-based stop measurements exist, say “Audible interruption latency is unverified.” |
| 4:10–4:30 | Explain current limits: one English worker per session, headset evaluation setup, single API instance, no enterprise warehouse integration, explicit confirmation required in live mode. |

For a clean replay, use a **new database filename**, seed it, and restart the API. Never delete or reset an existing database during a demo that needs to show durable recovery. Use `scripts/stress.py` for isolated repeatable database fixtures.
