import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import type { api } from './api';
import type { Mode, Snapshot, TranscriptRow } from './state';
import { readableTextColor, solidStageColor } from './lib/utils/stageColor';
import { Fade, Icon, InlineSpinner, Skeleton, ThinkingDots } from './ui';

function formatTime(utc: string) {
  const date = new Date(utc);
  return Number.isNaN(date.valueOf()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

type WelcomeProps = {
  mode: Mode;
  setMode: (mode: Mode) => void;
  health: Awaited<ReturnType<typeof api.health>> | null;
  healthBusy: boolean;
  error: string | null;
  refreshHealth: () => Promise<void>;
  startSession: () => Promise<boolean>;
  busy: boolean;
};

export function Welcome({ mode, setMode, health, healthBusy, error, refreshHealth, startSession, busy }: WelcomeProps) {
  return <main id="main" className="welcome page-width">
    <div className="welcome-layout">
      <section className="welcome-story">
        <p className="story-label"><Icon name="headphones"/>Voice-guided inventory picking</p>
        <h1>Keep your hands<br/>on the work.</h1>
        <p className="lede">Say what you need. Hear where to go.<br className="desktop-break"/> Confirm the pick when it's in your hands.</p>
        <div className="example-request">
          <span className="eyebrow">Try saying</span>
          <p><Icon name="mic"/><span>“Find six blue cartons.”</span></p>
          <span className="example-caption">Change the item or quantity as you go.</span>
        </div>
        <p className="story-footnote">Synthetic inventory. Real picking workflow.</p>
      </section>
      <section className="session-setup" aria-labelledby="setup-heading">
        <div className="setup-heading"><h2 id="setup-heading">Start your session</h2><p>A clear next step, from request to receipt.</p></div>
        <AnimatePresence>{error && <Fade key="error"><ErrorBanner text={error}/></Fade>}</AnimatePresence>
        <AnimatePresence mode="wait" initial={false}>
          {healthBusy && !health ? <Fade key="loading"><div className="mode-loading" role="status" aria-label="Loading session modes"><Skeleton className="skeleton-label"/><Skeleton className="skeleton-mode"/><Skeleton className="skeleton-mode"/></div></Fade> : <Fade key="modes">
            <fieldset className="mode-picker" disabled={busy || healthBusy}>
              <legend className="eyebrow">Session mode</legend>
              <label className={`mode-option ${mode === 'fixture' ? 'selected' : ''} ${health && !health.demo_enabled ? 'unavailable' : ''}`}>
                <input className="sr-only" type="radio" name="session-mode" value="fixture" checked={mode === 'fixture'} onChange={() => setMode('fixture')} disabled={!!health && !health.demo_enabled}/>
                <Icon name="keyboard"/><span className="mode-copy"><strong>Fixture</strong><small>Typed instructions. No microphone needed.</small></span>
                {mode === 'fixture' && <Icon name="check" className="selection-check"/>}
              </label>
              <label className={`mode-option ${mode === 'live' ? 'selected' : ''} ${!health?.live_ready ? 'unavailable' : ''}`}>
                <input className="sr-only" type="radio" name="session-mode" value="live" checked={mode === 'live'} onChange={() => setMode('live')} disabled={!health?.live_ready}/>
                <Icon name="mic"/><span className="mode-copy"><strong>Live voice</strong><small>Speak naturally. Keep both hands free.</small></span>
                {mode === 'live' ? <Icon name="check" className="selection-check"/> : !health?.live_ready && <span className="muted-label setup-needed">Setup needed</span>}
              </label>
            </fieldset>
          </Fade>}
        </AnimatePresence>
        <button className="primary start" onClick={startSession} disabled={busy || healthBusy || !health || (mode === 'fixture' && !health.demo_enabled)} aria-busy={busy}>
          <span>{busy ? 'Starting session' : healthBusy ? 'Connecting' : 'Start session'}</span>{busy || healthBusy ? <InlineSpinner/> : <Icon name="arrow"/>}
        </button>
        <p className="privacy"><Icon name="check"/><span>Stock changes only after you confirm a pick.<br/>Your session stays in this browser tab.</span></p>
        {!health?.live_ready && (!healthBusy || !!health) && <div className="setup-note"><Icon name="headphones"/><p>Live voice needs connected voice services.<button className="text-button" onClick={refreshHealth} disabled={busy || healthBusy} aria-busy={healthBusy}>{healthBusy ? 'Checking connection' : 'Check connection'}{healthBusy ? <InlineSpinner/> : <Icon name="arrow"/>}</button></p></div>}
      </section>
    </div>
    <section className="workflow-guide" aria-label="How PickMate works">
      <div className="workflow-heading"><h2>A pick, from<br/>{' '}start to finish.</h2><p>You handle the stock.<br/>PickMate keeps track of the request.</p></div>
      <ol>
        <li><span className="step-number">01</span><h3>Request</h3><p>Name the item and quantity. Correct either whenever you need.</p></li>
        <li><span className="step-number">02</span><h3>Locate</h3><p>Hear the bin and quantity. Ask to repeat the location while you work.</p></li>
        <li><span className="step-number">03</span><h3>Confirm</h3><p>Read back what you've picked. The inventory updates once.</p></li>
      </ol>
    </section>
  </main>;
}

export function VoicePanel({ status, mode, micMuted, pending }: { status: string; mode: Mode; micMuted: boolean; pending: string | null }) {
  const working = status === 'thinking' || pending === 'turn';
  const connecting = pending === 'start' || pending === 'reconnect';
  const title = connecting ? 'Connecting voice' : micMuted ? 'Microphone muted' : working ? 'Working on your request' : mode === 'fixture' && ['listening', 'speaking', 'idle'].includes(status) ? 'Ready for your next request' : status[0].toUpperCase() + status.slice(1);
  const descriptions: Record<string, string> = {
    listening: 'Ready for your next instruction.', thinking: 'Finding the next step.', speaking: mode === 'fixture' ? 'Showing the next instruction.' : 'Giving the next instruction.', paused: 'Your pick is held. Resume when ready.', disconnected: 'Reconnect to continue.', idle: 'Start when ready.',
  };
  return <section className={`voice-panel ${status}`} aria-live="polite">
    {working ? <ThinkingDots/> : connecting ? <InlineSpinner/> : <span className={`waveform ${status === 'speaking' ? 'active' : ''}`} aria-hidden="true"><i/><i/><i/><i/><i/></span>}
    <div><h2>{title}</h2><p>{mode === 'fixture' ? 'Text session · Your microphone is off.' : micMuted ? 'Turn on your microphone to speak.' : connecting ? 'Preparing your microphone and audio.' : descriptions[status]}</p></div>
  </section>;
}

export function TaskCard({ snapshot, busy, pending, sendInstruction, editRequest }: { snapshot: Snapshot; busy: boolean; pending: string | null; sendInstruction: (text: string) => unknown; editRequest: () => void }) {
  const task = snapshot.task?.status === 'cancelled' ? null : snapshot.task;
  const resolved = !!task && ['ready', 'awaiting_confirmation', 'committed'].includes(task.status);
  const color = solidStageColor(task?.status ?? 'empty');
  const stage = !task ? 0 : task.status === 'committed' ? 3 : task.status === 'awaiting_confirmation' ? 2 : 1;
  return <section className={`task-card ${!task ? 'empty' : ''}`}>
    <ol className="pick-progress" aria-label="Pick progress">{['Request an item', 'Pick from the bin', 'Confirm your pick'].map((label, index) => <li key={label} className={index < stage ? 'complete' : index === stage ? 'current' : ''} aria-current={index === stage ? 'step' : undefined}><span>{index < stage ? <Icon name="check"/> : `0${index + 1}`}</span><span>{label}</span></li>)}</ol>
    {task && <div className="section-head"><p className="eyebrow">{stage === 3 ? 'Pick completed' : 'Current pick'}</p><span className="task-status" style={{ backgroundColor: color, color: readableTextColor(color) }}>{task.status === 'awaiting_confirmation' ? 'Confirm to finish' : task.status.replaceAll('_', ' ')}</span></div>}
    <AnimatePresence mode="wait" initial={false}><Fade key={task?.item?.sku ?? 'empty'}>
      <h2>{task?.item?.name ?? 'What do you need to pick?'}</h2>
      {!task && <p className="empty-copy">Enter an item and quantity below, or choose an item from inventory.</p>}
    </Fade></AnimatePresence>
    {task ? <div className="pick-grid">
      <div><small>Quantity</small><strong>{task.quantity}</strong><span className="metric-unit">units</span></div>
      <div><small>Bin location</small><strong>{resolved ? task.item.bin : task.status === 'cancelled' ? '—' : <span className="pending-value">{snapshot.resolving && <InlineSpinner/>}Pending</span>}</strong></div>
      <div><small>Available</small><strong>{resolved ? task.item.available : '—'}</strong>{resolved && <span className="metric-unit">in stock</span>}</div>
    </div> : null}
    {task && snapshot.mode === 'fixture' && ['ready', 'awaiting_confirmation'].includes(task.status) && <div className="pick-next-action">
      <div><p>{task.status === 'ready' ? 'At the bin? Take the quantity shown above.' : `Confirming records ${task.quantity} ${task.item.name} and updates the stock.`}</p><div className="action-row">
        <button className="primary" disabled={busy || snapshot.paused} onClick={() => sendInstruction(task.status === 'ready' ? 'I picked them' : `Confirm ${task.quantity} ${task.item.name}`)}>{pending === 'turn' ? <InlineSpinner/> : <Icon name="check"/>}{task.status === 'ready' ? "I've picked these" : `Confirm ${task.quantity} ${task.item.name}`}</button>
        <button className="text-button" disabled={busy || snapshot.paused} onClick={editRequest}>Change request</button>
      </div></div>
    </div>}
    {task?.status === 'committed' && <p className="completion-notice"><Icon name="check"/>Pick recorded. Request another item when you're ready.</p>}
  </section>;
}

export function AssistantReply({ snapshot, thinking }: { snapshot: Snapshot; thinking: boolean }) {
  const hasRequest = snapshot.events.some(event => ['final_transcript', 'transcript_final'].includes(event.type));
  if (!snapshot.task && !hasRequest && !thinking) return null;
  return <section className="assistant-reply" aria-live="polite" aria-label="Latest assistant instruction"><div className="reply-author"><Icon name="headphones"/><strong>PickMate</strong></div>
    <AnimatePresence mode="wait" initial={false}><Fade key={thinking ? 'thinking' : snapshot.speech?.response_id ?? 'empty'}>{thinking ? <div className="reply-thinking"><ThinkingDots/><span>Checking your request…</span></div> : <p>{snapshot.speech?.text ?? 'Ready for your next instruction.'}</p>}</Fade></AnimatePresence>
  </section>;
}

export function Transcript({ events, thinking }: { events: TranscriptRow[]; thinking: boolean }) {
  const listRef = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  useEffect(() => {
    const list = listRef.current;
    if (list && followLatest.current) list.scrollTop = list.scrollHeight;
  }, [events.length, thinking, events.at(-1)?.text]);
  return <details className="transcript">
    <summary><span>Conversation history</span><span className="transcript-count">{events.length} {events.length === 1 ? 'message' : 'messages'}<Icon name="chevron"/></span></summary>
    <div className="transcript-list" ref={listRef} onScroll={event => {
      const list = event.currentTarget;
      followLatest.current = list.scrollHeight - list.scrollTop - list.clientHeight < 48;
    }}>
      {!events.length && !thinking && <p className="empty-copy">Your conversation will appear here.</p>}
      <AnimatePresence initial={false}>{events.map(row => <motion.article key={row.key} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }} className={`${row.speaker === 'Worker' ? 'worker-entry' : 'assistant-entry'} ${row.status === 'interrupted' ? 'interrupted' : ''}`}>
        <div className="transcript-author"><strong>{row.speaker === 'Worker' ? 'You' : row.speaker}</strong><time>{formatTime(row.utc)}</time></div>
        <p>{row.text}</p>{row.status === 'interrupted' && <small>Interrupted</small>}
      </motion.article>)}</AnimatePresence>
      <AnimatePresence>{thinking && <Fade key="thinking"><div className="transcript-thinking"><span>PickMate</span><ThinkingDots/></div></Fade>}</AnimatePresence>
    </div>
  </details>;
}

export function Inventory({ items, selectedSku, chooseItem, disabled }: { items: Snapshot['inventory']; selectedSku?: string; chooseItem?: (name: string) => void; disabled: boolean }) {
  const [query, setQuery] = useState('');
  const normalized = query.trim().toLowerCase();
  const visible = items.filter(item => `${item.name} ${item.sku} ${item.bin}`.toLowerCase().includes(normalized));
  return <section className="inventory">
    <p className="inventory-intro">{chooseItem ? 'Choose an item to start a request.' : 'Find the item and bin you need.'}<span>{items.length} items</span></p>
    <label className="inventory-search"><Icon name="search"/><input aria-label="Search inventory" placeholder="Search items or bins" value={query} onChange={event => setQuery(event.target.value)}/>{query && <button className="icon-button" onClick={() => setQuery('')} aria-label="Clear search"><Icon name="close"/></button>}</label>
    <div className="inventory-list"><table><caption className="sr-only">Inventory items, bin locations, and available quantities</caption>
      <thead><tr><th scope="col">Item</th><th scope="col">Bin</th><th scope="col">Stock</th><th scope="col"><span className="sr-only">Current item</span></th></tr></thead>
      <tbody>{visible.map(item => <tr key={item.sku} className={selectedSku === item.sku ? 'selected' : ''} aria-selected={selectedSku === item.sku}>
        <th scope="row">{chooseItem ? <button className="inventory-item-button" onClick={() => chooseItem(item.name)} disabled={disabled || item.available === 0} aria-label={`Choose ${item.name}`}><strong>{item.name}</strong><small>{item.sku}</small></button> : <><strong>{item.name}</strong><small>{item.sku}</small></>}</th><td className="bin-cell">{item.bin}</td><td className={item.available === 0 ? 'out-of-stock' : item.available <= 2 ? 'low-stock' : ''}>{item.available}</td><td className="selection-cell">{selectedSku === item.sku && <Icon name="check"/>}</td>
      </tr>)}</tbody>
    </table>{!visible.length && <p className="empty-copy">No items match “{query}”. Try an item name or bin.</p>}</div>
    <p className="inventory-note"><Icon name="check"/>Stock updates after a confirmed pick.</p>
  </section>;
}

export function StockroomPanel({ snapshot, chooseItem, disabled }: { snapshot: Snapshot; chooseItem?: (name: string) => void; disabled: boolean }) {
  const [tab, setTab] = useState<'inventory' | 'history'>('inventory');
  return <aside className="stockroom-panel" id="stockroom-panel">
    <div className="reference-tabs" role="tablist" aria-label="Stockroom information" onKeyDown={event => {
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault(); const next = event.key === 'Home' ? 'inventory' : event.key === 'End' ? 'history' : tab === 'inventory' ? 'history' : 'inventory'; setTab(next); document.getElementById(`${next}-tab`)?.focus();
      }
    }}><button id="inventory-tab" role="tab" aria-selected={tab === 'inventory'} aria-controls="inventory-panel" tabIndex={tab === 'inventory' ? 0 : -1} onClick={() => setTab('inventory')}>Inventory</button><button id="history-tab" role="tab" aria-selected={tab === 'history'} aria-controls="history-panel" tabIndex={tab === 'history' ? 0 : -1} onClick={() => setTab('history')}>Completed <span>{snapshot.history.length}</span></button></div>
    <div role="tabpanel" id="inventory-panel" aria-labelledby="inventory-tab" hidden={tab !== 'inventory'}><Inventory items={snapshot.inventory} selectedSku={snapshot.task?.item?.sku} chooseItem={chooseItem} disabled={disabled}/></div>
    <div role="tabpanel" id="history-panel" aria-labelledby="history-tab" hidden={tab !== 'history'}><History snapshot={snapshot}/></div>
  </aside>;
}

