import { expect, test, type Page } from '@playwright/test';

async function event(page: Page, detail: Record<string, unknown>) {
  return page.evaluate(detail => {
    const started = performance.now();
    window.dispatchEvent(new CustomEvent('voice-test', { detail }));
    return new Promise<number>(resolve => requestAnimationFrame(() => resolve(performance.now() - started)));
  }, detail);
}

test('voice events paint promptly, precede playback, and catch repeated interruptions', async ({ page }, testInfo) => {
  await page.goto('/tests/fixtures/voice-session.html');
  const presence = page.locator('.heard-presence');
  await expect(presence).toHaveAttribute('data-status', 'LISTENING');
  await page.locator('.heard-voice-session').screenshot({ path: testInfo.outputPath('voice-listening.png') });
  await event(page, { tone: true });
  await expect.poll(() => presence.evaluate(el => Number((el as HTMLElement).style.getPropertyValue('--voice-scale')))).toBeGreaterThan(1);
  expect(await event(page, { state: 'PROCESSING_FUSED_CONTEXT' })).toBeLessThan(100);
  await expect(presence).toHaveAttribute('data-status', 'PROCESSING');
  await expect(page.locator('.heard-orb')).toHaveCSS('animation-duration', '10s');
  await page.locator('.heard-voice-session').screenshot({ path: testInfo.outputPath('voice-processing.png') });
  expect(await event(page, { state: 'SPEAKING' })).toBeLessThan(100);
  await expect(page.locator('audio')).toHaveAttribute('data-visual-state-at-play', 'SPEAKING');
  await page.locator('.heard-voice-session').screenshot({ path: testInfo.outputPath('voice-speaking.png') });
  for (let i = 0; i < 2; i++) {
    await event(page, { state: 'USER_INTERRUPTED' });
    await expect(presence).toHaveAttribute('data-status', 'LISTENING');
    await expect(page.locator('audio')).toHaveJSProperty('muted', true);
    await expect(page.locator('.heard-orb-interruption')).toBeAttached();
    // A late speaking event must not change the visual or reopen audio.
    await event(page, { state: 'SPEAKING', sequence: 1 });
    await expect(presence).toHaveAttribute('data-status', 'LISTENING');
    await event(page, { state: 'PROCESSING' });
    await event(page, { state: 'SPEAKING' });
  }
});

