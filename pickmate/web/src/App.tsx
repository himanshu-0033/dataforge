import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, MotionConfig } from 'motion/react';
import { Room, RoomEvent, Track, type RemoteTrack } from 'livekit-client';
import { api, ApiError } from './api';
import { acceptSnapshot, buildTranscript, initialSessionState, voiceState, type Mode, type Snapshot } from './state';
import { PlaybackAcknowledger } from './playback';
import { Brand, Fade, Icon, InlineSpinner, Skeleton } from './ui';
import { Welcome, VoicePanel, TaskCard, AssistantReply, Transcript, StockroomPanel, DeveloperPanel, ErrorBanner } from './workspace';

const SESSION_KEY = 'pickmate.session';
type StoredSession = { id: string; token: string };
type Health = Awaited<ReturnType<typeof api.health>>;
function storedSession(): StoredSession | null {
  try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? 'null'); } catch { return null; }
}
function errorText(error: unknown) { return error instanceof Error ? error.message : 'Something went wrong.'; }

export default function App() {
  const [state, setState] = useState(initialSessionState);
  const [mode, setMode] = useState<Mode>('fixture');
  const [health, setHealth] = useState<Health | null>(null);
  const [healthBusy, setHealthBusy] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [credential, updateCredential] = useState<StoredSession | null>(() => storedSession());
  const credentialRef = useRef(credential);
  const setCredential = useCallback((next: StoredSession | null) => {
    credentialRef.current = next;
    updateCredential(next);
  }, []);
  const roomRef = useRef<Room | null>(null);
  const [connected, setConnected] = useState(false);
  const [micEnabled, setMicEnabled] = useState(false);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [message, setMessage] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const [workspaceView, setWorkspaceView] = useState<'pick' | 'stock'>('pick');
  const [pending, setPending] = useState<string | null>(null);
  const pendingRef = useRef<string | null>(null);
  const busy = pending !== null;
  const [actionError, setActionError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [developerOpen, setDeveloperOpen] = useState(false);
  const [delay, setDelay] = useState(5000);
  const [ignoreCancellation, setIgnoreCancellation] = useState(false);
  const [failure, setFailure] = useState('');
  const snapshot = state.snapshot;

  // Responses from ended sessions must not restore an old workspace.
  const applySnapshot = useCallback((incoming: Snapshot) => setState(current =>
    credentialRef.current?.id === incoming.session_id ? acceptSnapshot(current, incoming) : current
  ), []);

  const refreshHealth = useCallback(async () => {
    setHealthBusy(true);
    setHealthError(null);
    try {
      const next = await api.health();
      setHealth(next);
      if (next.live_ready && (next.mode === 'live' || !next.demo_enabled)) setMode('live');
      else if (!next.live_ready) setMode('fixture');
    } catch (error) { setHealthError(errorText(error)); }
    finally { setHealthBusy(false); }
  }, []);

  const playback = useMemo(() => new PlaybackAcknowledger(async (responseId, status) => {
    if (!credential || credentialRef.current?.id !== credential.id) return;
    try { applySnapshot(await api.playback(credential.id, credential.token, responseId, status)); }
    catch (error) { if (credentialRef.current?.id === credential.id) setPollError(errorText(error)); }
  }), [credential, applySnapshot]);

  useEffect(() => { void refreshHealth(); }, [refreshHealth]);
  useEffect(() => {
    if (!credential) return;
    let disposed = false;
    let inFlight = false;
    const poll = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next = await api.snapshot(credential.id, credential.token);
        if (!disposed && credentialRef.current?.id === credential.id) {
          if (next.ended) {
            sessionStorage.removeItem(SESSION_KEY);
            setCredential(null);
            setState(initialSessionState);
          } else applySnapshot(next);
          setPollError(null);
        }
      } catch (error) {
        if (!disposed && credentialRef.current?.id === credential.id) {
          if (error instanceof ApiError && [401, 403, 404].includes(error.status)) {
            sessionStorage.removeItem(SESSION_KEY);
            setCredential(null);
            setState(initialSessionState);
          }
          setPollError(errorText(error));
        }
      } finally { inFlight = false; }
    };
    void poll();
    const timer = window.setInterval(poll, 400);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [credential, applySnapshot, setCredential]);
  useEffect(() => {
    if (snapshot?.mode === 'fixture' && !snapshot.ended && snapshot.speech?.status === 'queued') playback.start(snapshot.speech.response_id);
  }, [snapshot?.speech?.response_id, snapshot?.speech?.status, snapshot?.mode, snapshot?.ended, playback]);
  useEffect(() => () => playback.stop(), [playback]);
  useEffect(() => () => {
    const active = roomRef.current;
    roomRef.current = null;
    void active?.disconnect();
    document.querySelectorAll<HTMLMediaElement>('[data-pickmate-audio]').forEach(el => el.remove());
  }, []);

  async function perform(name: string, operation: () => Promise<void>) {
    if (pendingRef.current) return false;
    pendingRef.current = name;
    setPending(name);
    setActionError(null);
    try { await operation(); return true; }
    catch (error) { setActionError(errorText(error)); return false; }
    finally { pendingRef.current = null; setPending(null); }
  }

  const connectLive = useCallback(async (session: StoredSession) => {
    const old = roomRef.current;
    if (old) { roomRef.current = null; await old.disconnect(); }
    document.querySelectorAll<HTMLMediaElement>('[data-pickmate-audio]').forEach(el => el.remove());
    const details = await api.liveToken(session.id, session.token);
    const nextRoom = new Room({ adaptiveStream: true, dynacast: true });
    nextRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach();
        el.dataset.pickmateAudio = 'remote';
        document.body.appendChild(el);
        void el.play().then(() => setAudioBlocked(false)).catch(() => setAudioBlocked(true));
      }
    });
    nextRoom.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => track.detach().forEach(el => el.remove()));
    nextRoom.on(RoomEvent.Disconnected, () => { setConnected(false); setMicEnabled(false); });
    try {
      await nextRoom.connect(details.url, details.token);
      roomRef.current = nextRoom;
      setConnected(true);
      await nextRoom.localParticipant.setMicrophoneEnabled(true);
      setMicEnabled(true);
    } catch (error) {
      if (roomRef.current !== nextRoom) await nextRoom.disconnect();
      throw error;
    }
  }, []);

  function startSession() {
    return perform('start', async () => {
      const created = await api.create(mode);
      const next = { id: created.session_id, token: created.token };
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
      setCredential(next);
      setWorkspaceView('pick');
      setPollError(null);
      applySnapshot(created.snapshot);
      if (mode === 'live') await connectLive(next);
    });
  }
  function control(action: string) {
    if (!credential) return;
    return perform(action, async () => {
      if (action === 'end') {
        playback.stop();
        const active = roomRef.current;
        roomRef.current = null;
        await active?.disconnect();
        document.querySelectorAll<HTMLMediaElement>('[data-pickmate-audio]').forEach(el => el.remove());
      }
      const next = await api.control(credential.id, credential.token, action);
      if (action === 'end') {
        sessionStorage.removeItem(SESSION_KEY);
        setCredential(null);
        setConnected(false);
        setMicEnabled(false);
        setState(initialSessionState);
        setMessage('');
        setPollError(null);
        setDeveloperOpen(false);
      } else applySnapshot(next);
    });
  }
  function reconnect() {
    if (!credential) return;
    return perform('reconnect', async () => {
      applySnapshot(await api.control(credential.id, credential.token, 'recover'));
      await connectLive(credential);
    });
  }
  async function sendInstruction(instruction: string) {
    if (!credential || !instruction.trim() || busy || snapshot?.mode !== 'fixture' || snapshot.paused) return;
    const text = instruction.trim();
    setMessage('');
    const success = await perform('turn', async () => {
      applySnapshot(await api.turn(credential.id, credential.token, text));
    });
    if (!success) setMessage(text);
  }
  async function submitTurn(event: FormEvent) {
    event.preventDefault();
    await sendInstruction(message);
    inputRef.current?.focus();
  }
  function prepareRequest(text: string) {
    setMessage(text);
    setWorkspaceView('pick');
    window.requestAnimationFrame(() => {
      inputRef.current?.focus({ preventScroll: true });
      inputRef.current?.scrollIntoView({ block: 'nearest' });
    });
  }
  function browseInventory() {
    setWorkspaceView('stock');
    window.requestAnimationFrame(() => document.querySelector<HTMLInputElement>('[aria-label="Search inventory"]')?.focus());
  }
  function toggleMic() {
    const room = roomRef.current;
    if (!room) return;
    return perform('mic', async () => {
      try {
        await room.localParticipant.setMicrophoneEnabled(!micEnabled);
        setMicEnabled(!micEnabled);
      } catch { throw new Error('Allow microphone access in your browser settings, then try again.'); }
    });
  }
  function injectFault() {
    if (!credential) return;
    return perform('faults', async () => {
      applySnapshot(await api.faults(credential.id, credential.token, {
        lookup_delay_ms: delay, ignore_cancellation: ignoreCancellation, fail_provider: failure || null,
      }));
    });
  }
  function unlockAudio() {
    return perform('audio', async () => {
      const elements = [...document.querySelectorAll<HTMLMediaElement>('[data-pickmate-audio]')];
      await Promise.all(elements.map(el => el.play()));
      setAudioBlocked(false);
    });
  }
  function clearRecovery() {
    sessionStorage.removeItem(SESSION_KEY);
    setCredential(null);
    setState(initialSessionState);
    setPollError(null);
  }

  const status = voiceState(snapshot, connected);
  const transcript = buildTranscript(snapshot?.events ?? []);
  const recovering = !!credential && !snapshot;

  return <MotionConfig reducedMotion="user" transition={{ duration: .15 }}>
    <div className="app-shell">
      <header className="site-header">
        <Brand/>
        <span className="header-divider"/>
        <span className="header-context">Stockroom workspace</span>
        <div className="header-right">
          <span className="connection-status" role="status">
            {healthBusy ? <><InlineSpinner/>Connecting</> : health && !healthError && !pollError ? <><i className="status-dot online"/>System online</> : <><i className="status-dot"/>Connection unavailable</>}
          </span>
          {snapshot && <button className="text-button developer-toggle" onClick={() => setDeveloperOpen(true)} aria-expanded={developerOpen}><Icon name="sliders"/>Developer</button>}
        </div>
      </header>

      <AnimatePresence mode="wait" initial={false}>
        {recovering ? <Fade key="recovering" className="recovery page-width">
          <p className="eyebrow"><InlineSpinner/>Restoring your session</p>
          <Skeleton className="skeleton-title"/><Skeleton className="skeleton-line"/>
          <div className="recovery-grid"><Skeleton/><Skeleton/><Skeleton/></div>
          {pollError && <><ErrorBanner text={pollError}/><button className="text-button" onClick={clearRecovery}>Return to start<Icon name="arrow"/></button></>}
        </Fade> : !snapshot ? <Fade key="welcome" onEntered={() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' })}>
          <Welcome mode={mode} setMode={setMode} health={health} healthBusy={healthBusy} error={healthError || actionError || pollError} refreshHealth={refreshHealth} startSession={startSession} busy={busy}/>
        </Fade> : <Fade key="workspace" onEntered={() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' })}>
          <main id="main" className={`session-page page-width view-${workspaceView}`}>
            <div className="workspace-heading">
              <div><h1>Picking workspace</h1><p className="page-description">Request an item. Find the bin. Confirm the pick.</p></div>
              <div className="session-meta"><span className="mode-label"><Icon name={snapshot.mode === 'fixture' ? 'keyboard' : 'mic'}/>{snapshot.mode === 'fixture' ? 'Text session' : 'Live voice'}</span><button className="control danger" onClick={() => control('end')} disabled={busy}>{pending === 'end' ? <InlineSpinner/> : <Icon name="logout"/>}End session</button></div>
            </div>
            <nav className="mobile-workspace-nav" aria-label="Workspace view"><button aria-pressed={workspaceView === 'pick'} onClick={() => setWorkspaceView('pick')}>Current pick</button><button aria-pressed={workspaceView === 'stock'} onClick={() => setWorkspaceView('stock')}>Inventory & completed</button></nav>
            <div className="workspace">
              <div className="main-column">
                <VoicePanel status={status} mode={snapshot.mode} micMuted={snapshot.mode === 'live' && connected && !micEnabled} pending={pending}/>
                <AnimatePresence>{(actionError || pollError) && <Fade key="error"><ErrorBanner text={actionError || pollError || ''}/></Fade>}</AnimatePresence>
                <AnimatePresence>{audioBlocked && <Fade key="audio"><div className="notice"><span>Allow audio playback to hear the assistant.</span><button className="text-button" onClick={unlockAudio} disabled={busy}>{pending === 'audio' && <InlineSpinner/>}Enable audio</button></div></Fade>}</AnimatePresence>
                {snapshot.mode === 'live' && (!connected || snapshot.provider.status === 'failed') && <div className="notice"><span>{snapshot.provider.status === 'failed' ? 'Voice is unavailable. Your current pick is saved.' : 'Connect your microphone to continue this session.'}</span><button className="text-button" onClick={reconnect} disabled={busy}>{pending === 'reconnect' && <InlineSpinner/>}Reconnect voice</button></div>}
                <TaskCard snapshot={snapshot} busy={busy} pending={pending} sendInstruction={sendInstruction} editRequest={() => prepareRequest(`Find ${snapshot.task?.quantity ?? 1} ${snapshot.task?.item.name ?? ''}`)}/>
                <AssistantReply snapshot={snapshot} thinking={pending === 'turn' || snapshot.resolving}/>
                {snapshot.mode === 'fixture' && <form className="turn-form" onSubmit={submitTurn}>
                  <div className="composer-label"><label htmlFor="fixture-turn">{snapshot.task && !['cancelled', 'committed'].includes(snapshot.task.status) ? 'Your next instruction' : 'Request an item'}</label><button className="text-button browse-inventory" type="button" onClick={browseInventory} disabled={busy || snapshot.paused}>Browse inventory<Icon name="arrow"/></button></div>
                  <div className="composer"><input ref={inputRef} id="fixture-turn" value={message} onChange={event => setMessage(event.target.value)} placeholder="e.g. Find 6 blue cartons" disabled={snapshot.paused || busy} autoComplete="off"/><button className="primary" disabled={!message.trim() || busy || snapshot.paused}>{pending === 'turn' ? <InlineSpinner/> : <Icon name="arrow"/>}<span>{pending === 'turn' ? 'Sending' : 'Send'}</span></button></div>
                  {(!snapshot.task || ['committed', 'cancelled'].includes(snapshot.task.status)) && <div className="suggestions"><span>Try a request</span>{snapshot.inventory.filter(item => ['CT-BLU', 'CT-RED'].includes(item.sku) && item.available > 0).map((item, index) => <button className="suggestion" type="button" key={item.sku} disabled={busy || snapshot.paused} onClick={() => prepareRequest(`Find ${Math.min(index === 0 ? 6 : 4, item.available)} ${item.name}`)}>{Math.min(index === 0 ? 6 : 4, item.available)} {item.name}<Icon name="arrow"/></button>)}</div>}
                  <small>{snapshot.paused ? 'Session paused. Resume to send another instruction.' : 'You can change your request at any time before confirming the pick.'}</small>
                </form>}
                <div className="controls" aria-label="Session controls">
                  {snapshot.mode === 'live' && <button className="control" onClick={toggleMic} disabled={!connected || busy}>{pending === 'mic' ? <InlineSpinner/> : <Icon name={micEnabled ? 'mic' : 'mic-off'}/>}<span>{micEnabled ? 'Mute mic' : 'Turn mic on'}</span></button>}
                  <button className="control" onClick={() => control(snapshot.paused ? 'resume' : 'pause')} disabled={busy}>{pending === 'pause' || pending === 'resume' ? <InlineSpinner/> : <Icon name={snapshot.paused ? 'play' : 'pause'}/>} {snapshot.paused ? 'Resume' : 'Pause'}</button>
                  <button className="control" onClick={() => control('repeat')} disabled={busy}>{pending === 'repeat' ? <InlineSpinner/> : <Icon name="repeat"/>}Repeat instruction</button>
                  {snapshot.task && !['committed', 'cancelled'].includes(snapshot.task.status) && <button className="control" onClick={() => control('cancel')} disabled={busy}>{pending === 'cancel' ? <InlineSpinner/> : <Icon name="close"/>}Cancel pick</button>}
                </div>
                <Transcript events={transcript} thinking={pending === 'turn' || snapshot.resolving}/>
              </div>
              <StockroomPanel snapshot={snapshot} chooseItem={snapshot.mode === 'fixture' ? name => prepareRequest(`Find 1 ${name}`) : undefined} disabled={busy || snapshot.paused}/>
            </div>
          </main>
        </Fade>}
      </AnimatePresence>
      <footer className="site-footer page-width"><span>Built for the work at hand.</span><span>PickMate <span className="footer-slash">/</span> Stockroom assistant</span></footer>
      <AnimatePresence>{developerOpen && snapshot && <DeveloperPanel snapshot={snapshot} demoEnabled={!!health?.demo_enabled} delay={delay} setDelay={setDelay} ignoreCancellation={ignoreCancellation} setIgnoreCancellation={setIgnoreCancellation} failure={failure} setFailure={setFailure} inject={injectFault} close={() => setDeveloperOpen(false)} busy={busy} saving={pending === 'faults'} error={actionError}/>}</AnimatePresence>
    </div>
  </MotionConfig>;
}
