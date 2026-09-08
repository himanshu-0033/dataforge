const $ = id => document.getElementById(id);
let ctx, source, gain, stream, recognition, frame, restartTimer, flushTimer;
let session = null, epoch = 0, mode = 'ledger', active = false, playing = false;
let playStart = 0, current = null, busy = false, generation = 0, polling = false;
let mutation = Promise.resolve(), finalText = '', interimText = '', lastAudioEpoch = -1;
const log = message => { $('log').textContent = (message + '\n' + $('log').textContent).slice(0, 10000); };
const fail = error => { $('status').textContent = error.message; log(error.message); };
async function api(path, body) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({...body, session_id:session})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function render(state) {
  epoch = state.epoch;
  busy = ['working','synthesizing','ready'].includes(state.status);
  $('status').textContent = state.error || (playing ? 'Speaking — you can interrupt.' :
    busy ? 'Working — you can change or cancel your request.' : 'Listening — speak or type.');
  $('provPill').textContent = 'provider: ' + state.provider;
  $('provPill').style.color = state.provider.startsWith('STUB') ? 'var(--unheard)' : '';
  $('believes').textContent = state.believes || '—';
  $('epoch').textContent = epoch;
  $('flags').textContent = 'Rejected stale results: ' + state.dropped_results;
  $('handoff').textContent = state.handoff === 'unavailable_demo' ?
    'Human handoff unavailable: this prototype has no live counsellor connection.' : '';
  if (state.last_cut) $('heard').textContent = state.last_cut.heard || '(No complete segment confirmed)';
  $('log').textContent = state.events.map(e => e.kind + ': ' + e.detail).reverse().join('\n');
  $('btnBarge').disabled = !busy && !playing;
}
function stopAudio() {
  if (!playing) return 0;
  // Subtract the reported output pipeline latency; this remains an estimate.
  const latency = (ctx.baseLatency || 0) + (ctx.outputLatency || 0);
  const played = Math.max(0, Math.min(current.total_ms, (ctx.currentTime-playStart-latency)*1000));
  const t0 = performance.now();
  source.onended = null;
  gain.gain.cancelScheduledValues(ctx.currentTime);
  gain.gain.setValueAtTime(gain.gain.value, ctx.currentTime);
  gain.gain.linearRampToValueAtTime(0, ctx.currentTime+0.008);
  source.stop(ctx.currentTime+0.01);
  playing = false;
  $('tstop').textContent = (performance.now()-t0).toFixed(2) + ' ms';
  $('played').textContent = Math.round(played) + ' ms (estimated)';
  return played;
}
function interrupt() {
  if (!active || (!playing && !busy)) return mutation;
  const played = stopAudio(), oldEpoch = epoch, token = generation;
  busy = false;
  // Suppress old poll responses and audio until cancellation is acknowledged.
  lastAudioEpoch = Math.max(lastAudioEpoch, oldEpoch);
  $('status').textContent = 'Listening for your correction…';
  mutation = mutation.then(async () => {
    if (!active || token !== generation) return;
    const state = await api('/api/bargein', {epoch:oldEpoch, played_ms:played});
    if (token === generation) render(state);
  });
  mutation.catch(fail);
  return mutation;
}
async function submit(text) {
  text = text.trim();
  if (!active || !text) return;
  const token = generation;
  await interrupt();
  mutation = mutation.then(async () => {
    if (!active || token !== generation) return;
    const state = await api('/api/say', {text, request_id:crypto.randomUUID()});
    if (token === generation) render(state);
  });
  await mutation;
}
function play(turn) {
  current = turn;
  lastAudioEpoch = turn.epoch;
  const parts = turn.segments.map(segment => {
    const raw = atob(segment.audio_b64), samples = new Float32Array(raw.length / 2);
    for (let i=0; i<samples.length; i++) {
      let value = raw.charCodeAt(i*2) | raw.charCodeAt(i*2+1)<<8;
      if (value >= 32768) value -= 65536;
      samples[i] = value / 32768;
    }
    return samples;
  });
  const buffer = ctx.createBuffer(1, parts.reduce((n,p)=>n+p.length,0), turn.sample_rate);
  let offset=0;
  for (const part of parts) { buffer.copyToChannel(part,0,offset); offset+=part.length; }
  source=ctx.createBufferSource(); gain=ctx.createGain(); source.buffer=buffer;
  source.connect(gain).connect(ctx.destination);
  const token=generation, audioSource=source;
  playing=true; playStart=ctx.currentTime;
  source.onended=() => {
    if (!active || token!==generation || source!==audioSource || !playing) return;
    playing=false; busy=false;
    mutation=mutation.then(async()=>{
      const state=await api('/api/complete',{epoch:turn.epoch});
      if(token===generation) { render(state); $('heard').textContent=turn.full_text; }
    });
    mutation.catch(fail);
  };
  source.start();
  $('generated').textContent=turn.full_text;
  $('status').textContent='Speaking — you can interrupt.';
  $('btnBarge').disabled=false;
}
async function poll() {
  if (!active || polling) return;
  polling=true;
  const token=generation, pending=mutation;
  try {
    await pending;
    if (!active || token!==generation) return;
    const response=await fetch('/api/state?session_id='+encodeURIComponent(session));
    const state=await response.json();
    if (!response.ok) throw new Error(state.error);
    if (!active || token!==generation || pending!==mutation) return;
    render(state);
    if(state.audio && state.audio.epoch>lastAudioEpoch && !playing) play(state.audio);
  } catch(error) { fail(error); }
  finally { polling=false; }
}
setInterval(poll,250);
function clearSpeech() {
  clearTimeout(flushTimer); finalText=''; interimText=''; $('recognition').textContent='';
}
function flushSpeech() {
  if(interimText) return; // Never submit an unfinished recognition hypothesis.
  const text=finalText; clearSpeech();
  if(text) submit(text).catch(fail);
}
async function startMic() {
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    if(!active) { stream.getTracks().forEach(t=>t.stop()); return; }
    const input=ctx.createMediaStreamSource(stream), analyser=ctx.createAnalyser();
    analyser.fftSize=512; input.connect(analyser);
    const data=new Float32Array(512); let above=0;
    function tick() {
      if(!active) return;
      analyser.getFloatTimeDomainData(data);
      const rms=Math.sqrt(data.reduce((sum,v)=>sum+v*v,0)/data.length);
      above=rms>0.045 ? above+1 : 0;
      if(above>2 && (playing||busy)) { above=0; interrupt(); }
      frame=requestAnimationFrame(tick);
    }
    tick(); $('micPill').textContent='mic: on';
  } catch(error) { log('Microphone unavailable. Type a message to continue.'); }
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR || !stream) { $('recognition').textContent='Speech recognition unavailable. Use the message field.'; return; }
  recognition=new SR(); recognition.lang='en-IN'; recognition.continuous=true; recognition.interimResults=true;
  recognition.onresult=event=>{
    clearTimeout(flushTimer); interimText='';
    for(let i=event.resultIndex;i<event.results.length;i++) {
      if(event.results[i].isFinal) finalText+=' '+event.results[i][0].transcript;
      else interimText+=event.results[i][0].transcript;
    }
    if(finalText.trim()||interimText.trim()) interrupt();
    $('recognition').textContent=(finalText+' '+interimText).trim();
    if(!interimText) flushTimer=setTimeout(flushSpeech,700);
  };
  recognition.onerror=event=>{
    if(['not-allowed','service-not-allowed','audio-capture'].includes(event.error)) {
      recognition.onend=null; $('recognition').textContent='Speech recognition unavailable. Type your message.';
    }
  };
  recognition.onend=()=>{
    if(!active) return;
    if(finalText.trim()&&!interimText) flushSpeech();
    restartTimer=setTimeout(()=>{ if(active) try{recognition.start();}catch{} },400);
  };
  recognition.start();
}
async function end() {
  const oldSession=session;
  active=false; generation++; stopAudio(); busy=false;
  cancelAnimationFrame(frame); clearTimeout(restartTimer); clearSpeech();
  if(recognition) { recognition.onend=null; recognition.onresult=null; recognition.abort(); recognition=null; }
  if(stream) { stream.getTracks().forEach(track=>track.stop()); stream=null; }
  await mutation.catch(()=>{});
  if(oldSession) await api('/api/end',{}).catch(fail);
  session=null; mutation=Promise.resolve();
  $('btnStart').disabled=false; $('btnEnd').disabled=true; $('send').disabled=true;
  $('btnBarge').disabled=true; $('btnMode').disabled=false; $('micPill').textContent='mic: off';
  $('status').textContent='Session ended.';
}
$('btnStart').onclick=async()=>{
  $('btnStart').disabled=true;
  try {
    ctx=ctx||new AudioContext(); await ctx.resume();
    const state=await api('/api/reset',{mode});
    session=state.session_id; epoch=state.epoch; active=true; generation++; lastAudioEpoch=-1;
    $('send').disabled=false; $('btnEnd').disabled=false; $('btnMode').disabled=true;
    render(state); await startMic();
  } catch(error) { fail(error); $('btnStart').disabled=false; }
};
$('btnEnd').onclick=()=>end().catch(fail);
$('btnBarge').onclick=()=>interrupt();
$('btnMode').onclick=()=>{mode=mode==='ledger'?'naive':'ledger';$('modePill').textContent='mode: '+mode;};
$('messageForm').onsubmit=event=>{
  event.preventDefault(); const text=$('message').value; $('message').value=''; clearSpeech();
  submit(text).catch(fail);
};
addEventListener('keydown',event=>{
  if(event.code==='Space' && !['INPUT','TEXTAREA','BUTTON'].includes(event.target.tagName)) {
    event.preventDefault(); interrupt();
  }
});
addEventListener('pagehide',()=>{
  if(session) navigator.sendBeacon('/api/end',new Blob([JSON.stringify({session_id:session})],{type:'application/json'}));
  if(stream) stream.getTracks().forEach(t=>t.stop());
});
