// Provisional energy onset, not speech recognition. Server Silero VAD remains
// authoritative. Only a sustained input signal may preempt browser playback.
export class LocalVoiceOnset {
  private started: number | null = null;

  observe(samples: Float32Array, now: number, enabled: boolean) {
    let energy = 0;
    for (const value of samples) energy += value * value;
    const rms = Math.sqrt(energy / Math.max(1, samples.length));
    if (!enabled || rms < 0.025) { this.started = null; return false; }
    this.started ??= now;
    return now - this.started >= 60;
  }
}
