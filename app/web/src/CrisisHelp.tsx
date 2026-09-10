import { useEffect, useRef, useState } from 'react';
import { Icon } from './ui';

// Country-specific contacts verified against the linked official sources, 2026-09-10.
const resources = {
  us: { name: 'United States', service: '988 Suicide & Crisis Lifeline', number: '988', text: true, url: 'https://988lifeline.org/get-help/' },
  canada: { name: 'Canada', service: '9-8-8 Suicide Crisis Helpline', number: '988', text: true, url: 'https://988.ca/get-help/what-to-expect' },
  india: { name: 'India', service: 'Tele-MANAS mental health support', number: '14416', text: false, url: 'https://www.dghs.mohfw.gov.in/national-mental-health-programme.php' },
};

export default function CrisisHelp({ onClose }: { onClose: () => void }) {
  const [country, setCountry] = useState<keyof typeof resources | ''>('');
  const panel = useRef<HTMLElement>(null);
  const resource = country ? resources[country] : null;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab') return;
      const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button, a, select') || []);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('keydown', key); previous?.focus(); };
  }, [onClose]);
  return <div className="heard-modal-backdrop heard-help-backdrop">
    <section ref={panel} tabIndex={-1} className="heard-modal heard-help" role="dialog" aria-modal="true" aria-labelledby="help-heading" aria-describedby="help-description" data-overlay="CRISIS_MODE">
      <button className="heard-icon-button heard-modal-close" aria-label="Close crisis help" onClick={onClose}><Icon name="close"/></button>
      <p className="heard-eyebrow">Support from a person</p>
      <h2 id="help-heading">You deserve support right now.</h2>
      <p id="help-description">If you have already hurt yourself or might act now, contact local emergency services. If you can, ask someone you trust to stay with you.</p>
      <label htmlFor="help-country">Find support where you are</label>
      <select id="help-country" value={country} onChange={event => setCountry(event.target.value as typeof country)}>
        <option value="">Choose a country or region</option>
        {Object.entries(resources).map(([key, item]) => <option value={key} key={key}>{item.name}</option>)}
      </select>
      {resource && <div className="heard-help-resource">
        <p>{resource.service}<small>Available 24 hours a day</small></p>
        <div><a className="heard-primary" href={`tel:${resource.number}`}>Call {resource.number}</a>{resource.text && <a className="heard-secondary" href={`sms:${resource.number}`}>Text {resource.number}</a>}</div>
        <a className="heard-link" href={resource.url} target="_blank" rel="noreferrer">Visit the official service <Icon name="arrow"/></a>
      </div>}
      <a className="heard-link" href="https://findahelpline.com/" target="_blank" rel="noreferrer">Find a helpline in another country <Icon name="arrow"/></a>
      <p className="heard-boundary">Heard is AI support, not a licensed professional or an emergency service. These links let you contact support yourself.</p>
      <button className="heard-secondary" onClick={onClose}>Return to conversation</button>
    </section>
  </div>;
}
