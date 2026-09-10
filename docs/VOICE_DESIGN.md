# Voice interface

Live sessions open in a full-height, midnight slate space (`#101c22`). The orb is the central visual; the transcript and keyboard open on demand. Text sessions retain their existing conversation layout.

## State language

| State | Colour and movement |
| --- | --- |
| Listening | Soft teal and sage, with a gentle response to microphone energy. |
| Processing | Lavender and indigo, breathing once every 10 seconds. |
| Speaking | Cyan with warm amber, with movement shaped by low and high audio frequencies. |
| Interrupted | A soft ripple and a 360 ms contraction, returning immediately to listening. |
| Paused / muted | A still, subdued sphere with an explicit text status. Muting the microphone does not pause a counselor reply. |

The native WebGL renderer uses one fragment pass, caps rendering at 30 fps and limits the drawing buffer to 640 pixels. A CSS gradient orb remains available when WebGL is unavailable or its context is lost. Reduced motion removes breathing, ripples, word fades and audio-driven scaling. Hidden pages suspend the rendering loop.

## Layout and controls

- Header: exit, “Virtual Counselor” with connection status and AI identification, transcript toggle.
- Hero: an orb area of about 40% of viewport height, a text status, and at most two visible caption lines. Captions follow the newest words; the full conversation remains in the transcript.
- Dock: pause/resume, a larger microphone toggle, and a muted maroon end button.
- Secondary controls: typing, conversation preferences and crisis help. Preferences use a native dialog with keyboard dismissal and focus restoration.

Controls have at least 44-pixel touch targets and visible keyboard focus. Safe-area insets protect the header and dock. Short screens can scroll; connection failures expose typing and reconnection actions.

## Timing

Accepted voice events update React synchronously, before resumed audio playback. Processing uses the direct voice event rather than the 500 ms snapshot poll. Sequence and worker checks reject stale events. Local voice onset also triggers the interruption ripple; a matching server confirmation does not replay it.

Browser tests check a visual update within 100 ms of **event receipt in the browser**, including the next animation frame. Network delivery from backend emission and physical audio-device latency are outside that measurement.

## Implementation and checks

`VoiceSession.tsx` owns the live layout, `VoicePresence.tsx` the orb and captions, `orbRenderer.ts` the shader, and `voice.css` the visual tokens and motion. `useVoiceFeedback.ts` connects the UI to the existing audio and interruption handling.

`npm run build` checks TypeScript and the production bundle. `npm run test:e2e` exercises desktop and mobile controls, captions, interruption ordering, playback handshakes, reduced motion, the CSS fallback, connection failure, and existing text conversations. The new voice-session fixture uses deterministic transport and synthetic audio; it does not contact live voice providers.
