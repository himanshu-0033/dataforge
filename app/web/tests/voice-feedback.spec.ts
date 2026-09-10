import { expect, test } from '@playwright/test';

test('voice feedback follows audio, streams captions, and silences interruption and pause', async ({ page }) => {
  await page.goto('/tests/fixtures/voice.html');
  const presence = page.locator('.heard-presence');
  await page.getByRole('button', { name: 'Generate audio' }).click();
  await expect.poll(() => presence.evaluate(el => Number((el as HTMLElement).style.getPropertyValue('--voice-scale')))).toBeGreaterThan(1);
  await page.getByRole('button', { name: 'Heard speaks' }).click();
  await expect(presence).toHaveAttribute('data-status', 'SPEAKING');
  await page.getByRole('button', { name: 'Heard captions' }).click();
  await expect(page.getByLabel('Heard live captions')).toContainText('Take your time.');
  await page.getByRole('button', { name: 'User speaks' }).click();
  await expect(presence).toHaveAttribute('data-status', 'LISTENING');
  await expect.poll(() => page.locator('audio').evaluate(el => (el as HTMLAudioElement).muted)).toBe(true);
  await expect(page.getByLabel('Heard live captions')).toBeHidden();
  await page.getByRole('button', { name: 'User captions' }).click();
  await expect(page.getByLabel('You live captions')).toContainText('I need a little time to explain.');
  await page.getByRole('button', { name: 'User finishes' }).click();
  await expect(presence).toHaveAttribute('data-status', 'PROCESSING');
  await expect(page.locator('.heard-orb')).toHaveCSS('animation-duration', '10s');
  await page.getByRole('button', { name: 'Heard speaks' }).click();
  await expect.poll(() => page.locator('audio').evaluate(el => (el as HTMLAudioElement).muted)).toBe(false);
  await page.getByRole('button', { name: 'Pause voice' }).click();
  await expect(presence).toHaveAttribute('data-status', 'PAUSED');
  await expect.poll(() => page.locator('audio').evaluate(el => (el as HTMLAudioElement).muted)).toBe(true);
  await expect.poll(() => presence.evaluate(el => (el as HTMLElement).style.getPropertyValue('--voice-scale'))).toBe('1');
});

test('reduced motion keeps the orb and caption words stable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/tests/fixtures/voice.html');
  await page.getByRole('button', { name: 'Generate audio' }).click();
  await expect.poll(() => page.locator('.heard-presence').evaluate(el => (el as HTMLElement).style.getPropertyValue('--voice-scale'))).toBe('1');
  await page.getByRole('button', { name: 'User finishes' }).click();
  await expect(page.locator('.heard-orb')).toHaveCSS('animation-name', 'none');
  await page.getByRole('button', { name: 'User captions' }).click();
  await expect(page.locator('.heard-captions p > span').first()).toHaveCSS('animation-name', 'none');
});

test('explicit interruption clears playback and fences stale states until a fresh reply', async ({ page }) => {
  await page.goto('/tests/fixtures/voice.html');
  const space = page.locator('.heard-quiet');
  const audio = page.locator('audio');
  await page.getByRole('button', { name: 'Generate audio' }).click();
  await page.getByRole('button', { name: 'Start new reply' }).click();
  await expect(space).toHaveAttribute('data-status', 'SPEAKING');
  await page.getByRole('button', { name: 'Heard captions' }).click();
  await expect(page.getByLabel('Heard live captions')).toContainText('Take');
  await page.getByRole('button', { name: 'Interrupt explicitly' }).click();
  await expect(space).toHaveAttribute('data-phase', 'USER_INTERRUPTED');
  expect(await audio.evaluate(el => ({ muted: (el as HTMLAudioElement).muted, paused: (el as HTMLAudioElement).paused, detached: (el as HTMLAudioElement).srcObject === null }))).toEqual({ muted: true, paused: true, detached: true });
  await page.getByRole('button', { name: 'Late old event' }).click();
  await page.getByRole('button', { name: 'Retired worker event' }).click();
  await page.getByRole('button', { name: 'Heard speaks', exact: true }).click();
  await expect(space).toHaveAttribute('data-status', 'LISTENING');
  await expect(page.getByLabel('Heard live captions')).toBeHidden();
  await page.getByRole('button', { name: 'Fuse context' }).click();
  await expect(space).toHaveAttribute('data-phase', 'PROCESSING_FUSED_CONTEXT');
  await page.getByRole('button', { name: 'Start new reply' }).click();
  await expect(space).toHaveAttribute('data-status', 'SPEAKING');
  await expect.poll(() => audio.evaluate(el => !(el as HTMLAudioElement).muted && (el as HTMLAudioElement).srcObject !== null && !(el as HTMLAudioElement).paused)).toBe(true);
  await page.getByRole('button', { name: 'Finish reply' }).click();
  await expect(space).not.toHaveAttribute('data-status', 'SPEAKING');
});

test('local microphone onset cuts audio before server confirmation and recovers from noise', async ({ page }) => {
  await page.goto('/tests/fixtures/voice.html');
  await page.getByRole('button', { name: 'Generate audio' }).click();
  await page.getByRole('button', { name: 'Start new reply' }).click();
  await page.getByRole('button', { name: 'Local microphone burst' }).click();
  await expect.poll(() => page.locator('audio').evaluate(el => (el as HTMLAudioElement).muted && (el as HTMLAudioElement).srcObject === null), { timeout: 800 }).toBe(true);
  // Without confirmed server speech, a sound must not strand the conversation.
  await expect.poll(() => page.locator('audio').evaluate(el => !(el as HTMLAudioElement).muted && (el as HTMLAudioElement).srcObject !== null), { timeout: 2500 }).toBe(true);
  await page.getByRole('button', { name: 'Mute microphone' }).click();
  await page.getByRole('button', { name: 'Start new reply' }).click();
  await page.getByRole('button', { name: 'Local microphone burst' }).click();
  await page.waitForTimeout(250);
  expect(await page.locator('audio').evaluate(el => (el as HTMLAudioElement).muted)).toBe(false);
});
