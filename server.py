"""Local voice prototype: isolated sessions, asynchronous work, epoch-fenced playback."""
import base64
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import ledger
import brain
import rime
from preflight import load_env

ROOT = Path(__file__).resolve().parent
load_env(ROOT / '.env')
PORT = int(os.environ.get('PORT', '8765'))
TOOL_DELAY_S = float(os.environ.get('TOOL_DELAY_S', '3'))
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()


class Session:
    def __init__(self, mode='ledger', client=None, brain_client=None):
        self.id = uuid.uuid4().hex
        self.lock = threading.RLock()
        self.led = ledger.Ledger(mode)
        self.client = client
        self.brain = brain_client or brain.make_brain()
        self.cancel = threading.Event()
        self.status = 'listening'
        self.audio = None
        self.events = []
        self.error = None
        self.preference = None
        self.handoff = 'not_requested'
        self.last_cut = None
        self.requests = set()
        self.touched = time.monotonic()

    def configuration(self):
        notes = []
        if self.brain.provider == 'OpenAI' and not brain.configured():
            notes.append('OpenAI is not configured: add OPENAI_API_KEY to .env and restart.')
        if os.environ.get('RIME_DEV_STUB','').strip() in ('1','true','yes'):
            notes.append('Audio test stub enabled: it emits a hum, not speech. Set RIME_DEV_STUB=0 for Rime.')
        elif not os.environ.get('RIME_API_KEY','').strip() or os.environ.get('RIME_API_KEY','').startswith('your_'):
            notes.append('Rime is not configured: add RIME_API_KEY to .env and restart.')
        return notes

    def log(self, kind, detail):
        self.events.append({'kind': kind, 'detail': detail, 't': round(time.monotonic(), 3)})
        self.events = self.events[-80:]

    def snapshot(self):
        with self.lock:
            self.touched = time.monotonic()
            return dict(session_id=self.id, epoch=self.led.epoch, mode=self.led.mode,
                        status=self.status, audio=self.audio, error=self.error,
                        transcript=self.led.transcript(), believes=self.led.agent_believes_said(),
                        events=list(self.events), dropped_results=len(self.led.dropped_results),
                        handoff=self.handoff, last_cut=self.last_cut,
                        brain=self.brain.provider, model=self.brain.model,
                        configuration=self.configuration(),
                        provider=self.client.provider if self.client else 'RIME (not connected)')

    def interrupt(self, epoch, played_ms=0):
        with self.lock:
            if epoch != self.led.epoch:
                return False
            self.cancel.set()
            turn = self.led.turn
            if turn:
                # An unfinished synthesis has no playable audio.
                position = played_ms if self.audio else 0
                self.last_cut = dict(generated=turn.full_text, **self.led.barge_in(position))
            else:
                self.led.epoch += 1
            self.audio = None
            self.status = 'listening'
            self.log('interrupt', 'Old work invalidated; waiting for final caller transcript')
            return True

    def submit(self, text, request_id):
        with self.lock:
            if request_id in self.requests:
                return self.led.epoch
            if self.status not in ('listening', 'error'):
                raise ValueError('Interrupt or finish the current turn before submitting')
            self.requests.add(request_id)
            self.led.user_said(text)
            self.led.epoch += 1
            epoch = self.led.epoch
            self.cancel = threading.Event()
            cancel = self.cancel
            self.error = None
            self.audio = None
            self.status = 'working'
            # A detected risk stays active for this session. This is a limited
            # keyword gate, not a clinically validated classifier.
            if ledger.risk_signal(text):
                self.handoff = 'unavailable_demo'
            preference = self.preference
            self.log('user', text)
            threading.Thread(target=self._work, args=(epoch, cancel, text, preference), daemon=True).start()
            return epoch

    def _work(self, epoch, cancel, text, preference):
        try:
            if self.handoff != 'not_requested':
                reply = ('Thank you for telling me. This demo cannot connect you to a counsellor. '
                         'Please contact a trusted person or local emergency support if you are in immediate danger.')
            else:
                with self.lock:
                    history = list(self.led.history)
                decision = self.brain.respond(history)
                if cancel.is_set():
                    return
                if 'lookup' in decision:
                    preference = decision['lookup']
                    with self.lock:
                        if epoch != self.led.epoch:
                            return
                        self.preference = preference
                        self.log('tool_dispatch', 'Synthetic slot lookup; %.1fs delay; epoch %d' % (TOOL_DELAY_S, epoch))
                    if cancel.wait(TOOL_DELAY_S):
                        with self.lock:
                            self.log('tool_cancelled', 'Lookup cancelled for epoch %d' % epoch)
                        return
                    slots = {'morning': 'ten in the morning', 'afternoon': 'half past two in the afternoon',
                             'evening': 'six in the evening', 'any': 'ten in the morning'}
                    result = {'preference':preference, 'spoken_time':slots[preference], 'synthetic':True, 'booked':False}
                    with self.lock:
                        if not self.led.accept_tool_result(epoch, result) or cancel.is_set():
                            self.log('tool_fenced', 'Obsolete lookup result rejected')
                            return
                    decision = self.brain.respond(history, tool_result=result)
                reply = decision['reply']
            with self.lock:
                if cancel.is_set() or epoch != self.led.epoch:
                    return
                turn = ledger.Turn(epoch, [part for sentence in re.split(r'(?<=[.!?])\s+', reply)
                                           for part in ledger.split_segments(sentence, max_chars=180)])
                self.led.turn = turn
                self.status = 'synthesizing'
            client = self.client or rime.make_client()
            with self.lock:
                self.client = client
            started = time.perf_counter()
            for i, segment in enumerate(turn.segments):
                if cancel.is_set():
                    return
                audio, duration, _ = client.synth(segment.text, fmt='L16')
                with self.lock:
                    if cancel.is_set() or epoch != self.led.epoch:
                        self.log('synthesis_fenced', 'In-flight audio discarded for epoch %d' % epoch)
                        return
                    turn.set_timing(i, duration, audio)
            with self.lock:
                if cancel.is_set() or epoch != self.led.epoch:
                    return
                self.audio = dict(epoch=epoch, full_text=turn.full_text, total_ms=turn.total_ms,
                    provider=client.provider, sample_rate=16000,
                    synth_ms=round((time.perf_counter()-started)*1000),
                    segments=[dict(text=s.text, dur_ms=s.dur_ms, t_start_ms=s.t_start_ms,
                                   audio_b64=base64.b64encode(s.audio).decode()) for s in turn.segments])
                self.status = 'ready'
                self.log('audio_ready', 'Waiting for client playback acknowledgement')
        except Exception as exc:
            with self.lock:
                if epoch == self.led.epoch and not cancel.is_set():
                    self.error = str(exc) if isinstance(exc, (rime.RimeError, brain.BrainError)) else 'Speech service failed; please retry.'
                    self.status = 'error'
                    self.led.turn = None
                    self.audio = None
                    self.log('error', self.error)

    def complete(self, epoch):
        with self.lock:
            if epoch != self.led.epoch or self.audio is None:
                return False
            self.led.complete_turn()
            self.audio = None
            self.status = 'listening'
            self.log('playback_complete', 'Full response committed once')
            return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, content_type='application/json'):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def session(self, sid):
        if not isinstance(sid, str):
            raise ValueError('Invalid session identifier')
        with SESSIONS_LOCK:
            session = SESSIONS.get(sid)
        if not session:
            raise ValueError('Session expired or missing; start a new session')
        return session

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/state':
            try:
                return self.send(200, self.session(parse_qs(parsed.query).get('session_id', [''])[0]).snapshot())
            except ValueError as exc:
                return self.send(404, {'error': str(exc)})
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript')}
        if parsed.path not in files:
            return self.send(404, {'error': 'Not found'})
        name, mime = files[parsed.path]
        self.send(200, (ROOT / 'static' / name).read_bytes(), mime+'; charset=utf-8')

    def do_POST(self):
        try:
            origin = self.headers.get('Origin')
            if origin and urlparse(origin).netloc != self.headers.get('Host'):
                return self.send(403, {'error': 'Cross-origin requests are not allowed'})
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 16384:
                return self.send(413, {'error': 'Request too large'})
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            if self.path == '/api/reset':
                mode = body.get('mode', 'ledger')
                if mode not in ('ledger', 'naive'):
                    raise ValueError('Invalid mode')
                with SESSIONS_LOCK:
                    for sid, old in list(SESSIONS.items()):
                        if time.monotonic()-old.touched > 3600 or sid == body.get('session_id'):
                            old.cancel.set()
                            del SESSIONS[sid]
                    if len(SESSIONS) >= 100:
                        return self.send(503, {'error': 'Session capacity reached'})
                    session = Session(mode)
                    SESSIONS[session.id] = session
                return self.send(200, session.snapshot())
            session = self.session(body.get('session_id'))
            if self.path == '/api/say':
                text = body.get('text')
                rid = body.get('request_id')
                if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                    raise ValueError('Provide 1-2000 characters of text')
                if not isinstance(rid, str) or not 1 <= len(rid) <= 100:
                    raise ValueError('Missing request identifier')
                session.submit(text.strip(), rid)
            elif self.path == '/api/bargein':
                played = float(body.get('played_ms', 0))
                if not math.isfinite(played) or played < 0:
                    raise ValueError('Invalid playback position')
                session.interrupt(body.get('epoch'), played)
            elif self.path == '/api/complete':
                session.complete(body.get('epoch'))
            elif self.path == '/api/end':
                session.interrupt(session.led.epoch)
                with SESSIONS_LOCK:
                    SESSIONS.pop(session.id, None)
                return self.send(200, {'ok': True})
            else:
                return self.send(404, {'error': 'Not found'})
            return self.send(200, session.snapshot())
        except (ValueError, TypeError) as exc:
            self.send(400, {'error': str(exc)})


if __name__ == '__main__':
    print('Heard Ledger: http://127.0.0.1:%d (synthetic appointments; no real handoff)' % PORT)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
