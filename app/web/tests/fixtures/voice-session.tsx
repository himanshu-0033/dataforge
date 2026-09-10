import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Room, RoomEvent } from 'livekit-client';
import { useVoiceFeedback } from '../../src/useVoiceFeedback';
import VoiceSession from '../../src/VoiceSession';
import SessionPreferences from '../../src/SessionPreferences';
import CrisisHelp from '../../src/CrisisHelp';
import type { SupportStyle } from '../../src/api';
import '../../src/styles.css';
import '../../src/voice.css';

// The production session component and feedback hook, with deterministic transport.
const client = new Room();
Object.defineProperty(client.localParticipant, 'identity', { value: 'test-user' });
const agent = { identity: 'agent', isAgent: true, audioTrackPublications: new Map() };
client.remoteParticipants.set('agent', agent as never);
let streamHandler: Parameters<Room['registerTextStreamHandler']>[1];
client.registerTextStreamHandler = (_topic, callback) => { streamHandler = callback; };
client.unregisterTextStreamHandler = () => {};
let sequence = 0;
function emit(state: string, override?: number) {
  client.emit(RoomEvent.DataReceived, new TextEncoder().encode(JSON.stringify({
    type: 'voice_state', state, status: state === 'USER_INTERRUPTED' ? 'LISTENING' : state === 'PROCESSING_FUSED_CONTEXT' ? 'PROCESSING' : state,
    command: state === 'USER_INTERRUPTED' ? 'clear_audio' : undefined, worker_epoch: 1, sequence: override ?? ++sequence,
  })), agent as never, undefined, 'heard.voice');
}

function Fixture() {
  const [mic, setMic] = useState(true);
  const [paused, setPaused] = useState(false);
  const [quiet, setQuiet] = useState(true);
  const [ended, setEnded] = useState(false);
  const [help, setHelp] = useState(false);
  const [support, setSupport] = useState<SupportStyle>('explore');
  const [focus, setFocus] = useState('');
  const [message, setMessage] = useState('');
  const [sent, setSent] = useState('');
  const feedback = useVoiceFeedback(client, mic, paused);
  const status = paused || (!mic && feedback.status === 'LISTENING') ? 'PAUSED' : feedback.status || 'LISTENING';
  useEffect(() => {
    const audio = document.querySelector('audio')!;
    audio.play = async () => { audio.dataset.visualStateAtPlay = document.querySelector<HTMLElement>('.heard-presence')?.dataset.status; };
    let context: AudioContext | undefined;
    const command = (event: Event) => {
      const { state, sequence, caption, speaker = 'agent', tone } = (event as CustomEvent).detail;
      if (state) emit(state, sequence);
      if (caption) void streamHandler({ info: { id: 'segment', attributes: {} }, async *[Symbol.asyncIterator]() {
        for (const chunk of caption.split(/(?<=\s)/)) { yield chunk; await new Promise(resolve => setTimeout(resolve, 8)); }
      } } as never, { identity: speaker });
      if (tone) {
        context = new AudioContext();
        const oscillator = context.createOscillator();
        const destination = context.createMediaStreamDestination();
        const gain = context.createGain();
        gain.gain.value = .002;
        oscillator.connect(gain).connect(destination);
        oscillator.start();
        audio.srcObject = destination.stream;
        const track = { kind: 'audio', mediaStreamTrack: destination.stream.getAudioTracks()[0] };
        client.localParticipant.getTrackPublication = () => ({ audioTrack: track } as never);
        client.emit(RoomEvent.LocalTrackPublished, {} as never, client.localParticipant);
        client.emit(RoomEvent.TrackSubscribed, track as never, {} as never, agent as never);
      }
    };
    window.addEventListener('voice-test', command);
    return () => { window.removeEventListener('voice-test', command); void context?.close(); };
  }, []);
  const control = (action: string) => {
    if (action === 'end') { feedback.silence(); setEnded(true); return; }
    const pause = action === 'pause';
    setPaused(pause); setMic(!pause);
    if (pause) feedback.silence();
    emit(pause ? 'PAUSED' : 'LISTENING');
  };
  return <div className="heard-app heard-app-voice">
    <audio data-heard-audio="voice"/>
    {ended ? <p role="status">Your session has ended.</p> : <VoiceSession status={status}
      label={paused ? 'Voice paused' : status === 'PROCESSING' ? 'Taking a moment to respond' : status === 'SPEAKING' ? 'Heard is speaking' : mic ? 'Ready to listen' : 'Microphone off'}
      spectrum={feedback.spectrum} interruption={feedback.interruption} caption={feedback.caption} ready connecting={false}
      mic={mic} micPending={false} paused={paused} pending={null} quiet={quiet} onQuiet={setQuiet}
      onMic={() => setMic(!mic)} onControl={control} onHelp={() => setHelp(true)} onAbout={() => {}}
      preferences={<SessionPreferences support={support} focus={focus} busy={false} saving={false} onChange={value => { if (value.support) setSupport(value.support); if (value.focus !== undefined) setFocus(value.focus); }}/>} notices={null}
      transcript={<div className="heard-transcript" role="log" aria-label="Conversation messages"><article className="heard-message assistant"><div className="heard-message-meta"><span>Heard <small>AI</small></span></div><p>Start wherever you are. There is no rush.</p></article>{sent && <article className="heard-message user"><p>{sent}</p></article>}</div>}
      composer={<form className="heard-composer" onSubmit={event => { event.preventDefault(); setSent(message); setMessage(''); }}><textarea aria-label="Your message" placeholder="What's on your mind?" value={message} onChange={event => setMessage(event.target.value)}/><button className="heard-send" aria-label="Send message">↑</button></form>}
    />}
    {help && <CrisisHelp onClose={() => setHelp(false)}/>}
  </div>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
