import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Room, RoomEvent } from 'livekit-client';
import { useVoiceFeedback } from '../../src/useVoiceFeedback';
import VoicePresence, { KineticCaption } from '../../src/VoicePresence';
import '../../src/styles.css';
import '../../src/voice.css';

// Exercise the real hook and Web Audio analyser with a deterministic transport.
const client = new Room();
Object.defineProperty(client.localParticipant, 'identity', { value: 'test-user' });
let streamHandler: Parameters<Room['registerTextStreamHandler']>[1];
client.registerTextStreamHandler = (_topic, callback) => { streamHandler = callback; };
client.unregisterTextStreamHandler = () => {};
const agent = { identity: 'agent', isAgent: true };
client.remoteParticipants.set('agent', agent as never);
Object.defineProperty(agent, 'audioTrackPublications', { value: new Map() });
let segment = 0;
let stateSequence = 0;
let inputGain: GainNode;
function voiceState(state: string, sequence = ++stateSequence, worker = 1) {
  client.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({
    type: 'voice_state', state, sequence, worker_epoch: worker,
    status: state === 'USER_INTERRUPTED' ? 'LISTENING' : state === 'PROCESSING_FUSED_CONTEXT' ? 'PROCESSING' : state,
    command: state === 'USER_INTERRUPTED' ? 'clear_audio' : null,
  })), agent as never, undefined, 'heard.voice');
}
async function caption(identity: string, text: string) {
  const chunks = text.split(/(?<=\s)/);
  const reader = {
    info: { id: String(++segment), attributes: {} },
    async *[Symbol.asyncIterator]() {
      for (const chunk of chunks) { yield chunk; await new Promise(resolve => setTimeout(resolve, 80)); }
    },
  };
  await streamHandler(reader as never, { identity });
}

function Fixture() {
  const [mic, setMic] = useState(true);
  const [paused, setPaused] = useState(false);
  const [processing, setProcessing] = useState(false);
  const feedback = useVoiceFeedback(client, mic, paused);
  const status = paused ? 'PAUSED' : feedback.userSpeaking ? 'LISTENING' : feedback.agentSpeaking ? 'SPEAKING' : processing ? 'PROCESSING' : mic ? 'LISTENING' : 'PAUSED';
  const userSpeaks = () => {
    client.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({ type: 'user_state', status: 'LISTENING' })), agent as never, undefined, 'heard.voice');
    setProcessing(false);
  };
  return <main style={{ maxWidth: 700, margin: 'auto', padding: 20 }}>
    <section className="heard-quiet" data-status={status} data-phase={feedback.phase} aria-label="Voice fixture">
      <VoicePresence status={status} spectrum={feedback.spectrum}/>
      <p role="status">{status}</p>
      {feedback.caption && <KineticCaption caption={feedback.caption}/>}
    </section>
    <audio data-heard-audio="voice"/>
    <button onClick={() => setMic(!mic)}>{mic ? 'Mute microphone' : 'Enable microphone'}</button>
    <button onClick={() => setPaused(!paused)}>{paused ? 'Resume voice' : 'Pause voice'}</button>
    <button onClick={userSpeaks}>User speaks</button>
    <button onClick={() => voiceState('USER_INTERRUPTED')}>Interrupt explicitly</button>
    <button onClick={() => { voiceState('PROCESSING_FUSED_CONTEXT'); setProcessing(true); }}>Fuse context</button>
    <button onClick={() => voiceState('SPEAKING')}>Start new reply</button>
    <button onClick={() => voiceState('LISTENING')}>Finish reply</button>
    <button onClick={() => voiceState('SPEAKING', 1)}>Late old event</button>
    <button onClick={() => voiceState('SPEAKING', 999, 0)}>Retired worker event</button>
    <button onClick={() => client.emit(RoomEvent.ParticipantAttributesChanged, { 'lk.agent.state': 'speaking' }, agent as never)}>Heard speaks</button>
    <button onClick={() => { client.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({ type: 'user_state', status: 'PROCESSING' })), agent as never, undefined, 'heard.voice'); setProcessing(true); }}>User finishes</button>
    <button onClick={() => void caption('test-user', 'I need a little time to explain.')}>User captions</button>
    <button onClick={() => void caption('agent', 'Take your time. What has been on your mind?')}>Heard captions</button>
    <button onClick={() => { inputGain.gain.value = 0.15; window.setTimeout(() => { inputGain.gain.value = 0.002; }, 180); }}>Local microphone burst</button>
    <button onClick={() => {
      const context = new AudioContext();
      const oscillator = context.createOscillator();
      const destination = context.createMediaStreamDestination();
      inputGain = context.createGain();
      inputGain.gain.value = 0.002;
      oscillator.connect(inputGain).connect(destination);
      oscillator.start();
      document.querySelector('audio')!.srcObject = destination.stream;
      const track = { kind: 'audio', mediaStreamTrack: destination.stream.getAudioTracks()[0] };
      client.localParticipant.getTrackPublication = () => ({ audioTrack: track } as never);
      client.emit(RoomEvent.LocalTrackPublished, {} as never, client.localParticipant);
      client.emit(RoomEvent.TrackSubscribed, track as never, {} as never, agent as never);
    }}>Generate audio</button>
  </main>;
}

createRoot(document.getElementById('root')!).render(<Fixture/>);