export function History({ snapshot }: { snapshot: Snapshot }) {
  return <section className="history"><div className="section-head"><h2>Completed picks</h2><span className="muted-label">{snapshot.history.length} recorded</span></div>
    {snapshot.history.length ? <div className="history-list">{snapshot.history.map((entry, index) => <article key={entry.operation_id ?? index}>
      <Icon name="check"/><div><strong>{entry.item?.name ?? entry.name ?? entry.sku}</strong><small>{entry.quantity} picked {entry.bin ? `from ${entry.bin}` : ''}</small></div><time>{entry.committed_at ? formatTime(entry.committed_at) : ''}</time>
    </article>)}</div> : <p className="empty-copy">A clear record of the work you've finished. Your first confirmed pick will appear here.</p>}
  </section>;
}

type DeveloperProps = {
  snapshot: Snapshot; demoEnabled: boolean; delay: number; setDelay: (value: number) => void;
  ignoreCancellation: boolean; setIgnoreCancellation: (value: boolean) => void;
  failure: string; setFailure: (value: string) => void; inject: () => unknown; close: () => void;
  busy: boolean; saving: boolean; error?: string | null;
};

export function DeveloperPanel(props: DeveloperProps) {
  const { snapshot, close, busy, saving } = props;
  const provider = snapshot.provider;
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function keyboard(event: KeyboardEvent) {
      if (event.key === 'Escape') closeRef.current();
      if (event.key !== 'Tab') return;
      const elements = panelRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)');
      if (!elements?.length) return;
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener('keydown', keyboard);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener('keydown', keyboard); previous?.focus(); };
  }, []);
  return <motion.div className="drawer-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }} onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <motion.aside ref={panelRef} className="developer" role="dialog" aria-modal="true" aria-labelledby="developer-title" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }}>
      <div className="drawer-head"><div><p className="eyebrow">Session details</p><h2 id="developer-title">Developer panel</h2></div><button className="icon-button" onClick={close} aria-label="Close developer panel"><Icon name="close"/></button></div>
      <dl>{[['Provider', provider.name], ['Status', provider.status], ['Model / voice', [provider.model, provider.speaker].filter(Boolean).join(' / ') || 'Not applicable'], ['Language', provider.language ?? '—'], ['Measurement', snapshot.mode === 'fixture' ? 'Simulated playback only' : 'SDK playout estimates; physical audio not measured']].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>
      {props.error && <ErrorBanner text={props.error}/>}
      {props.demoEnabled && <fieldset className="faults" disabled={busy}><legend>Controlled failure injection</legend>
        <label htmlFor="lookup-delay">Lookup delay<output aria-hidden="true">{props.delay / 1000}s</output></label><input id="lookup-delay" type="range" min="0" max="10000" step="500" value={props.delay} aria-valuetext={`${props.delay / 1000} seconds`} onChange={event => props.setDelay(Number(event.target.value))}/>
        <label className="check"><input type="checkbox" checked={props.ignoreCancellation} onChange={event => props.setIgnoreCancellation(event.target.checked)}/>Return stale lookup after cancellation</label>
        <label className="select-label">Dependency failure<select value={props.failure} onChange={event => props.setFailure(event.target.value)}><option value="">None</option><option value="lookup">Inventory lookup</option><option value="rime">Rime</option><option value="stt">Speech recognition</option><option value="llm">Language model</option></select></label>
        <button className="primary" onClick={props.inject} aria-busy={saving}>{saving ? <InlineSpinner/> : <Icon name="sliders"/>}{saving ? 'Applying settings' : 'Apply fault settings'}</button>
      </fieldset>}
      <div className="event-log"><h3>Event timeline</h3>{snapshot.events.slice(-80).reverse().map(event => <article key={event.seq}><span>{event.seq}</span><div><strong>{event.type.replaceAll('_', ' ')}</strong><small>{event.monotonic_ms.toFixed(1)} ms · epoch {event.response_epoch}</small></div><time>{formatTime(event.utc)}</time></article>)}</div>
    </motion.aside>
  </motion.div>;
}

export function ErrorBanner({ text }: { text: string }) { return <div className="error-banner" role="alert"><Icon name="alert"/><p>{text}</p></div>; }
