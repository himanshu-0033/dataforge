"""Preflight gate. Run this FIRST: python preflight.py

Verifies, in order:
  1. RIME_API_KEY is present
  2. mistv2 / ritu / eng exists in Rime's LIVE catalog (not a stale copy)
  3. A real synth call succeeds, in both L16 (browser) and PCMU (telephony)
  4. Latency is measured and printed

Exits non-zero on any failure. Stdlib only - nothing to pip install.
"""
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request

TTS_URL = "https://users.rime.ai/v1/rime-tts"
CATALOG_URL = "https://users.rime.ai/data/voices/all-v2.json"

MODEL = "mistv2"
SPEAKER = "ritu"
LANG = "eng"

# (Accept header, sampling rate, bytes per sample, label)
FORMATS = [
    ("audio/L16", 16000, 2, "browser"),
    ("audio/PCMU", 8000, 1, "telephony"),
]

SAMPLE = "Hey, I'm here. Take your time - what's going on tonight?"


def load_env(path=".env"):
    """Minimal .env parser so we don't need python-dotenv."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def fail(msg, hint=""):
    print("\n  FAIL: " + msg)
    if hint:
        print("  -> " + hint)
    sys.exit(1)


def ok(msg):
    print("  ok   " + msg)


def wav_bytes(pcm, rate):
    """Wrap 16-bit mono PCM in a WAV header so the file is playable."""
    hdr = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    hdr += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return hdr + b"data" + struct.pack("<I", len(pcm)) + pcm


def check_catalog():
    """The brief disqualifies configs that fail preflight. Check the LIVE list."""
    try:
        with urllib.request.urlopen(CATALOG_URL, timeout=20) as r:
            catalog = json.load(r)
    except Exception as exc:
        fail("could not reach the Rime voice catalog: %s" % exc,
             "Check your network. The catalog is public, no key needed.")

    voices = catalog.get(MODEL, {}).get(LANG, [])
    if not voices:
        fail("model/lang %s/%s not in live catalog" % (MODEL, LANG))
    if SPEAKER not in voices:
        fail("speaker '%s' is not in %s/%s" % (SPEAKER, MODEL, LANG),
             "Available sample: %s" % ", ".join(sorted(voices)[:12]))
    ok("%s / %s / %s present in live catalog (%d voices in %s/%s)"
       % (MODEL, SPEAKER, LANG, len(voices), MODEL, LANG))


def synth(key, accept, rate, label):
    body = json.dumps({
        "text": SAMPLE,
        "modelId": MODEL,
        "speaker": SPEAKER,
        "lang": LANG,
        "samplingRate": rate,
        "speedAlpha": 1.0,
    }).encode()

    req = urllib.request.Request(TTS_URL, data=body, method="POST")
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", accept)

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            ttfb = (time.perf_counter() - t0) * 1000
            audio = resp.read()
            total = (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        if exc.code in (401, 403):
            fail("Rime rejected the API key (HTTP %d)" % exc.code,
                 "Check RIME_API_KEY in .env is a live key.")
        fail("Rime returned HTTP %d for %s: %s" % (exc.code, accept, detail))
    except Exception as exc:
        fail("request to Rime failed: %s" % exc)

    if not audio:
        fail("Rime returned an empty body for %s" % accept)

    bps = 2 if accept == "audio/L16" else 1
    dur = len(audio) / bps / rate * 1000

    os.makedirs("out", exist_ok=True)
    if accept == "audio/L16":
        path = "out/preflight_%s.wav" % label
        open(path, "wb").write(wav_bytes(audio, rate))
    else:
        path = "out/preflight_%s.ulaw" % label
        open(path, "wb").write(audio)

    ok("%-9s %-12s %6d bytes  ttfb %6.0f ms  total %6.0f ms  audio %6.0f ms  -> %s"
       % (label, accept, len(audio), ttfb, total, dur, path))
    return ttfb


def main():
    load_env()
    print("\nRime preflight - %s / %s / %s\n" % (MODEL, SPEAKER, LANG))

    # Catalog first: it needs no key, so the config can be validated
    # while someone is still fetching credentials.
    check_catalog()

    key = os.environ.get("RIME_API_KEY", "").strip()
    if not key or key == "your_rime_api_key_here":
        fail("RIME_API_KEY is not set",
             "cp .env.example .env  then paste your key into .env")
    ok("RIME_API_KEY present (%d chars, ...%s)" % (len(key), key[-4:]))

    ttfbs = [synth(key, acc, rate, label) for acc, rate, _, label in FORMATS]

    print("\n  PREFLIGHT PASSED. Median TTFB %.0f ms.\n" % sorted(ttfbs)[len(ttfbs) // 2])
    print("  Listen to out/preflight_browser.wav before going further -")
    print("  if the voice is wrong for a 2am distress line, change SPEAKER now, not at 22:00.\n")


if __name__ == "__main__":
    main()
