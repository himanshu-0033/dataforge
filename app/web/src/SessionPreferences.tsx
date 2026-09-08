import { useEffect, useState } from 'react';
import type { SupportStyle } from './api';
import { Icon, InlineSpinner } from './ui';

const styles: { id: SupportStyle; label: string; description: string }[] = [
  { id: 'listen', label: 'Just listen', description: 'Space to say it, without jumping to advice.' },
  { id: 'explore', label: 'Talk it through', description: 'Make sense of things together, one thread at a time.' },
  { id: 'steps', label: 'One small step', description: 'Find something manageable, when you feel ready.' },
];

export default function SessionPreferences({ support, focus, busy, saving, onChange }: {
  support: SupportStyle; focus: string; busy: boolean; saving: boolean;
  onChange: (value: { support?: SupportStyle; focus?: string }) => void;
}) {
  const [note, setNote] = useState(focus);
  useEffect(() => setNote(focus), [focus]);

  return <section className="heard-preferences" aria-label="Your conversation preferences">
    <div className="heard-support-heading"><span>What would help right now?</span><span>You can change your mind.</span></div>
    <div className="heard-support-options" role="group" aria-label="How Heard responds">
      {styles.map(style => <button key={style.id} type="button" aria-pressed={support === style.id} disabled={busy}
        onClick={() => onChange({ support: style.id })}>
        {support === style.id && <Icon name="check"/>}{style.label}
      </button>)}
    </div>
    <p className="heard-support-detail">{styles.find(style => style.id === support)?.description}</p>
    <details className="heard-focus">
      <summary><Icon name="sliders"/>{focus ? 'What we’re keeping in mind' : 'Something to keep in mind'}<span>{focus ? 'Edit' : 'Optional'}</span></summary>
      <form onSubmit={event => { event.preventDefault(); onChange({ focus: note.trim() }); }}>
        <label htmlFor="session-focus">What matters for this conversation?</label>
        <textarea id="session-focus" value={note} maxLength={600} rows={2} onChange={event => setNote(event.target.value)}
          placeholder="For example: I want to talk about work. Please don't suggest journaling." disabled={busy}/>
        <div className="heard-focus-actions"><span>Only for this session. You can edit or clear it.</span>
          {focus && <button type="button" className="heard-link" disabled={busy} onClick={() => { setNote(''); onChange({ focus: '' }); }}>Clear note</button>}
          <button type="submit" disabled={busy || note.trim() === focus} className="heard-focus-save">{saving && <InlineSpinner/>}Save note</button>
        </div>
      </form>
    </details>
  </section>;
}
