import io
import json
import os
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch
import brain
import server
from test_workflow import FastAudio

class ConversationTests(unittest.TestCase):
    def test_openai_receives_heard_history_and_exact_model(self):
        history=[('user','My exams are tomorrow.'),('agent','That sounds stressful. [interrupted mid-sentence]'),
                 ('user','What did I tell you about my exams?')]
        response={'status':'completed','output':[{'type':'message','content':[
            {'type':'output_text','text':'You said your exams are tomorrow. What feels hardest right now?'}]}]}
        captured=[]
        def fake(req,timeout):
            captured.append(json.loads(req.data)); return io.BytesIO(json.dumps(response).encode())
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only', 'LLM_MODEL':'gpt-4.1-mini-2025-04-14'}), patch('urllib.request.urlopen',side_effect=fake):
            answer=brain.OpenAIBrain().respond(history)
        self.assertIn('tomorrow',answer['reply'])
        self.assertEqual(captured[0]['input'],[{'role':'assistant' if who=='agent' else 'user','content':text} for who,text in history])
        self.assertEqual(captured[0]['model'],'gpt-4.1-mini-2025-04-14')
        self.assertFalse(captured[0]['store'])
        self.assertNotIn('previous_response_id',captured[0])

    def test_tool_result_is_grounded_and_no_second_tool_call(self):
        data={'status':'completed','output':[{'type':'function_call','name':'lookup_slots','arguments':'{"preference":"evening"}'}]}
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}), patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
            self.assertEqual(brain.OpenAIBrain().respond([('user','evening appointment')]),{'lookup':'evening'})
        captured=[]
        response={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'Six in the evening is available in the demo.'}]}]}
        def fake(req,timeout):
            captured.append(json.loads(req.data)); return io.BytesIO(json.dumps(response).encode())
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}), patch('urllib.request.urlopen',side_effect=fake):
            brain.OpenAIBrain().respond([('user','evening appointment')],{'spoken_time':'six in the evening','synthetic':True})
        self.assertIn('six in the evening',captured[0]['instructions']); self.assertNotIn('tools',captured[0])

    def test_missing_key_does_not_silently_use_script(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}):
            with self.assertRaisesRegex(brain.BrainError,'OPENAI_API_KEY'):
                brain.OpenAIBrain().respond([('user','hi')])

    def test_quota_error_does_not_expose_provider_body(self):
        error=urllib.error.HTTPError('https://api.openai.com/v1/responses',429,'quota',{},io.BytesIO(b'private data'))
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}), patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaisesRegex(brain.BrainError,'quota and billing') as result:
                brain.OpenAIBrain().respond([('user','hi')])
        self.assertNotIn('private',str(result.exception))

    def test_cancelled_model_response_never_reaches_tts(self):
        entered=threading.Event(); release=threading.Event()
        class SlowBrain:
            provider='TEST'; model='test'
            def respond(self,*a,**kw):
                entered.set(); release.wait(1); return {'reply':'obsolete words'}
        s=server.Session(client=FastAudio(),brain_client=SlowBrain())
        old=s.submit('hi','1'); self.assertTrue(entered.wait(1)); s.interrupt(old); release.set()
        time.sleep(.03)
        self.assertIsNone(s.audio); self.assertIsNone(s.led.turn)
        self.assertNotIn('obsolete',s.led.transcript())

    def test_old_preference_does_not_force_new_lookup(self):
        class ChatBrain:
            provider='TEST'; model='test'
            def respond(self,*a,**kw): return {'reply':'You mentioned exams. How did they go?'}
        s=server.Session(client=FastAudio(),brain_client=ChatBrain()); s.preference='morning'
        s.submit('I finished my exams','1'); deadline=time.monotonic()+1
        while s.status not in ('ready','error') and time.monotonic()<deadline: time.sleep(.005)
        self.assertEqual(s.status,'ready'); self.assertIn('exams',s.audio['full_text'])
        self.assertFalse(any(e['kind']=='tool_dispatch' for e in s.events))

if __name__=='__main__': unittest.main()
