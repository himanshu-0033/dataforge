import { expect, test } from 'vitest';
import { LocalVoiceOnset } from './localVoiceOnset';

test('local cutoff requires sustained microphone energy and respects permissions', () => {
  const onset = new LocalVoiceOnset();
  const speech = new Float32Array(256).fill(0.06);
  const quiet = new Float32Array(256).fill(0.002);
  expect(onset.observe(quiet, 0, true)).toBe(false);
  expect(onset.observe(speech, 20, true)).toBe(false);
  expect(onset.observe(speech, 60, true)).toBe(false);
  expect(onset.observe(speech, 80, true)).toBe(true);
  expect(onset.observe(speech, 100, false)).toBe(false);
  expect(onset.observe(speech, 120, true)).toBe(false);
  expect(onset.observe(quiet, 160, true)).toBe(false);
  expect(onset.observe(speech, 180, true)).toBe(false);
});
