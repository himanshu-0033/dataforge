import { useEffect, useRef, useState, type ReactNode } from 'react';
import VoicePresence, { KineticCaption, type VoicePresenceProps } from './VoicePresence';
import type { Caption } from './useVoiceFeedback';
import { Icon, InlineSpinner } from './ui';

type Props = VoicePresenceProps & {
  label: string;
  ready: boolean;
  microphoneReady?: boolean;
  connecting: boolean;
  mic: boolean;
  micPending: boolean;
  paused: boolean;
  pending: string | null;
  caption: Caption | null;
  quiet: boolean;
  onQuiet: (quiet: boolean) => void;
  onMic: () => void;
  onControl: (action: string) => void;
  onHelp: () => void;
  onAbout: () => void;
  preferences: ReactNode;
  transcript: ReactNode;
  composer: ReactNode;
  notices: ReactNode;
};

export default function VoiceSession(props: Props) {
  const { status, label, quiet, onQuiet, paused, pending, mic, ready } = props;
  const [typing, setTyping] = useState(false);
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const preferences = useRef<HTMLDialogElement>(null);
  const composer = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const showComposer = typing || (!ready && !props.connecting);
  useEffect(() => {
    if (preferencesOpen) preferences.current?.showModal();
    else preferences.current?.close();
  }, [preferencesOpen]);
  useEffect(() => {
    if (typing) composer.current?.querySelector('textarea')?.focus();
  }, [typing]);
  const restingText = paused ? 'A little pause. Take all the time you need.' : props.connecting ? 'Making a little space for you…' :
    !ready ? 'Your conversation is here. You can keep typing.' : status === 'PROCESSING' ? 'Taking a moment with what you shared…' :
    status === 'SPEAKING' ? 'You can speak whenever you need to.' : !mic ? 'A quiet moment, just for you.' : 'I’m listening. Start wherever you are.';
  return <main id="main" className="heard-voice-session" data-status={status} data-transcript={!quiet}>
    <header className="heard-voice-header">
      <button className="heard-icon-button" aria-label="Exit conversation" title="End and exit conversation" disabled={pending !== null} onClick={() => props.onControl('end')}><Icon name="back"/></button>
      <div className="heard-voice-identity"><span><i data-online={ready && !paused} aria-hidden="true"/>Virtual Counselor</span><small>Heard · AI support</small></div>
      <button ref={toggle} className="heard-icon-button" aria-label={quiet ? 'Show conversation' : 'Hide conversation'} title={quiet ? 'Show transcript' : 'Hide transcript'} aria-pressed={!quiet} aria-controls="heard-voice-transcript" onClick={() => onQuiet(!quiet)}><Icon name="transcript"/></button>
    </header>
    <section className="heard-voice-space" aria-label="Conversation with Heard">
      <div className="heard-voice-notices">{props.notices}</div>
      <section className="heard-voice-hero" aria-label="Quiet conversation space" hidden={!quiet}>
        <div className="heard-voice-orbit"><VoicePresence status={status} spectrum={props.spectrum} interruption={props.interruption}/></div>
        <div className="heard-voice-copy">
          <p className="heard-voice-state" role="status">{label}</p>
          {props.caption && !paused ? <KineticCaption caption={props.caption}/> : <p className="heard-voice-reassurance">{restingText}</p>}
        </div>
      </section>
      <section id="heard-voice-transcript" className="heard-voice-transcript" aria-label="Transcript" hidden={quiet}>
        <div className="heard-voice-transcript-heading"><h1>Your conversation</h1><span role="status">{label}</span></div>
        {props.transcript}
        {props.caption && !paused && <KineticCaption caption={props.caption}/>}
      </section>
      <div className="heard-voice-bottom">
        {showComposer && <div ref={composer} className="heard-voice-type" onKeyDown={event => { if (event.key === 'Escape' && ready) { setTyping(false); toggle.current?.focus(); } }}>{props.composer}</div>}
        <div className="heard-voice-dock" role="group" aria-label="Voice session controls">
          <div className="heard-dock-control"><button className="heard-dock-pause" aria-label={paused ? 'Resume voice' : 'Pause voice'} aria-pressed={paused} disabled={pending !== null || !ready} onClick={() => props.onControl(paused ? 'resume' : 'pause')}>{pending === 'pause' || pending === 'resume' ? <InlineSpinner/> : <Icon name={paused ? 'play' : 'pause'}/>}</button><span>{paused ? 'Resume' : 'Pause'}</span></div>
          <div className="heard-dock-control heard-dock-primary"><button className="heard-mic-toggle" aria-label={mic ? 'Mute microphone' : 'Enable microphone'} aria-pressed={mic} disabled={props.micPending || !(props.microphoneReady ?? ready) || paused || pending !== null} onClick={props.onMic}>{props.micPending ? <InlineSpinner/> : <Icon name={mic ? 'mic' : 'mic-off'}/>}</button><span>{paused ? 'On hold' : mic ? 'Mic is on' : 'Mic is off'}</span></div>
          <div className="heard-dock-control"><button className="heard-dock-end" aria-label="End conversation" disabled={pending !== null} onClick={() => props.onControl('end')}>{pending === 'end' ? <InlineSpinner/> : <Icon name="phone-down"/>}</button><span>End</span></div>
        </div>
        <nav className="heard-voice-tools" aria-label="Conversation options">
          <button aria-label={typing ? 'Hide keyboard' : 'Type a message'} aria-expanded={showComposer} onClick={() => setTyping(!typing)}><Icon name="keyboard"/><span>{typing ? 'Hide keyboard' : 'Type instead'}</span></button>
          <button aria-label="Conversation preferences" onClick={() => setPreferencesOpen(true)}><Icon name="sliders"/></button>
          <button onClick={props.onHelp}>Crisis help</button>
        </nav>
      </div>
    </section>
    <dialog className="heard-voice-preferences" ref={preferences} aria-labelledby="voice-preferences-heading" onClose={() => setPreferencesOpen(false)} onClick={event => { if (event.target === event.currentTarget) setPreferencesOpen(false); }}>
      <div><button className="heard-icon-button heard-modal-close" aria-label="Close preferences" onClick={() => setPreferencesOpen(false)}><Icon name="close"/></button>
        <h2 id="voice-preferences-heading">Make this space yours.</h2>{props.preferences}
        <button className="heard-link heard-about-link" onClick={() => { setPreferencesOpen(false); props.onAbout(); }}>About your conversation <Icon name="arrow"/></button>
      </div>
    </dialog>
  </main>;
}
