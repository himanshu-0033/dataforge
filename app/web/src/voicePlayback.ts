// LiveKit clears server-side TTS queues. Detaching the live stream also discards
// the browser's old playback pipeline instead of leaving muted audio buffered.
const streams = new WeakMap<HTMLMediaElement, NonNullable<HTMLMediaElement['srcObject']>>();

export function clearVoicePlayback() {
  document.querySelectorAll<HTMLMediaElement>('[data-heard-audio]').forEach(element => {
    element.muted = true;
    element.pause();
    if (element.srcObject) {
      streams.set(element, element.srcObject);
      element.srcObject = null;
    }
  });
}

export function resumeVoicePlayback(onBlocked?: () => void) {
  document.querySelectorAll<HTMLMediaElement>('[data-heard-audio]').forEach(element => {
    const stream = streams.get(element);
    if (stream) { element.srcObject = stream; streams.delete(element); }
    element.muted = false;
    if (element.srcObject) void element.play().catch(() => onBlocked?.());
  });
}