test('the dock, transcript, typing, and preferences work without leaving the voice space', async ({ page }, testInfo) => {
  await page.goto('/tests/fixtures/voice-session.html');
  await expect(page.getByRole('textbox', { name: 'Your message' })).toBeHidden();
  const pause = page.getByRole('button', { name: 'Pause voice', exact: true });
  const mic = page.getByRole('button', { name: 'Mute microphone' });
  const end = page.getByRole('button', { name: 'End conversation' });
  for (const control of [pause, mic, end]) await expect(control).toBeInViewport();
  const positions = await Promise.all([pause, mic, end].map(control => control.boundingBox()));
  expect(positions[0]!.x).toBeLessThan(positions[1]!.x);
  expect(positions[1]!.x).toBeLessThan(positions[2]!.x);
  await mic.click();
  await expect(page.getByRole('button', { name: 'Enable microphone' })).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: 'Enable microphone' }).click();
  await pause.click();
  await expect(mic).toBeHidden();
  await expect(page.getByRole('button', { name: 'Enable microphone' })).toBeDisabled();
  await page.getByRole('button', { name: 'Resume voice' }).click();
  await expect(mic).toBeEnabled();
  await page.getByRole('button', { name: 'Type a message' }).click();
  await expect(page.getByRole('textbox', { name: 'Your message' })).toBeFocused();
  await page.getByRole('textbox', { name: 'Your message' }).fill('I need a little time.');
  await page.getByRole('button', { name: 'Send message' }).click();
  await page.getByRole('button', { name: 'Hide keyboard' }).click();
  await page.getByRole('button', { name: 'Show conversation' }).click();
  await expect(page.getByRole('log')).toContainText('I need a little time.');
  await page.locator('.heard-voice-session').screenshot({ path: testInfo.outputPath('voice-transcript.png') });
  await page.getByRole('button', { name: 'Hide conversation' }).click();
  await page.getByRole('button', { name: 'Conversation preferences' }).click();
  await page.getByRole('button', { name: 'Just listen', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('button', { name: 'Conversation preferences' })).toBeFocused();
  await page.getByRole('button', { name: 'Crisis help' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'Return to conversation' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await end.click();
  await expect(page.getByRole('status')).toContainText('Your session has ended.');
});

test('streaming captions follow the newest two lines and clear on interruption', async ({ page }) => {
  await page.goto('/tests/fixtures/voice-session.html');
  await event(page, { state: 'SPEAKING' });
  const caption = 'Take your time. You do not need to find the perfect words. We can explore this together, one thought at a time. What feels most important to you in this moment?';
  await event(page, { caption });
  const window = page.locator('.heard-voice-hero .heard-caption-window');
  await expect(window).toContainText(caption);
  const dimensions = await window.evaluate(el => ({ height: el.clientHeight, line: parseFloat(getComputedStyle(el).lineHeight), remaining: el.scrollHeight - el.scrollTop - el.clientHeight }));
  expect(dimensions.height).toBeLessThanOrEqual(Math.ceil(dimensions.line * 2));
  expect(dimensions.remaining).toBeLessThanOrEqual(1);
  await event(page, { state: 'USER_INTERRUPTED' });
  await expect(window).toBeHidden();
});

test('small screens and reduced motion retain accessible state feedback without WebGL', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.addInitScript(() => {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
      if (type === 'webgl') return null;
      return getContext.call(this, type as '2d', ...args);
    } as typeof getContext;
  });
  await page.goto('/tests/fixtures/voice-session.html');
  await expect(page.locator('.heard-presence')).toHaveAttribute('data-renderer', 'css');
  await event(page, { state: 'PROCESSING' });
  await expect(page.locator('.heard-orb')).toHaveCSS('animation-name', 'none');
  await expect(page.getByRole('status')).toContainText('Taking a moment');
  await page.locator('.heard-voice-session').screenshot({ path: testInfo.outputPath('voice-small-reduced-motion.png') });
  for (const name of ['Pause voice', 'Mute microphone', 'End conversation']) await expect(page.getByRole('button', { name, exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await event(page, { state: 'SPEAKING' });
  await event(page, { state: 'USER_INTERRUPTED' });
  await expect(page.locator('.heard-orb-interruption')).toBeHidden();
  await expect(page.locator('.heard-presence')).toHaveAttribute('data-status', 'LISTENING');
});

test('the app opens the voice layout and keeps typing and exit available after connection failure', async ({ page }) => {
  const snapshot = {
    session_id: 'voice-ui-test', revision: 1, mode: 'live', ended: false, paused: false,
    thinking: false, user_speaking: false, error: null, awaiting_continuation: false,
    support: 'explore', focus: '', draft: '', messages: [], speech: null,
    provider: { status: 'disconnected' }, worker_epoch: 1,
    ui: { status: 'LISTENING', overlay: null, crisis_id: null, acknowledgement: null },
  };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/health')) return route.fulfill({ json: { product: 'counselor', live_ready: true, conversation_ready: true, conversation_provider: 'vertex' } });
    if (path.endsWith('/token')) return route.fulfill({ status: 503, json: { detail: 'Voice unavailable' } });
    if (path.endsWith('/control')) return route.fulfill({ json: { ...snapshot, ended: true, revision: 2 } });
    if (path === '/api/sessions') return route.fulfill({ json: { session_id: snapshot.session_id, token: 'fixture-token', snapshot } });
    return route.fulfill({ json: snapshot });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Start talking' }).click();
  await expect(page.locator('.heard-voice-session')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reconnect voice' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Your message' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Enable microphone' })).toBeDisabled();
  await page.getByRole('button', { name: 'Show conversation' }).click();
  await expect(page.getByRole('log')).toBeVisible();
  await page.getByRole('button', { name: 'Conversation preferences' }).click();
  await page.getByRole('button', { name: 'About your conversation', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'About your conversation' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Conversation preferences' })).toBeFocused();
  await page.getByRole('button', { name: 'Exit conversation' }).click();
  await expect(page.getByRole('button', { name: 'Start talking' })).toBeVisible();
});
