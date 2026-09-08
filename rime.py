"""Thin Rime TTS client. Stdlib only.

Rime provides the primary spoken output on the judged path. We synthesize one
segment per call rather than streaming a whole turn, because that is what makes the
text <-> audio alignment EXACT at segment boundaries - which the heard ledger needs.

Byte accounting (deterministic, no guessing):
    L16  : 16-bit mono PCM  -> ms = bytes / 2 / rate * 1000
    PCMU : 8-bit G.711 mu-law -> ms = bytes / 1 / rate * 1000
"""
import json
import os
import struct
import time
import urllib.error
import urllib.request

TTS_URL = "https://users.rime.ai/v1/rime-tts"

MODEL = "mistv2"
SPEAKER = "ritu"
LANG = "eng"

FORMATS = {
    # name : (Accept header, sampling rate, bytes per sample)
    "L16": ("audio/L16", 16000, 2),
    "PCMU": ("audio/PCMU", 8000, 1),
}

# Campus vocabulary that generic TTS mangles. Values are Rime phonetic alphabet
# strings, applied with phonemizeBetweenBrackets. Left empty deliberately: an
# unverified phoneme sounds WORSE than the default, so we only add entries we have
# actually listened to. See RIME_EVIDENCE.md "pronunciation" for the ones we tested.
PRONOUNCE = {
    # "Kharagpur": "k1arxgp0Ur",   # example shape - verify by ear before enabling
}


class RimeError(RuntimeError):
    pass


def wav_bytes(pcm, rate):
    """Wrap 16-bit mono PCM in a WAV header."""
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    hdr += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(pcm)) + pcm


def apply_pronunciation(text):
    """Wrap known-hard words in {curly braces} for Rime's phonemizer."""
    if not PRONOUNCE:
        return text, False
    out, hit = text, False
    for word, phon in PRONOUNCE.items():
        if word.lower() in out.lower():
            out = out.replace(word, "{%s}" % phon)
            hit = True
    return out, hit


class RimeClient:
    def __init__(self, api_key=None, model=MODEL, speaker=SPEAKER, lang=LANG):
        self.api_key = (api_key or os.environ.get("RIME_API_KEY", "")).strip()
        if not self.api_key:
            raise RimeError("RIME_API_KEY is not set - run: python preflight.py")
        self.model = model
        self.speaker = speaker
        self.lang = lang
        self.calls = 0
        self.total_ttfb = 0.0

    def synth(self, text, fmt="L16", speed=1.0):
        """Synthesize one segment. Returns (audio_bytes, duration_ms, ttfb_ms).

        speed: Rime's speedAlpha. NOTE - lower values speak FASTER, so we invert
        here to keep the caller-facing argument intuitive (speed=0.9 -> slower).
        """
        accept, rate, bps = FORMATS[fmt]
        text_out, phonemized = apply_pronunciation(text)

        payload = {
            "text": text_out,
            "modelId": self.model,
            "speaker": self.speaker,
            "lang": self.lang,
            "samplingRate": rate,
            "speedAlpha": round(2.0 - speed, 3),
        }
        if phonemized:
            payload["phonemizeBetweenBrackets"] = True

        req = urllib.request.Request(TTS_URL, data=json.dumps(payload).encode(),
                                     method="POST")
        req.add_header("Authorization", "Bearer " + self.api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", accept)

        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                ttfb = (time.perf_counter() - t0) * 1000
                audio = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200].decode("utf-8", "replace")
            raise RimeError("Rime HTTP %d: %s" % (exc.code, detail))

        if not audio:
            raise RimeError("Rime returned empty audio for: %r" % text[:60])

        self.calls += 1
        self.total_ttfb += ttfb
        return audio, len(audio) / bps / rate * 1000.0, ttfb

    def synth_turn(self, turn, fmt="L16", speed=1.0):
        """Synthesize every segment of a Turn and record real timings on it."""
        ttfbs = []
        for i, seg in enumerate(turn.segments):
            audio, dur_ms, ttfb = self.synth(seg.text, fmt=fmt, speed=speed)
            turn.set_timing(i, dur_ms, audio)
            ttfbs.append(ttfb)
        return ttfbs

    def turn_audio(self, turn):
        return b"".join(s.audio for s in turn.segments)


if __name__ == "__main__":
    # Smoke test - needs a live key.
    import sys
    from preflight import load_env
    import ledger

    load_env()
    try:
        c = RimeClient()
    except RimeError as e:
        print("SKIP:", e)
        sys.exit(0)

    t = ledger.Ledger().start_turn(
        "Okay, I hear you. I've got three slots tomorrow, one at ten in the morning.")
    ttfbs = c.synth_turn(t, fmt="L16")
    os.makedirs("out", exist_ok=True)
    open("out/rime_smoke.wav", "wb").write(wav_bytes(c.turn_audio(t), FORMATS["L16"][1]))

    print("segments   :", len(t.segments))
    print("total audio: %.0f ms" % t.total_ms)
    print("ttfb       : %s ms" % [round(x) for x in ttfbs])
    print("heard@1500 :", repr(t.heard(1500.0)))
    print("wrote out/rime_smoke.wav")
