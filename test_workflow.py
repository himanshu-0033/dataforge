import threading
import time
import unittest
from unittest.mock import patch
import ledger
import server
import brain

class FastAudio:
    provider = 'TEST AUDIO'
    def synth(self, text, fmt='L16'):
        return b'\0\0' * 160, 10, 0

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        factory=patch.object(brain, 'make_brain', return_value=brain.ScriptedBrain())
        factory.start(); self.addCleanup(factory.stop)

    def wait_ready(self, session):
        deadline=time.monotonic()+2
        while session.status not in ('ready','error') and time.monotonic()<deadline:
            time.sleep(.005)
        self.assertEqual(session.status,'ready',session.error)

    def test_partial_segment_is_not_committed(self):
        turn=ledger.Turn(1,['Hello world','Second segment'])
        turn.set_timing(0,1000); turn.set_timing(1,1000)
        self.assertEqual(turn.heard(200),'')
        self.assertEqual(turn.heard(1500),'Hello world')
        self.assertEqual(turn.heard(2000),turn.full_text)

    def test_completion_is_idempotent_and_fenced(self):
        s=server.Session(client=FastAudio()); epoch=s.submit('hello','1'); self.wait_ready(s)
        self.assertFalse(s.complete(epoch-1)); self.assertTrue(s.complete(epoch))
        self.assertFalse(s.complete(epoch))
        self.assertEqual(len([x for x in s.led.history if x[0]=='agent']),1)

    def test_delayed_lookup_can_be_corrected(self):
        with patch.object(server,'TOOL_DELAY_S',.1):
            s=server.Session(client=FastAudio()); old=s.submit('morning appointment','1')
            self.assertNotEqual(s.status,'ready')
            deadline=time.monotonic()+1
            while not any(e['kind']=='tool_dispatch' for e in s.events) and time.monotonic()<deadline:
                time.sleep(.001)
            s.interrupt(old); s.submit('actually evening only','2'); self.wait_ready(s)
            self.assertIn('six in the evening',s.audio['full_text'])
            self.assertNotIn('ten in the morning',s.audio['full_text'])
            self.assertEqual([t for who,t in s.led.history if who=='user'],['morning appointment','actually evening only'])
            self.assertTrue(any(e['kind']=='tool_cancelled' for e in s.events))

    def test_synthesis_result_cannot_resurrect(self):
        entered=threading.Event(); release=threading.Event()
        class Blocking(FastAudio):
            def synth(self,*args,**kwargs):
                entered.set(); release.wait(1); return super().synth(*args,**kwargs)
        s=server.Session(client=Blocking()); old=s.submit('hello','1')
        self.assertTrue(entered.wait(1)); s.interrupt(old); release.set(); time.sleep(.05)
        self.assertIsNone(s.audio); self.assertIsNone(s.led.turn)
        self.assertEqual(s.status,'listening')

    def test_sessions_and_duplicate_request(self):
        a=server.Session(client=FastAudio()); b=server.Session(client=FastAudio())
        old=a.submit('hello','same'); self.wait_ready(a)
        self.assertEqual(a.submit('hello','same'),old)
        self.assertEqual(len(a.led.history),1); self.assertEqual(b.led.history,[])

    def test_handoff_is_honest_and_persistent(self):
        s=server.Session(client=FastAudio()); e=s.submit('I want to die','1'); self.wait_ready(s)
        self.assertEqual(s.handoff,'unavailable_demo')
        self.assertIn('cannot connect',s.audio['full_text'])
        s.complete(e); s.submit('morning appointment','2'); self.wait_ready(s)
        self.assertIn('cannot connect',s.audio['full_text'])

    def test_provider_failure_recovers(self):
        class Broken(FastAudio):
            def synth(self,*a,**kw): raise RuntimeError('private detail')
        s=server.Session(client=Broken()); s.submit('hello','1')
        deadline=time.monotonic()+1
        while s.status!='error' and time.monotonic()<deadline: time.sleep(.005)
        self.assertEqual(s.status,'error'); self.assertNotIn('private',s.error)
        s.client=FastAudio(); s.submit('hello','2'); self.wait_ready(s)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.factory=patch.object(brain, 'make_brain', return_value=brain.ScriptedBrain())
        cls.factory.start()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.base = 'http://127.0.0.1:%d' % cls.http.server_port
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        cls.factory.stop()

    def request(self, path, body=None):
        import json
        import urllib.request
        import urllib.error
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base+path, data=data,
                                     headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def test_http_lifecycle_and_invalid_input(self):
        code, state = self.request('/api/reset', {})
        self.assertEqual(code, 200)
        sid = state['session_id']
        server.SESSIONS[sid].client = FastAudio()
        code, state = self.request('/api/say', {'session_id':sid, 'text':'hello', 'request_id':'1'})
        self.assertEqual(code, 200)
        deadline = time.monotonic()+1
        while state['status'] != 'ready' and time.monotonic()<deadline:
            _, state = self.request('/api/state?session_id='+sid)
        self.assertEqual(state['status'], 'ready')
        code, complete = self.request('/api/complete', {'session_id':sid, 'epoch':state['epoch']})
        self.assertEqual(code, 200)
        self.assertIn('agent:', complete['transcript'])
        code, _ = self.request('/api/bargein', {'session_id':sid, 'epoch':state['epoch'], 'played_ms':'NaN'})
        self.assertEqual(code, 400)
        code, _ = self.request('/api/say', {'session_id':{}, 'text':'hello', 'request_id':'bad'})
        self.assertEqual(code, 400)
        code, _ = self.request('/api/end', {'session_id':sid})
        self.assertEqual(code, 200)
        code, _ = self.request('/api/state?session_id='+sid)
        self.assertEqual(code, 404)

if __name__=='__main__': unittest.main()

