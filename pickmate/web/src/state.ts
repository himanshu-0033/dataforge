export type Mode = 'fixture' | 'live';
export type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'paused' | 'disconnected';
export interface EventRecord { seq:number; type:string; utc:string; monotonic_ms:number; clock_domain:string; session_id:string; task_id:string|null; task_version:number|null; response_epoch:number; data:Record<string,unknown> }
export interface InventoryItem { sku:string; name:string; bin:string; available:number; aliases?:string[]; attributes?:Record<string,string> }
export interface Task { task_id:string; task_version:number; item:{sku:string;name:string;bin:string;available:number}; quantity:number; status:string; operation_id:string|null }
export interface Speech { response_id:string; response_epoch:number; task_version:number|null; text:string; status:string; allow_while_paused?:boolean }
export interface Provider { name:string; status:string; model:string|null; speaker:string|null; language:string|null; endpoint:string|null }
export interface HistoryItem { operation_id?:string; task_id?:string; item?:{sku:string;name:string}; sku?:string; name?:string; quantity:number; bin?:string; committed_at?:string; status?:string }
export interface Snapshot { revision?:number; session_id:string; room:string; mode:Mode; ended:boolean; paused:boolean; resolving:boolean; response_epoch:number; task:Task|null; speech:Speech|null; provider:Provider; events:EventRecord[]; history:HistoryItem[]; inventory:InventoryItem[] }
export interface SessionState { snapshot:Snapshot|null; lastSeq:number; revision:number }
export interface TranscriptRow { key:string; speaker:'Worker'|'PickMate'; text:string; utc:string; status:string; evidence:string }
export const initialSessionState: SessionState = { snapshot:null, lastSeq:-1, revision:-1 };
export function mergeEvents(a:EventRecord[], b:EventRecord[]) { return [...new Map([...a,...b].map(e=>[e.seq,e])).values()].sort((x,y)=>x.seq-y.seq); }
export function acceptSnapshot(current:SessionState, incoming:Snapshot):SessionState {
  const maxSeq = incoming.events.reduce((n,e)=>Math.max(n,e.seq), -1);
  const revision=incoming.revision??maxSeq;
  if (revision < current.revision || (revision === current.revision && incoming.response_epoch < (current.snapshot?.response_epoch ?? -1))) return current;
  return {snapshot:{...incoming,events:mergeEvents(current.snapshot?.events ?? [],incoming.events)},lastSeq:Math.max(current.lastSeq,maxSeq),revision};
}
export function voiceState(s:Snapshot|null, liveConnected:boolean):VoiceState {
  if (!s || s.ended || (s.mode==='live' && !liveConnected)) return s ? 'disconnected' : 'idle';
  if (s.paused) return 'paused';
  if (s.speech?.status === 'playing') return 'speaking';
  if (s.resolving || ['generated','queued'].includes(s.speech?.status ?? '')) return 'thinking';
  return 'listening';
}
export function buildTranscript(events:EventRecord[]):TranscriptRow[]{
  const rows=new Map<string,TranscriptRow>();
  for(const event of [...events].sort((a,b)=>a.seq-b.seq)){
    const data=event.data;const text=String(data.text??data.transcript??'').trim();
    if(['final_transcript','transcript_final'].includes(event.type)&&text){rows.set(`worker-${event.seq}`,{key:`worker-${event.seq}`,speaker:'Worker',text,utc:event.utc,status:'final',evidence:'Final transcript'});continue}
    const responseId=String(data.response_id??'');if(!responseId)continue;const key=`assistant-${responseId}`;const existing=rows.get(key);
    if(['speech_generated','speech_queued','assistant_text'].includes(event.type)&&text){rows.set(key,{key,speaker:'PickMate',text,utc:event.utc,status:event.type==='speech_generated'?'generated':'queued',evidence:'Generated; delivery unverified'});continue}
    if(!existing)continue;
    if(event.type==='speech_started')rows.set(key,{...existing,status:'playing',evidence:'Playback estimate'});
    if(event.type==='speech_interrupted'||event.type==='speech_stopped'){
      const status=String(data.status??(event.type==='speech_interrupted'?'interrupted':'stopped'));
      rows.set(key,{...existing,status,evidence:status==='completed'?'Playback completion estimate':'Playback estimate'});
    }
    if(event.type==='speech_completed')rows.set(key,{...existing,status:'completed',evidence:'Playback completion estimate'});
  }
  return [...rows.values()].slice(-16);
}
