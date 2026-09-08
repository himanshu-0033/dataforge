import type { ReactNode } from 'react';
import { motion } from 'motion/react';

export type IconName = 'package' | 'arrow' | 'check' | 'mic' | 'mic-off' | 'keyboard' | 'search' | 'close' | 'pause' | 'play' | 'repeat' | 'logout' | 'sliders' | 'alert' | 'chevron' | 'headphones';

export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    package: <><path d="m12 3 9 5v8l-9 5-9-5V8l9-5Z"/><path d="m3 8 9 5 9-5M12 13v8M7.5 5.5l9 5v4"/></>,
    arrow: <><path d="M4 12h16m-6-6 6 6-6 6"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    mic: <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></>,
    'mic-off': <><path d="M9 5V4a3 3 0 0 1 6 0v7M5 10v2a7 7 0 0 0 12 5M19 10v2M12 19v3m-4 0h8M3 3l18 18M9 9v3a3 3 0 0 0 4 3"/></>,
    keyboard: <><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M10 13h.01M14 13h.01M18 13h.01M8 16h8"/></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
    close: <path d="m6 6 12 12M6 18 18 6"/>,
    pause: <><path d="M8 5v14M16 5v14"/></>,
    play: <path d="m8 4 12 8-12 8V4Z"/>,
    repeat: <><path d="m17 2 4 4-4 4M3 11V9a3 3 0 0 1 3-3h15M7 22l-4-4 4-4m14-1v2a3 3 0 0 1-3 3H3"/></>,
    logout: <><path d="M9 4H4v16h5M10 12h11m-4-4 4 4-4 4"/></>,
    sliders: <><path d="M4 7h8m4 0h4M4 17h3m4 0h9"/><circle cx="14" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></>,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4h.01"/></>,
    chevron: <path d="m9 5 7 7-7 7"/>,
    headphones: <><path d="M4 14v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="12" width="4" height="8" rx="2"/><rect x="17" y="12" width="4" height="8" rx="2"/></>,
  };
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function InlineSpinner() { return <span className="inline-spinner" aria-hidden="true"/>; }
export function ThinkingDots() { return <span className="thinking-dots" aria-label="Thinking"><i/><i/><i/></span>; }
export function Skeleton({ className = '' }: { className?: string }) { return <span className={`skeleton animate-pulse ${className}`} aria-hidden="true"/>; }
export function Fade({ children, className = '', onEntered }: { children: ReactNode; className?: string; onEntered?: () => void }) {
  return <motion.div className={className} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: .15 }} onAnimationComplete={onEntered}>{children}</motion.div>;
}
export function Brand() {
  return <a className="brand" href="#main" aria-label="PickMate home"><Icon name="package"/><span>pickmate<span className="brand-period">.</span></span></a>;
}
