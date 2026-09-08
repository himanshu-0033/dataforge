# Live evaluation and recording procedure

Acceptance targets were frozen in `ACCEPTANCE.md` at commit `ae1be64`, before experiments. They remain unchanged. This procedure is not a record of execution.

## Declare the setup

Record device/OS/browser and versions, headset make, sample rates, worker and API locations, LiveKit region/service, network type and RTT, Rime endpoint/region/model/voice/language, STT/LLM IDs and versions, and the exact Git commit. Keep English/headset results separate from speakerphone, noise, telephony or multilingual conditions. Do not claim untested conditions.

## Run the gates

1. Add server credentials to `.env`; run `make preflight-live` and retain its dated configuration and real WAV clips. Listen to the two bin-wording variants at constant model/voice; record which is clearer and why. The shipping aisle/bin wording still needs a listening check.
2. Run the organizer preflight when supplied. Its absence is a separate pending gate.
3. Start API, worker, LiveKit service and browser. Verify actual Rime activity from worker events, real Deepgram transcription, and complete streaming structured calls from the selected LLM. An explicit exact confirmation must record one pick.
4. Record input and returned output on a shared clock. An OS loopback device or DAW with microphone and system audio on separate tracks is suitable. Preserve separate channels if possible. A screen capture with narration does not establish the acoustic stop boundary.

## Corpus

Collect at least **30 valid spoken interruptions while old assistant audio is actually playing**, varying onset across instruction positions. Separately collect at least 10 corrections during silent lookup waiting and 5 normal picks. Include repeated confirmation, disconnected/reconnected session, interrupted receipt, a cough/noise/backchannel, STT/LLM/Rime failure and recovery. Keep warm/cold and cached/uncached strata separate. Record failures and timeouts; never silently replace them with successful retries.

For each speech-stop trial, annotate the user onset and last superseded output sample using the recording clock. If using decoded/rendered system loopback, label it **rendered_loopback_proxy**; it does not prove when a physical speaker became quiet. Add an acoustic or hardware-loopback check for a stronger audible claim and report device/buffering uncertainty. Exclude already-silent waiting trials from speech-stop percentiles with a reason.

Write one actual annotation per line in `evidence/recordings/annotations.jsonl`:

```json
{"trial":"operator-01","outcome":"success","old_speech_playing":true,"clock_domain":"capture-01","onset_clock":"capture-01","output_clock":"capture-01","measurement":"acoustic_loopback","recording":"operator-01.wav","onset_ms":1234.0,"last_old_sample_ms":1456.0,"temperature":"warm","cache":"uncached"}
```

Numbers above are **format examples**, not observed measurements; do not copy them as a result. Set `outcome` to `failure` or `timeout` for failed trials. The report requires common clock identifiers and records exclusions. It uses nearest-rank quantiles and reports each stratum's sample count.

```sh
.venv/bin/python scripts/report.py --audio-annotations evidence/recordings/annotations.jsonl
```

Also annotate end-of-user-turn, first audible response, and first substantive answer separately. Retain LiveKit STT/TTS metrics with their original clock domains; provider first decoded frame timing from preflight is not end-to-end latency. The report leaves those fields not run until independently calculated evidence is supplied.

## Save the demo

Record the 4–5 minute real-operator demonstration from `DEMO_SCRIPT.md`, including audible speech, microphone correction, current task, provider display, event trace and receipt. Export recording files outside Git to a controlled location. Put their actual filenames, SHA-256 hashes, sizes, setup record and access/export instructions in `evidence/MANIFEST.md`. Keep credentials out of screenshots and recordings. The recording requirement remains pending until those actual files exist.
