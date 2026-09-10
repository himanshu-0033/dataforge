import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import { ConnectionState, Room, RoomEvent, Track } from 'livekit-client';
import { Icon, InlineSpinner, ThinkingDots } from './ui';
import { request, RequestError, route, type Credential, type Health, type Mode, type Snapshot, type SupportStyle } from './api';
import SessionPreferences from './SessionPreferences';
import CrisisHelp from './CrisisHelp';
import VoicePresence, { KineticCaption } from './VoicePresence';
import VoiceSession from './VoiceSession';
import { useVoiceFeedback } from './useVoiceFeedback';
import './styles.css';
import './voice.css';

const SESSION_KEY = 'heard.session';
const MIC_CAPTURE = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
const starters = ["I've been feeling overwhelmed", "Something's been on my mind", "I'd like to understand how I feel"];
function stored(): Credential | null {
  try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null'); } catch { return null; }
}
function Wave({ moving = false }: { moving?: boolean }) {
  return <span className={`heard-wave ${moving ? 'moving' : ''}`} aria-hidden="true">{[1, 2, 3, 4, 5].map(n => <i key={n}/>)}</span>;
}

export default function App() {
  const [credential, setCredential] = useState<Credential | null>(stored);
  const active = useRef(credential);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthBusy, setHealthBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const inFlight = useRef(false);
  const room = useRef<Room | null>(null);
  const [voiceClient, setVoiceClient] = useState<Room | null>(null);
  const [connected, setConnected] = useState(false);
  const [mic, setMic] = useState(false);
  const [micPending, setMicPending] = useState(false);
  const micWanted = useRef(true);
  const voiceEnabled = useRef(false);
  const reconnectAttempts = useRef(0);
  const reconnectVoice = useRef<() => void>(() => {});
  const [transportReconnecting, setTransportReconnecting] = useState(false);
  const [repairingVoice, setRepairingVoice] = useState(false);
  const repairInFlight = useRef(false);
  const pausedVoice = useRef(false);
  pausedVoice.current = !!snapshot?.paused;
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [message, setMessage] = useState('');
  const [privacy, setPrivacy] = useState(false);
  const [ended, setEnded] = useState(false);
  const [quiet, setQuiet] = useState(false);
  const [help, setHelp] = useState(false);
  const [dismissedCrisis, setDismissedCrisis] = useState<string | null>(null);
  const feedback = useVoiceFeedback(voiceClient, mic, !!snapshot?.paused, () => setAudioBlocked(true));
  const input = useRef<HTMLTextAreaElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const busy = pending !== null;

  const apply = useCallback((next: Snapshot) => {
    if (active.current?.id !== next.session_id) return;
    setSnapshot(previous => !previous || previous.session_id !== next.session_id || next.revision >= previous.revision ? next : previous);
  }, []);

  const disconnect = useCallback(async () => {
    const previous = room.current;
    room.current = null;
    setVoiceClient(null);
    setConnected(false);
    setTransportReconnecting(false);
    setMic(false);
    document.querySelectorAll('[data-heard-audio]').forEach(el => el.remove());
    await previous?.disconnect();
  }, []);

  const clear = useCallback(() => {
    voiceEnabled.current = false;
    reconnectAttempts.current = 0;
    active.current = null;
    sessionStorage.removeItem(SESSION_KEY);
    setCredential(null);
    setSnapshot(null);
    setQuiet(false);
    setHelp(false);
    setDismissedCrisis(null);
    setMessage('');
    setVoiceError(null);
    setAudioBlocked(false);
    void disconnect();
  }, [disconnect]);

  async function loadHealth() {
    setHealthBusy(true);
    try {
      const result = await request<Health>('/health');
      if (result.product !== 'counselor') throw new Error('The counselor server is not running yet. Please restart it with start-counselor.ps1.');
      setHealth(result);
      setError(null);
    } catch (e) { setError(e instanceof Error ? e.message : 'The service could not be reached.'); }
    finally { setHealthBusy(false); }
  }

  useEffect(() => { void loadHealth(); }, []);
  useEffect(() => { if (snapshot?.mode === 'live') setQuiet(true); }, [snapshot?.mode]);
  useEffect(() => {
    if (!credential) return;
    let disposed = false;
    let polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      try {
        const result = await request<Snapshot>(route(credential!), undefined, credential!);
        if (disposed || active.current?.id !== credential!.id) return;
        if (result.ended) { clear(); setEnded(true); }
        else apply(result);
      } catch (e) {
        if (!disposed && active.current?.id === credential!.id) {
          if (e instanceof RequestError && [401, 403, 404].includes(e.status)) clear();
          setError(e instanceof Error ? e.message : 'The conversation could not be refreshed.');
        }
      } finally { polling = false; }
    }
    void poll();
    const timer = window.setInterval(poll, 500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [credential, apply, clear]);
  useEffect(() => () => { void disconnect(); }, [disconnect]);
  const crisisId = snapshot?.ui?.crisis_id;
  const showHelp = help || (!!crisisId && crisisId !== dismissedCrisis);
  const closeHelp = useCallback(() => { setHelp(false); setDismissedCrisis(crisisId || null); }, [crisisId]);
  useEffect(() => { if (showHelp) setPrivacy(false); }, [showHelp]);
  useEffect(() => {
    if (follow.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [snapshot?.messages.length, snapshot?.thinking, snapshot?.draft, quiet]);
  useEffect(() => {
    if (!privacy) return;
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setPrivacy(false); return; }
      if (event.key !== 'Tab') return;
      const controls = Array.from(document.querySelectorAll<HTMLElement>('.heard-modal button, .heard-modal a'));
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.querySelector<HTMLButtonElement>('.heard-header .heard-about-link, .heard-voice-tools button[aria-label="Conversation preferences"]')?.focus();
    };
  }, [privacy]);
  useEffect(() => {
    if (!connected || ['connected', 'active', 'failed', 'disconnected'].includes(snapshot?.provider.status || '')) return;
    const timer = window.setTimeout(() => setVoiceError('The voice service is taking too long to join. You can keep typing, or reconnect voice.'), 30000);
    return () => window.clearTimeout(timer);
  }, [connected, snapshot?.provider.status]);
  useEffect(() => {
    if (!voiceEnabled.current || !credential || snapshot?.mode !== 'live' || busy || transportReconnecting || repairingVoice) return;
    const healthy = connected && ['connected', 'active'].includes(snapshot.provider.status);
    if (healthy) {
      // A momentary 'healthy' update must not reset the budget into an infinite loop.
      setVoiceError(null);
      const stable = window.setTimeout(() => { reconnectAttempts.current = 0; }, 60000);
      return () => window.clearTimeout(stable);
    }
    const lost = !connected || ['failed', 'disconnected'].includes(snapshot.provider.status);
    if (!lost || reconnectAttempts.current >= 3) return;
    const timer = window.setTimeout(() => {
      reconnectAttempts.current += 1;
      reconnectVoice.current();
    }, (connected ? 10000 : 2000) * 2 ** reconnectAttempts.current);
    return () => window.clearTimeout(timer);
  }, [credential, snapshot?.mode, snapshot?.provider.status, connected, busy, transportReconnecting, repairingVoice]);

  async function perform(name: string, operation: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(name);
    setError(null);
    try { await operation(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Something went wrong. Please try again.'); }
    finally { inFlight.current = false; setPending(null); }
  }

  async function connectVoice(next: Credential) {
    // Provider recovery does not own the browser transport or microphone.
    if (room.current?.state === ConnectionState.Reconnecting || room.current?.state === ConnectionState.Connecting) return;
    if (room.current?.state === ConnectionState.Connected) { await repairVoice(next); return; }
    setVoiceError(null);
    await disconnect();
    const client = new Room({ adaptiveStream: true, dynacast: true });
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access needs localhost or a secure connection. You can keep typing here.');
      const token = await request<{ url: string; token: string }>(route(next, '/token'), {}, next);
      if (active.current?.id !== next.id) return;
      room.current = client;
      setVoiceClient(client);
      client.on(RoomEvent.TrackSubscribed, track => {
        if (track.kind !== Track.Kind.Audio || room.current !== client) return;
        const element = track.attach();
        element.dataset.heardAudio = 'voice';
        document.body.appendChild(element);
        void element.play().then(() => setAudioBlocked(false)).catch(() => setAudioBlocked(true));
      });
      client.on(RoomEvent.TrackUnsubscribed, track => track.detach().forEach(el => el.remove()));
      client.on(RoomEvent.Reconnecting, () => { if (room.current === client) setTransportReconnecting(true); });
      client.on(RoomEvent.Reconnected, () => {
        if (room.current === client) { setTransportReconnecting(false); setConnected(true); setVoiceError(null); }
      });
      client.on(RoomEvent.Disconnected, () => {
        if (room.current === client) { setConnected(false); setTransportReconnecting(false); setMic(false); setVoiceClient(null); }
      });
      await client.connect(token.url, token.token);
      if (room.current !== client || active.current?.id !== next.id) { await client.disconnect(); return; }
      setConnected(true);
      const enableMic = micWanted.current && !pausedVoice.current;
      await client.localParticipant.setMicrophoneEnabled(enableMic, MIC_CAPTURE);
      if (room.current !== client || active.current?.id !== next.id) { await client.disconnect(); return; }
      setMic(enableMic);
      voiceEnabled.current = true;
    } catch (e) {
      const permission = e instanceof Error && ['NotAllowedError', 'PermissionDeniedError'].includes(e.name);
      if (permission) voiceEnabled.current = false;
      setVoiceError(permission ? 'Microphone access is blocked. Allow it in your browser, then reconnect voice. You can type below.' : 'Voice could not connect. You can keep typing, or reconnect voice.');
      await disconnect();
    }
  }

  async function repairVoice(next: Credential) {
    if (repairInFlight.current || active.current?.id !== next.id) return;
    repairInFlight.current = true;
    setRepairingVoice(true);
    try {
      const state = await request<Snapshot>(route(next, '/voice/recover'), {}, next);
      if (active.current?.id === next.id) { apply(state); setVoiceError(null); }
    } catch {
      if (active.current?.id === next.id) setVoiceError('The voice service is taking longer to recover. Your microphone connection has not been restarted. You can still type.');
    } finally {
      repairInFlight.current = false;
      setRepairingVoice(false);
    }
  }

  reconnectVoice.current = () => {
    if (!credential) return;
    if (room.current?.state === ConnectionState.Connected) void repairVoice(credential);
    else if (room.current?.state !== ConnectionState.Reconnecting) void perform('reconnect', () => connectVoice(credential));
  };

  function start(mode: Mode) {
    void perform('start-' + mode, async () => {
      const created = await request<{ session_id: string; token: string; snapshot: Snapshot }>('/sessions', { mode });
      const next = { id: created.session_id, token: created.token };
      active.current = next;
      setCredential(next);
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
      setEnded(false);
      micWanted.current = true;
      setQuiet(mode === 'live');
      follow.current = true;
      apply(created.snapshot);
      window.scrollTo(0, 0);
      if (mode === 'live') await connectVoice(next);
      else input.current?.focus();
    });
  }

  function send(event: FormEvent) {
    event.preventDefault();
    if (!credential || !message.trim()) return;
    const text = message.trim();
    void perform('send', async () => {
      const next = await request<Snapshot>(route(credential, '/turn'), { text, event_id: crypto.randomUUID() }, credential);
      follow.current = true;
      apply(next);
      setMessage('');
      input.current?.focus();
    });
  }

  function control(action: string) {
    if (!credential) return;
    if (action === 'end') voiceEnabled.current = false;
    if (action === 'pause') micWanted.current = false;
    if (action === 'resume') micWanted.current = true;
    if (['pause', 'interrupt', 'end'].includes(action)) feedback.silence();
    void perform(action, async () => {
      if (action === 'pause' && room.current) { await room.current.localParticipant.setMicrophoneEnabled(false); setMic(false); }
      if (action === 'end') await disconnect();
      const next = await request<Snapshot>(route(credential, '/control'), { action }, credential);
      if (action === 'end') { clear(); setEnded(true); window.scrollTo(0, 0); }
      else {
        apply(next);
        if (action === 'resume' && room.current) { await room.current.localParticipant.setMicrophoneEnabled(true, MIC_CAPTURE); setMic(true); }
      }
    });
  }

  async function toggleMic() {
    const client = room.current;
    if (!client || micPending) return;
    setMicPending(true);
    try {
      await client.localParticipant.setMicrophoneEnabled(!mic, MIC_CAPTURE);
      if (room.current === client) { micWanted.current = !mic; setMic(!mic); }
    } catch { setVoiceError('The microphone could not be changed. Please reconnect voice.'); }
    finally { setMicPending(false); }
  }

  function preferences(value: { support?: SupportStyle; focus?: string }) {
    if (!credential) return;
    void perform('preferences', async () => {
      apply(await request<Snapshot>(route(credential, '/preferences'), value, credential));
    });
  }

  const live = snapshot?.mode === 'live';
  useEffect(() => {
    const theme = document.querySelector('meta[name="theme-color"]');
    theme?.setAttribute('content', live ? '#101c22' : '#faf9f6');
  }, [live]);
  const workerReady = ['connected', 'active', 'reconnecting'].includes(snapshot?.provider.status || '');
  const voiceReady = connected && workerReady && !transportReconnecting;
  const voiceFailed = ['failed', 'disconnected'].includes(snapshot?.provider.status || '');
  const listening = live && voiceReady && mic && !snapshot?.paused && (feedback.status ? feedback.userSpeaking : snapshot?.user_speaking);
  const speaking = live && voiceReady && !snapshot?.paused && !listening && !audioBlocked && feedback.agentSpeaking;
  const connecting = transportReconnecting || pending === 'start-live' || pending === 'reconnect' || (connected && !workerReady && !voiceFailed && !voiceError);
  const latestReply = snapshot?.messages.filter(item => item.role === 'assistant' && item.status !== 'interrupted').at(-1);
  const liveStatus = live && voiceReady ? feedback.status : null;
  const feedbackMuted = (liveStatus === 'LISTENING' && !mic) || (liveStatus === 'SPEAKING' && audioBlocked);
  const presence = snapshot?.paused || pending === 'pause' ? 'PAUSED' :
    liveStatus ? (feedbackMuted ? 'PAUSED' : liveStatus) :
    listening ? 'LISTENING' : speaking ? 'SPEAKING' :
    snapshot?.thinking || (live && voiceReady && snapshot?.speech?.status === 'queued') ? 'PROCESSING' :
    live && voiceReady && mic && !snapshot?.awaiting_continuation ? 'LISTENING' : 'PAUSED';
  const status = snapshot?.paused || pending === 'pause' ? 'Voice paused' : listening ? 'Listening to you' : speaking ? 'Heard is speaking' : presence === 'PROCESSING' ? 'Taking a moment to respond' :
    !live ? 'Here when you are' : transportReconnecting ? 'Restoring your connection' : connecting ? 'Connecting your voice' : !voiceReady ? (connected ? 'Voice service recovering' : 'Voice disconnected') :
    speaking ? 'Heard is speaking' : !mic ? 'Microphone off' : snapshot?.user_speaking ? 'Listening to you' : snapshot?.awaiting_continuation ? 'Take your time' : 'Ready to listen';
  const detail = snapshot?.paused ? 'Take your time. You can still type below.' : listening ? 'There is room to finish your thought.' : speaking ? 'You can speak to interrupt me.' : snapshot?.thinking ? 'You can add something or interrupt at any time.' :
    !live ? 'Write whatever feels right. There is no rush.' : connecting ? 'Preparing your microphone and the voice service.' : !voiceReady ? 'Your conversation is here. Keep typing or reconnect.' :
    speaking ? 'You can speak to interrupt me.' : !mic ? 'Turn your microphone on, or keep typing.' : snapshot?.awaiting_continuation ? 'There’s no rush to finish your thought.' : 'Speak naturally, or write a message below.';

  const preferencePanel = snapshot && <SessionPreferences support={snapshot.support || 'explore'} focus={snapshot.focus || ''} busy={busy} saving={pending === 'preferences'} onChange={preferences}/>;

  const conversationTranscript = <div className="heard-transcript" hidden={quiet} ref={transcript} role="log" aria-label="Conversation messages" aria-live="polite" aria-relevant="additions text" onScroll={event => { const el = event.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
            {!snapshot && <div className="heard-message-skeleton animate-pulse" role="status" aria-label="Loading your conversation"/>}
            {snapshot?.messages.map(item => <motion.article className={`heard-message ${item.role}`} key={item.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: .15 }}><div className="heard-message-meta"><span>{item.role === 'assistant' ? 'Heard' : 'You'}{item.role === 'assistant' && <small>AI</small>}</span><time dateTime={item.utc}>{new Date(item.utc).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p>{item.text}</p>{item.status === 'interrupted' && <span className="heard-interrupted">Voice reply interrupted</span>}</motion.article>)}
            {snapshot?.draft && <article className="heard-message assistant heard-draft" aria-live="off"><div className="heard-message-meta"><span>Heard <small>AI · replying</small></span></div><p>{snapshot.draft}<span className="heard-caret" aria-hidden="true"/></p></article>}
            {snapshot?.thinking && !snapshot.draft && <div className="heard-thinking" role="status"><ThinkingDots/><span>Taking a moment with what you shared</span></div>}
          </div>;
  const messageComposer = <form className="heard-composer" onSubmit={send}><label className="sr-only" htmlFor="heard-message">Your message</label><textarea ref={input} id="heard-message" value={message} maxLength={4000} placeholder="What's on your mind?" rows={2} onChange={e => setMessage(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} disabled={pending === 'end'}/><button className="heard-send" type="submit" disabled={busy || !message.trim()} aria-label="Send message">{pending === 'send' ? <InlineSpinner/> : <Icon name="arrow"/>}</button></form>;
  const voiceNotices = <>{live && !connecting && (!connected || voiceFailed || voiceError) && <div className="heard-notice"><p>{voiceError || (connected ? 'The voice service is recovering. Your call and microphone connection remain open; you can also type.' : 'Voice is disconnected. You can continue this conversation by typing.')}</p><button className="heard-link" disabled={busy || repairingVoice} onClick={() => { reconnectAttempts.current = 0; reconnectVoice.current(); }}>{(pending === 'reconnect' || repairingVoice) && <InlineSpinner/>}{connected ? 'Retry voice service' : 'Reconnect voice'} <Icon name="arrow"/></button></div>}
          {audioBlocked && <button className="heard-secondary heard-audio" disabled={busy} onClick={() => void perform('audio', async () => { await room.current?.startAudio(); for (const audio of document.querySelectorAll<HTMLMediaElement>('[data-heard-audio]')) await audio.play(); setAudioBlocked(false); })}>Enable sound</button>}
          {error && <div className="heard-error" role="alert">{error}<button className="heard-icon-button" aria-label="Dismiss error" onClick={() => setError(null)}><Icon name="close"/></button></div>}</>;

  return <MotionConfig reducedMotion="user"><div className={`heard-app ${credential && live ? 'heard-app-voice' : ''}`}>
    {!(credential && live) && <header className="heard-header"><a href="#main" className="heard-brand" aria-label="Heard home"><Wave/><span>heard<span>.</span></span></a><span className="heard-descriptor">A space to talk things through</span><button className="heard-link heard-help-link" onClick={() => setHelp(true)}>Crisis help</button><button className="heard-link heard-about-link" onClick={() => setPrivacy(true)}>About your conversation <Icon name="arrow"/></button></header>}
    <AnimatePresence mode="wait">
      {!credential ? <motion.main id="main" key="welcome" className="heard-welcome" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }}>
        <section className="heard-intro"><p className="heard-eyebrow">AI support. At your pace.</p><h1>A little space.<br/><em>Just for you.</em></h1><p className="heard-lede">Some days, it helps to talk.<br/>Make room for what's on your mind, one conversation at a time.</p><div className="heard-intro-note"><span className="heard-rule"/><p>No perfect words needed.<br/>Start wherever you are.</p></div></section>
        <section className="heard-begin" aria-labelledby="begin-heading"><p className="heard-eyebrow">Let's begin</p><h2 id="begin-heading">How are you, really?</h2><p>Talk with Heard about your day, a difficult feeling, or something you're still figuring out.</p>
          {ended && <p className="heard-ended" role="status"><Icon name="check"/>Your session has ended. Its transcript has been cleared from this app.</p>}
          {error && <div className="heard-error" role="alert">{error}<button className="heard-link" onClick={loadHealth} disabled={healthBusy}>{healthBusy && <InlineSpinner/>}Retry connection</button></div>}
          {healthBusy ? <div className="heard-start-skeleton" role="status" aria-label="Connecting to Heard"><span className="animate-pulse"/><span className="animate-pulse"/></div> : <div className="heard-start-actions">
            <button className="heard-primary" onClick={() => start('live')} disabled={busy || !health?.live_ready}>{pending === 'start-live' ? <InlineSpinner/> : <Icon name="mic"/>}{pending === 'start-live' ? 'Connecting voice' : 'Start talking'}<Icon name="arrow"/></button>
            <button className="heard-secondary" onClick={() => start('text')} disabled={busy || !health?.conversation_ready}>{pending === 'start-text' ? <InlineSpinner/> : <Icon name="keyboard"/>}{pending === 'start-text' ? 'Opening conversation' : 'I prefer to type'}</button>
            {health && !health.live_ready && <p className="heard-small">Voice is unavailable right now. Text conversation is available.</p>}
          </div>}
          <p className="heard-boundary">Heard is an AI companion, not a licensed therapist or an emergency service.</p>
        </section>
        <footer className="heard-welcome-footer"><span>Room for your thoughts.</span><span>Speak or type. Pause whenever you need.</span></footer>
      </motion.main> : live ? <VoiceSession key="voice-session"
        status={presence} label={status} ready={voiceReady} microphoneReady={connected} connecting={connecting} mic={mic} micPending={micPending}
        paused={!!snapshot?.paused || pending === 'pause'} pending={pending} quiet={quiet} onQuiet={setQuiet}
        spectrum={feedback.spectrum} interruption={feedback.interruption} caption={feedback.caption}
        onMic={() => void toggleMic()} onControl={control} onHelp={() => setHelp(true)} onAbout={() => setPrivacy(true)}
        preferences={preferencePanel} transcript={conversationTranscript} composer={messageComposer}
        notices={<>{voiceNotices}{snapshot?.error && <div className="heard-error" role="alert">{snapshot.error}<button className="heard-link" disabled={busy} onClick={() => control('retry')}>Retry reply</button></div>}</>}
      /> : <motion.main id="main" key="session" className={`heard-session ${quiet ? 'heard-session-quiet' : ''}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }}>
        <aside className="heard-sidebar"><div><p className="heard-eyebrow">Your conversation</p><h1>A moment<br/> for yourself.</h1><p>You don't have to figure<br className="heard-desktop"/> everything out at once.</p></div>
          <div className="heard-session-notes"><span className="heard-eyebrow">A gentle reminder</span><p>Share as much or as little as feels comfortable.</p><p>Heard is AI support. It doesn't replace a qualified mental-health professional.</p></div>
          <button className="heard-end" onClick={() => control('end')} disabled={busy}>{pending === 'end' ? <InlineSpinner/> : <Icon name="logout"/>}End conversation</button>
        </aside>
        <section className="heard-conversation" aria-label="Conversation with Heard">
          <div className="heard-voice-bar"><Wave moving={!!speaking || !!snapshot?.user_speaking}/><div><h2 role="status">{status}</h2><p>{detail}</p></div><button className="heard-view-toggle" aria-pressed={quiet} onClick={() => setQuiet(!quiet)}>{quiet ? 'Show conversation' : 'Quiet view'}</button></div>
          {quiet ? <details className="heard-preferences-drawer"><summary>Conversation preferences <Icon name="sliders"/></summary>{preferencePanel}</details> : preferencePanel}
          {voiceNotices}
          {quiet && <section className="heard-quiet" data-status={presence} data-phase={snapshot?.ui?.phase || feedback.phase || presence} aria-label="Quiet conversation space">
            <VoicePresence status={presence} spectrum={feedback.spectrum}/>
            <span className="heard-quiet-label">Heard <small>AI support</small></span>
            {live && feedback.caption && !snapshot?.paused ? <KineticCaption caption={feedback.caption}/> : <p aria-live={live || snapshot?.draft ? 'off' : 'polite'}>{snapshot?.paused ? 'There’s room to take your time.' : snapshot?.thinking ? snapshot.ui?.acknowledgement || 'Taking a moment with what you shared…' : snapshot?.draft || latestReply?.text || 'There’s room to take your time.'}</p>}
          </section>}
          {!quiet && live && feedback.caption && !snapshot?.paused && <KineticCaption caption={feedback.caption}/>}
          {conversationTranscript}
          {snapshot?.error && <div className="heard-error" role="alert">{snapshot.error}<button className="heard-link" disabled={busy} onClick={() => control('retry')}>{pending === 'retry' && <InlineSpinner/>}Retry reply</button></div>}
          <div className="heard-composer-area">
            {!quiet && snapshot && snapshot.messages.every(item => item.role !== 'user') && <div className="heard-starters" aria-label="Ideas to start a conversation">{starters.map(text => <button key={text} onClick={() => { setMessage(text); input.current?.focus(); }} disabled={busy}>{text}<Icon name="arrow"/></button>)}</div>}
            <div className="heard-voice-controls">{live && <><button className="heard-mic-toggle" aria-pressed={mic} disabled={micPending || !connected || snapshot?.paused} onClick={() => void toggleMic()}>{micPending ? <InlineSpinner/> : <Icon name={mic ? 'mic' : 'mic-off'}/>} {mic ? 'Mute microphone' : 'Enable microphone'}</button><button disabled={busy} onClick={() => control(snapshot?.paused ? 'resume' : 'pause')}>{pending === 'pause' || pending === 'resume' ? <InlineSpinner/> : <Icon name={snapshot?.paused ? 'play' : 'pause'}/>} {snapshot?.paused ? 'Resume voice' : 'Pause voice'}</button></>}{(speaking || snapshot?.thinking) && <button disabled={busy} onClick={() => control('interrupt')}><Icon name="close"/>Stop reply</button>}</div>
            {messageComposer}
            <div className="heard-composer-note"><span>{live ? 'You can speak or type at any time.' : 'Enter to send · Shift + Enter for a new line'}</span><span>AI support, at your pace.</span></div>
          </div>
        </section>
      </motion.main>}
    </AnimatePresence>
    {showHelp && <CrisisHelp onClose={closeHelp}/>}
    <AnimatePresence>{privacy && <motion.div className="heard-modal-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }} onClick={() => setPrivacy(false)}><section className="heard-modal" role="dialog" aria-modal="true" aria-labelledby="privacy-heading" onClick={e => e.stopPropagation()}><button className="heard-icon-button heard-modal-close" autoFocus onClick={() => setPrivacy(false)} aria-label="Close about your conversation"><Icon name="close"/></button><p className="heard-eyebrow">Before you share</p><h2 id="privacy-heading">About your conversation</h2><p>Heard is an AI companion for reflection and supportive conversation. It cannot diagnose, provide treatment, book appointments, or connect you to a human counselor.</p><p>This app keeps the current transcript and your session note in server memory. Ending the session clears it; inactive sessions expire after one hour. It does not save raw audio.</p><p>Your text is processed by {health?.conversation_provider === 'vertex' ? 'Google Cloud Vertex AI' : health?.conversation_provider === 'groq' ? 'Groq' : 'the configured AI provider'}. Voice uses LiveKit, Deepgram, and Rime. These services have their own data policies. Avoid sharing identifying or sensitive details in this prototype.</p><p>If you are in immediate danger, contact local emergency services or someone you trust nearby. This app cannot provide emergency help.</p><button className="heard-primary" onClick={() => setPrivacy(false)}>Back to my space <Icon name="arrow"/></button></section></motion.div>}</AnimatePresence>
  </div></MotionConfig>;
}
