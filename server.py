"""Voice agent server.  Run: make dev   (or python server.py)  ->  http://localhost:8765

Deliberately stdlib-only HTTP, no WebSocket. Rationale: barge-in must stop playback
at the SPEAKER, so cancellation is client-side and must not wait for a server round
trip. The server is only asked to reconcile state afterwards. That split is the
honest architecture for this claim, and it happens to need no dependencies.

Endpoints
  GET  /                 the client
  POST /api/reset        new session; body {mode: "ledger"|"naive"}
  POST /api/say          body {text} -> agent turn, synthesized, with segment timings
  POST /api/bargein      body {played_ms, user_text} -> heard/unheard reconciliation
  GET  /api/state        transcript + what the agent believes it said
"""
import base64
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ledger
import rime
from preflight import load_env

PORT = int(os.environ.get("PORT", "8765"))
TOOL_DELAY_S = float(os.environ.get("TOOL_DELAY_S", "3.0"))  # the deliberate stress

SAFETY_CHECK = "are you safe right now"

_lock = threading.Lock()
STATE = {
    "led": None,
    "turn": None,
    "client": None,
    "mode": "ledger",
    "fmt": "L16",
    "tool": None,       # {"epoch":int, "ready_at":float, "payload":dict}
    "events": [],
}


def log(kind, detail):
    STATE["events"].append({"t": round(time.time() % 10000, 2), "kind": kind, "detail": detail})
    STATE["events"][:] = STATE["events"][-40:]


def brain(user_text, led):
    """Decide what the agent says next.

    Default is a scripted, deterministic brain: for a distress line, predictable
    behaviour beats a clever one, and it keeps the demo reproducible for judges.
    Set ANTHROPIC_API_KEY to route through Claude instead.
    """
    heard_ctx = led.transcript()
    if ledger.risk_signal(user_text):
        return ("I'm really glad you told me that. You matter, and I want to get "
                "you to a person right now. I'm connecting you to the on-call "
                "counsellor - stay with me on the line.")

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        try:
            return _claude(user_text, heard_ctx, key)
        except Exception as exc:
            log("brain_fallback", str(exc)[:80])

    low = user_text.lower()
    if any(w in low for w in ("later", "week", "another", "different")):
        return ("That's completely fine. I can look at later in the week instead. "
                "Would a morning or an evening suit you better?")
    if any(w in low for w in ("no", "don't", "not yet", "wait")):
        return ("No pressure at all, nothing is booked. We can just talk. "
                "What's been the hardest part this week?")
    if "again" in low or "repeat" in low:
        return "Of course. Let me go through those slots again, slower this time."
    return ("Okay, I hear you, and I'm glad you called. I've got three counselling "
            "slots free tomorrow, there's one at ten in the morning, one at half "
            "past two, and a late one at six in the evening. "
            "Before we sort that out, are you safe right now?")


