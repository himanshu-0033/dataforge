import { describe, expect, it } from 'vitest';
import { acceptSnapshot, buildTranscript, initialSessionState, mergeEvents, type Snapshot } from './state';

const snapshot = (seq: number): Snapshot => ({revision:seq,session_id:'s',room:'r',mode:'fixture',ended:false,paused:false,resolving:false,response_epoch:seq,task:null,speech:null,provider:{name:'fixture',status:'ready',model:null,speaker:null,language:'en',endpoint:null},events:[{seq,type:'tick',utc:'2026-01-01T00:00:00Z',monotonic_ms:seq,clock_domain:'server',session_id:'s',task_id:null,task_version:null,response_epoch:seq,data:{}}],history:[],inventory:[]});

describe('snapshot fencing', () => {
  it('rejects a late snapshot whose event sequence is older', () => {
    const newer = acceptSnapshot(initialSessionState, snapshot(7));
    expect(acceptSnapshot(newer, snapshot(5))).toBe(newer);
  });
  it('deduplicates and sorts overlapping event pages', () => {
    expect(mergeEvents(snapshot(3).events, [...snapshot(3).events, ...snapshot(4).events]).map(e => e.seq)).toEqual([3,4]);
  });
});

describe('transcript evidence',()=>{
  it('uses generated text and later marks the same response interrupted',()=>{
    const base=snapshot(1).events[0];
    const rows=buildTranscript([
      {...base,seq:1,type:'speech_generated',data:{response_id:'r1',text:'Pick six blue cartons.'}},
      {...base,seq:2,type:'speech_started',data:{response_id:'r1'}},
      {...base,seq:3,type:'speech_stopped',data:{response_id:'r1',status:'interrupted'}},
    ]);
    expect(rows).toEqual([{key:'assistant-r1',speaker:'PickMate',text:'Pick six blue cartons.',utc:base.utc,status:'interrupted',evidence:'Playback estimate'}]);
  });
  it('keeps generated speech visibly distinct from delivered speech',()=>{
    const base=snapshot(1).events[0];
    expect(buildTranscript([{...base,type:'speech_queued',data:{response_id:'r2',text:'Checking stock.'}}])[0]).toMatchObject({status:'queued',evidence:'Generated; delivery unverified'});
  });
});
