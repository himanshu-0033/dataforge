import { useEffect, useLayoutEffect, useRef } from 'react';
import type { InterfaceStatus } from './api';
import type { Caption } from './useVoiceFeedback';
import { createOrbRenderer } from './orbRenderer';

export function KineticCaption({ caption }: { caption: Caption }) {
  const windowRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const viewport = windowRef.current;
    if (!viewport) return;
    const follow = () => { viewport.scrollTop = viewport.scrollHeight; };
    follow();
    const observer = new ResizeObserver(follow);
    observer.observe(viewport);
    return () => observer.disconnect();
  }, [caption.text]);
  return <div className="heard-captions" aria-label={`${caption.speaker} live captions`}>
    <span className="heard-caption-speaker">{caption.speaker === 'Heard' ? 'Heard · AI support' : 'You'}</span>
    <div className="heard-caption-window" ref={windowRef}>
      <p aria-live="off">{caption.text.split(/(\s+)/).map((word, index) => /^\s+$/.test(word) ? word : <span key={`${caption.id}-${index}-${word}`}>{word}</span>)}</p>
    </div>
  </div>;
}

export type VoicePresenceProps = {
  status: InterfaceStatus;
  interruption?: number;
  spectrum: (side: 'input' | 'output', bins: Uint8Array<ArrayBuffer>) => void;
};

export default function VoicePresence({ status, spectrum, interruption = 0 }: VoicePresenceProps) {
  const orb = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const current = useRef(status);
  useLayoutEffect(() => { current.current = status; }, [status]);
  useEffect(() => {
    if (!interruption || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const animation = orb.current?.querySelector('.heard-orb-surface')?.animate(
      [{ scale: 1 }, { scale: .93, offset: .45 }, { scale: 1 }],
      { duration: 360, easing: 'cubic-bezier(.22, .68, .2, 1)' },
    );
    return () => animation?.cancel();
  }, [interruption]);
  useEffect(() => {
    const element = orb.current;
    const surface = canvas.current;
    if (!element || !surface) return;
    const bins = new Uint8Array(128);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let renderer = createOrbRenderer(surface);
    element.dataset.renderer = renderer ? 'webgl' : 'css';
    let frame = 0, level = 0, lastTime = 0;
    let previousStatus: InterfaceStatus | null = null;
    let dirty = true;
    const resize = new ResizeObserver(([entry]) => {
      surface.width = surface.height = Math.max(1, Math.min(640, Math.round(entry.contentRect.width * Math.min(devicePixelRatio, 1.5))));
      dirty = true;
    });
    resize.observe(surface);
    const draw = (now: number) => {
      const state = current.current;
      const active = !reduced.matches && (state === 'LISTENING' || state === 'SPEAKING');
      // Cap the shader at 30fps; a new state always renders on the next frame.
      if (state !== previousStatus || dirty || now - lastTime >= 32) {
        if (active) spectrum(state === 'SPEAKING' ? 'output' : 'input', bins);
        else bins.fill(0);
        const energy = Math.sqrt(bins.reduce((sum, value) => sum + (value / 255) ** 2, 0) / bins.length);
        level = active ? level + (energy - level) * .28 : 0;
        const low = bins.slice(0, 20).reduce((sum, value) => sum + value, 0) / (20 * 255);
        const high = bins.slice(35, 100).reduce((sum, value) => sum + value, 0) / (65 * 255);
        element.style.setProperty('--voice-scale', String(1 + level * .16));
        element.style.setProperty('--voice-glow', String(.16 + level * .45));
        if ((!reduced.matches && state !== 'PAUSED') || state !== previousStatus || dirty) renderer?.draw(reduced.matches || state === 'PAUSED' ? 8 : now / 1000, state, level, low, high);
        previousStatus = state;
        dirty = false;
        lastTime = now;
      }
      frame = requestAnimationFrame(draw);
    };
    const visibility = () => {
      cancelAnimationFrame(frame);
      if (!document.hidden) { dirty = true; frame = requestAnimationFrame(draw); }
    };
    const motionChange = () => { dirty = true; };
    const lost = (event: Event) => { event.preventDefault(); renderer = null; element.dataset.renderer = 'css'; };
    const restored = () => { renderer = createOrbRenderer(surface); element.dataset.renderer = renderer ? 'webgl' : 'css'; dirty = true; };
    document.addEventListener('visibilitychange', visibility);
    reduced.addEventListener('change', motionChange);
    surface.addEventListener('webglcontextlost', lost);
    surface.addEventListener('webglcontextrestored', restored);
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      renderer?.dispose();
      document.removeEventListener('visibilitychange', visibility);
      reduced.removeEventListener('change', motionChange);
      surface.removeEventListener('webglcontextlost', lost);
      surface.removeEventListener('webglcontextrestored', restored);
    };
  }, [spectrum]);
  return <div className="heard-presence" data-status={status} ref={orb} aria-hidden="true">
    <div className="heard-orb-halo"/>
    <div className="heard-orb"><div className="heard-orb-surface">
      <div className="heard-orb-fallback"><span/><span/><span/></div>
      <canvas ref={canvas}/>
    </div></div>
    {interruption > 0 && <div className="heard-orb-interruption" key={interruption}><span/><span/></div>}
  </div>;
}