def _claude(user_text, heard_ctx, key):
    """Optional LLM path. The context we send is the HEARD transcript - that is the
    whole point: the model is never told it said something the caller did not hear."""
    import urllib.request
    body = json.dumps({
        "model": "claude-opus-5",
        "max_tokens": 160,
        "system": ("You are a calm triage line for a university student in distress. "
                   "You are NOT a therapist and must not claim to be. Two or three "
                   "short spoken sentences, no lists, no markdown. If there is any "
                   "risk to life, hand off to a human counsellor immediately.\n\n"
                   "Conversation so far (only what the caller ACTUALLY HEARD):\n" + heard_ctx),
        "messages": [{"role": "user", "content": user_text}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body)
    req.add_header("x-api-key", key)
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["content"][0]["text"].strip()


def ensure_session(mode=None):
    if STATE["led"] is None or (mode and mode != STATE["mode"]):
        STATE["mode"] = mode or STATE["mode"]
        STATE["led"] = ledger.Ledger(mode=STATE["mode"])
        STATE["turn"] = None
        STATE["tool"] = None
        STATE["events"] = []
        log("session", "mode=%s" % STATE["mode"])
    if STATE["client"] is None:
        STATE["client"] = rime.RimeClient()
    return STATE["led"]


def do_say(payload):
    led = ensure_session()
    user_text = (payload.get("text") or "").strip()
    if user_text:
        led.user_said(user_text)

    text = brain(user_text, led)
    turn = led.start_turn(text)
    STATE["turn"] = turn

    # Dispatch the slot lookup with a deliberate delay, tagged with this turn's epoch.
    STATE["tool"] = {"epoch": led.epoch, "ready_at": time.time() + TOOL_DELAY_S,
                     "payload": {"slots": ["10:00", "14:30", "18:00"]}}
    log("tool_dispatch", "epoch=%d delay=%.1fs" % (led.epoch, TOOL_DELAY_S))

    t0 = time.perf_counter()
    ttfbs = STATE["client"].synth_turn(turn, fmt=STATE["fmt"])
    synth_ms = (time.perf_counter() - t0) * 1000
    log("synth", "%d segments, %.0f ms audio" % (len(turn.segments), turn.total_ms))

    _, rate, _ = rime.FORMATS[STATE["fmt"]]
    return {
        "epoch": turn.epoch,
        "mode": STATE["mode"],
        "full_text": turn.full_text,
        "total_ms": turn.total_ms,
        "sample_rate": rate,
        "synth_ms": round(synth_ms),
        "ttfb_ms": [round(x) for x in ttfbs],
        "segments": [{
            "text": s.text,
            "char_start": s.char_start,
            "char_end": s.char_end,
            "t_start_ms": round(s.t_start_ms, 1),
            "dur_ms": round(s.dur_ms, 1),
            "audio_b64": base64.b64encode(s.audio).decode(),
        } for s in turn.segments],
    }


def do_bargein(payload):
    led = ensure_session()
    turn = STATE["turn"]
    played_ms = float(payload.get("played_ms") or 0)
    user_text = (payload.get("user_text") or "").strip()
    t_stop_ms = payload.get("t_stop_ms")  # measured at the speaker, by the client

    generated = turn.full_text if turn else ""
    res = led.barge_in(played_ms)
    log("bargein", "played=%.0fms heard=%d chars" % (played_ms, len(res["heard"])))

    # The delayed tool now resolves - for a turn that no longer exists.
    stale_used = False
    tool = STATE["tool"]
    if tool:
        accepted = led.accept_tool_result(tool["epoch"], tool["payload"])
        stale_used = accepted and tool["epoch"] < led.epoch
        log("tool_result", "epoch=%d %s" % (tool["epoch"], "USED" if accepted else "FENCED"))
        STATE["tool"] = None

    if user_text:
        led.user_said(user_text)

    believes = led.agent_believes_said()
    heard_safety = SAFETY_CHECK in res["heard"].lower()
    return {
        "mode": STATE["mode"],
        "played_ms": round(played_ms),
        "t_stop_ms": t_stop_ms,
        "generated": generated,
        "heard": res["heard"],
        "unheard": res["unheard"],
        "believes": believes,
        "epoch": res["epoch"],
        "stale_result_used": stale_used,
        "escalated": ledger.risk_signal(user_text) or ledger.risk_signal(res["heard"]),
        "false_safety_claim": (SAFETY_CHECK in believes.lower()) and not heard_safety,
        "dropped_results": len(led.dropped_results),
        "events": STATE["events"][-12:],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            led = STATE["led"]
            return self._send(200, {
                "mode": STATE["mode"],
                "transcript": led.transcript() if led else "",
                "believes": led.agent_believes_said() if led else "",
                "events": STATE["events"][-12:],
            })
        path = "static/index.html" if self.path in ("/", "") else "static" + self.path
        path = os.path.normpath(path)
        if not path.startswith("static") or not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ctype = "text/html" if path.endswith(".html") else "text/plain"
        self._send(200, open(path, "rb").read(), ctype + "; charset=utf-8")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})

        try:
            with _lock:
                if self.path == "/api/reset":
                    STATE["led"] = None
                    ensure_session(payload.get("mode"))
                    return self._send(200, {"ok": True, "mode": STATE["mode"]})
                if self.path == "/api/say":
                    return self._send(200, do_say(payload))
                if self.path == "/api/bargein":
                    return self._send(200, do_bargein(payload))
        except rime.RimeError as exc:
            return self._send(503, {"error": str(exc)})
        except Exception as exc:
            return self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
        self._send(404, {"error": "not found"})


if __name__ == "__main__":
    load_env()
    if not os.environ.get("RIME_API_KEY", "").strip():
        print("\n  RIME_API_KEY is not set. Run: python preflight.py\n")
    print("  heard-ledger agent on http://localhost:%d  (tool delay %.1fs)\n" % (PORT, TOOL_DELAY_S))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
