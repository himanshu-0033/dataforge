# Heard — AI support

The main frontend is now a conversation-first AI support app. It listens to ordinary concerns, responds using conversation context, and supports text input in both text and live voice sessions. It does not perform inventory operations, book appointments, diagnose, or provide therapy.

## Start on Windows

From the repository root, with the existing Python and frontend dependencies installed:

```powershell
.\start-counselor.ps1 -Restart
```

Open **http://localhost:5173**. Choose **Start talking** and allow microphone access, or **I prefer to type**. In a voice session, the message field remains available. **Pause voice** pauses audio and microphone input; typed conversation still works. **Resume voice** resumes the microphone. **End conversation** clears the transcript from app memory.

Provider configuration is read from the ignored local `pickmate/.env`. `COUNSELOR_PROVIDER=vertex` uses paid Gemini through Google Cloud; `COUNSELOR_PROVIDER=groq` selects Groq explicitly. LiveKit transports voice, Deepgram transcribes, and Rime speaks. `WORKER_SECRET` authenticates the internal bridge. The privacy dialog identifies the active text provider. Provider failures are surfaced without silently routing a conversation elsewhere.

For Vertex, use `GOOGLE_CREDENTIALS_BASE64` for service account JSON encoded as base64. The server decodes it in memory and renews access tokens through Google's authentication library; it does not create a decoded key file. Base64 is encoding, not encryption. `GOOGLE_CLOUD_PROJECT` can be omitted when the service account supplies it. Application Default Credentials are also supported; specify a project for that path. Never put credentials in `VITE_` variables or `.env.example`.

The Vertex defaults are `VERTEX_MODEL=gemini-3.1-pro-preview`, `GOOGLE_CLOUD_LOCATION=global`, and `VERTEX_THINKING_LEVEL=MEDIUM`. The model and thinking level are configurable independently of the conversation policy. Google's [Gemini 3.1 Pro documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-1-pro) lists this model as preview and does not currently support tuning. The integration uses the [Gemini streaming API](https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/models/inference).

The API entry point is `counselor.app:app` under `pickmate/backend`; the worker is `counselor.worker`. Both use the `heard` agent and room prefix. The React entry point is `pickmate/web/src/App.tsx`. Provider configuration, dispatch, and voice request models live in the counselor package. See the root [README](../README.md) for installation, checks, and the source layout.

## Conversation and data behavior

The app sends eligible conversation history to the selected provider. Interrupted voice responses remain visible as interrupted in the transcript and are excluded from subsequent assistant history. LiveKit completion events are delivery estimates, not proof of what a person heard. Streaming text is shown as a draft; it becomes a completed message only after the provider finishes successfully. Drafts are cleared on interruption, failure, and session end. Speech starts after a complete reply is available. Late results and retired worker callbacks cannot replace a newer turn.

Session tokens are stored in the current browser tab. Transcripts live only in process memory, bounded to 200 messages. The model can receive all eligible messages within a conservative 64,000-byte history budget, keeping complete recent messages when older history must be omitted. A user-written note of up to 600 characters stays available independently of this history window. It is user-supplied context, not an inferred diagnosis or a system instruction. There is no memory across sessions. Ending a session clears the transcript and note, restarting the API clears all sessions, and sessions inactive for one hour expire. Audio is not recorded by this app. The providers have their own data handling policies; the UI explains this before users share sensitive information.

**Just listen** emphasizes reflection without unsolicited advice. **Talk it through** follows a concern without repeatedly asking answered questions. **One small step** helps with one manageable action. The user's latest explicit request takes precedence over their selected style. Changes apply to the next reply; a reply still being generated is cancelled and regenerated with the updated preferences. These are model instructions, not guarantees of conversational quality.

Voice detection now allows 0.8 seconds of silence to accommodate pauses, and requires 0.15 seconds of speech before detecting an onset. These are starting settings, not measured acoustic performance. The current speech-recognition path is English; text can follow the user's language. Quiet view animations indicate application activity and do not infer emotion or measure audio volume.

The assistant identifies itself as AI support. It cannot connect to a human counselor or provide emergency help. Contextual responses to mental-health concerns are generated by the model, not a clinically validated assessment system. Use synthetic scenarios for evaluation.

## Verification

```powershell
cd pickmate
.\.venv\Scripts\python.exe -m pytest -q
cd web
npm.cmd run build
npm.cmd run test:e2e
```

Backend tests cover conversation context, provider message formats and completion checks, duplicate inputs, interrupted history, cancellation-ignoring generation, paused/disconnected typed input, worker replacement, session ownership, error recovery, and transcript/note cleanup. Browser checks cover preferences reaching the API, reload, streaming drafts, quiet view, and session reset on desktop and mobile. Live provider observations are separate from deterministic tests.

## Evaluate before fine-tuning

`pickmate/fixtures/counselor-conversations.json` contains thirteen synthetic scenarios and review criteria for the first meeting, specific reflection, corrections, rejected suggestions, continuity, direct requests, language, safety, meaning, and summaries. These are development evaluation cases, not a clinically reviewed training dataset. Review outputs yourself and add fresh holdout scenarios before drawing broader conclusions. See the [conversation design and sources](COUNSELOR_CONVERSATION_DESIGN.md) for how professional guidance informs these behaviors.

```powershell
cd pickmate
# Inspect synthetic scenarios without calling a model:
.\.venv\Scripts\python.exe scripts/evaluate_conversation.py
# Generate paid provider replies, saved only in ignored .cache:
.\.venv\Scripts\python.exe scripts/evaluate_conversation.py --live
# Compare another accessible Vertex model without changing the running app:
.\.venv\Scripts\python.exe scripts/evaluate_conversation.py --live --model MODEL_ID --output .cache/comparison.json
```

The report includes response and first-text latency, plus criteria awaiting human review. It does not turn a successful API call into a quality score. Fine-tuning requires a model that supports it, a separately reviewed dataset of appropriate dialogue examples, and comparisons on held-out conversations. No training job is launched, and user transcripts are not collected for training by this app.
