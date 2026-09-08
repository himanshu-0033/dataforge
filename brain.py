"""OpenAI conversation engine. Rime remains the only production speech provider."""
import json
import os
import re
import urllib.error
import urllib.request

SYSTEM = """You are Heard, an AI voice assistant in a student-support prototype.
Have a natural, warm conversation: respond to what the caller just said, remember
relevant details, use contractions, and ask at most one useful follow-up question.
Keep each spoken reply to one or two short sentences, usually under 45 words.
Do not repeatedly greet, repeat a safety checklist, or push appointments when the
caller wants to talk. Acknowledge a correction without repeating the old answer.
You are an AI, not a human or therapist. Do not diagnose or provide treatment.
Only assistant messages in the supplied history were committed as heard. Text
marked interrupted may be incomplete; never assume the rest was delivered.
Appointments are synthetic and nothing can actually be booked. Only offer a time
returned by lookup_slots. Call that tool only for an appointment request or a
correction to an active appointment request, not a casual mention of morning.
Do not claim a booking or a human transfer. No live counsellor connection exists.
If someone appears in immediate danger, prioritize getting support from a real
person or local emergency services, without inventing contact details.
Do not claim capabilities beyond conversation and synthetic appointment lookup.
Return plain spoken English, no markdown, lists, stage directions or sound effects.
"""
LOOKUP = {
    'type': 'function', 'name': 'lookup_slots',
    'description': 'Look up synthetic appointments for tomorrow. No real booking. Use for explicit requests or changed preferences.',
    'parameters': {'type':'object', 'properties':{'preference':{'type':'string',
                    'enum':['morning','afternoon','evening','any']}},
                   'required':['preference'], 'additionalProperties':False},
    'strict': True,
}


class BrainError(RuntimeError):
    pass


def configured():
    key = os.environ.get('OPENAI_API_KEY','').strip()
    return bool(key and not key.startswith('your_'))


class OpenAIBrain:
    provider = 'OpenAI'
    def __init__(self):
        self.model = (os.environ.get('LLM_MODEL') or os.environ.get('OPENAI_MODEL') or 'gpt-4.1-mini-2025-04-14').strip()

    def respond(self, history, tool_result=None):
        if not configured():
            raise BrainError('Add OPENAI_API_KEY to the local .env file and restart the server to enable natural conversation.')
        messages = [{'role':'assistant' if who=='agent' else 'user', 'content':text}
                    for who,text in history[-40:]]
        instructions = SYSTEM
        if tool_result is not None:
            # Only application-owned tool facts enter instructions. Caller text
            # remains in user messages, never promoted to system instructions.
            instructions += '\nCurrent lookup result (synthetic, not booked): '+json.dumps(tool_result)
        body = {'model':self.model, 'instructions':instructions, 'input':messages,
                'max_output_tokens':240, 'store':False}
        if tool_result is None:
            body['tools']=[LOOKUP]
            body['parallel_tool_calls']=False
        req=urllib.request.Request('https://api.openai.com/v1/responses',
            data=json.dumps(body).encode(), method='POST', headers={
                'Authorization':'Bearer '+os.environ['OPENAI_API_KEY'].strip(),
                'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                data=json.load(response)
        except urllib.error.HTTPError as exc:
            # Never echo provider bodies, prompts, or credentials into public logs.
            hints={401:'Check OPENAI_API_KEY.', 403:'Check model access.',
                   429:'Check OpenAI API quota and billing, then retry.'}
            raise BrainError('OpenAI request failed (HTTP %d). %s' %
                             (exc.code,hints.get(exc.code,'Please retry.'))) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise BrainError('Could not reach the conversation service. Please retry.') from exc
        if data.get('status') != 'completed':
            raise BrainError('The conversation response was incomplete. Please retry.')
        for item in data.get('output',[]):
            if item.get('type')=='function_call':
                if tool_result is not None or item.get('name')!='lookup_slots':
                    raise BrainError('The conversation requested an unsupported action.')
                try:
                    args=json.loads(item['arguments'])
                    preference=args['preference']
                    if preference not in ('morning','afternoon','evening','any'):
                        raise ValueError()
                except (KeyError,ValueError,TypeError) as exc:
                    raise BrainError('Could not understand the appointment preference. Please try again.') from exc
                return {'lookup':preference}
        text=' '.join(part.get('text','') for item in data.get('output',[])
                      if item.get('type')=='message' for part in item.get('content',[])
                      if part.get('type')=='output_text').strip()
        if not text:
            raise BrainError('The conversation service returned no spoken reply. Please retry.')
        return {'reply':text}


class ScriptedBrain:
    """Explicit offline test mode; never presented as an OpenAI conversation."""
    provider='SCRIPTED DEMO (not AI conversation)'
    model='scripted'
    def respond(self, history, tool_result=None):
        if tool_result is not None:
            return {'reply':'The demo has a slot at %s tomorrow. Nothing has been booked.' % tool_result['spoken_time']}
        text=next((text for who,text in reversed(history) if who=='user'),'').lower()
        if re.search(r'\b(cancel|stop)\b|don.t (?:want to )?book',text):
            return {'reply':'The demo lookup is cancelled. Nothing has been booked.'}
        times=re.findall(r'\b(morning|afternoon|evening)\b',text)
        if times:
            return {'lookup':times[-1]}
        if re.search(r'\b(slot|appointment|book|counselling)\b',text):
            return {'reply':'Would a morning, afternoon, or evening demo appointment suit you?'}
        if re.search(r'\b(hi|hello|hey)\b',text):
            return {'reply':"Hi, I'm Heard, an AI voice assistant. What's on your mind?"}
        return {'reply':"This is the scripted test mode. Connect OpenAI to have an open conversation with me."}


def make_brain():
    provider=os.environ.get('BRAIN_PROVIDER','openai').lower().strip()
    if provider=='scripted':
        return ScriptedBrain()
    if provider!='openai':
        raise BrainError('Set BRAIN_PROVIDER to openai or scripted.')
    return OpenAIBrain()
