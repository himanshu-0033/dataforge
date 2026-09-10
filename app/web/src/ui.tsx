import type { ReactNode } from 'react';

export type IconName = 'arrow' | 'back' | 'transcript' | 'phone-down' | 'check' | 'mic' | 'mic-off' | 'keyboard' | 'close' | 'pause' | 'play' | 'logout' | 'sliders';

export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    arrow: <><path d="M4 12h16m-6-6 6 6-6 6"/></>,
    back: <path d="M20 12H4m6-6-6 6 6 6"/>,
    transcript: <><path d="M8 8h8M8 12h6"/><path d="M5 3h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H9l-5 3v-3a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/></>,
    'phone-down': <path d="M3 15c-.7 0-1-.5-1-1.2v-2c0-.6.3-1.2.8-1.5a17 17 0 0 1 18.4 0c.5.3.8.9.8 1.5v2c0 .7-.3 1.2-1 1.2h-4c-.6 0-1-.4-1-1v-2a13 13 0 0 0-8 0v2c0 .6-.4 1-1 1H3Z"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    mic: <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></>,
    'mic-off': <><path d="M9 5V4a3 3 0 0 1 6 0v7M5 10v2a7 7 0 0 0 12 5M19 10v2M12 19v3m-4 0h8M3 3l18 18M9 9v3a3 3 0 0 0 4 3"/></>,
    keyboard: <><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M10 13h.01M14 13h.01M18 13h.01M8 16h8"/></>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    pause: <><path d="M8 5v14M16 5v14"/></>,
    play: <path d="m8 4 12 8-12 8V4Z"/>,
    logout: <><path d="M9 4H4v16h5M10 12h11m-4-4 4 4-4 4"/></>,
    sliders: <><path d="M4 7h8m4 0h4M4 17h3m4 0h9"/><circle cx="14" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></>,
  };
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function InlineSpinner() { return <span className="inline-spinner" aria-hidden="true"/>; }
export function ThinkingDots() { return <span className="thinking-dots" aria-label="Thinking"><i/><i/><i/></span>; }
