import { expect, test, type Page } from '@playwright/test';

async function start(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Start talking' })).toBeDisabled();
  await page.getByRole('button', { name: 'I prefer to type' }).click();
  await expect(page.getByRole('region', { name: 'Conversation with Heard' })).toBeVisible();
}

async function send(page: Page, text: string) {
  await page.getByRole('textbox', { name: 'Your message' }).fill(text);
  await page.getByRole('button', { name: 'Send message' }).click();
}

test('text conversation keeps context across reload and clears on end', async ({ page, request }) => {
  await start(page);
  const transcript = page.getByRole('log', { name: 'Conversation messages' });
  await send(page, 'I feel overwhelmed');
  await expect(transcript).toContainText('Test reply 1: I feel overwhelmed');
  await page.reload();
  await expect(transcript).toContainText('Test reply 1: I feel overwhelmed');
  await send(page, 'Mostly about exams');
  await expect(transcript).toContainText('Test reply 2: Mostly about exams');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);

  const credential = await page.evaluate(() => JSON.parse(sessionStorage.getItem('heard.session')!));
  await page.getByRole('button', { name: 'End conversation' }).click();
  await expect(page.getByRole('button', { name: 'I prefer to type' })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem('heard.session'))).toBeNull();
  const response = await request.get(`http://127.0.0.1:8001/api/sessions/${credential.id}`, {
    headers: { Authorization: `Bearer ${credential.token}` },
  });
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toMatchObject({ ended: true, messages: [], speech: null });
});

test('stopping a pending reply allows a new message', async ({ page }) => {
  await start(page);
  await send(page, 'Please wait');
  await page.getByRole('button', { name: 'Stop reply' }).click();
  await expect(page.getByRole('button', { name: 'Stop reply' })).toBeHidden();
  await send(page, 'A different concern');
  await expect(page.getByRole('log')).toContainText('Test reply 2: A different concern');
  await expect(page.getByRole('log')).not.toContainText('Test reply 1: Please wait');
  await page.getByRole('button', { name: 'End conversation' }).click();
});

test('privacy dialog supports keyboard dismissal', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'About your conversation', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('button', { name: 'About your conversation', exact: true })).toBeFocused();
});

test('support preference and session note reach the reply and survive reload', async ({ page }) => {
  await start(page);
  await page.getByRole('button', { name: 'Just listen', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Just listen', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.locator('summary').click();
  await page.getByRole('textbox', { name: 'What matters for this conversation?' }).fill('Please skip journaling.');
  await page.getByRole('button', { name: 'Save note', exact: true }).click();
  await expect(page.locator('summary')).toContainText('What we’re keeping in mind');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Just listen', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await send(page, 'Use my preferences');
  await expect(page.getByRole('log')).toContainText('Preference received: listen; Please skip journaling.');
  await page.getByRole('button', { name: 'Quiet view', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Quiet conversation space' })).toContainText('Please skip journaling.');
  await expect(page.getByRole('log')).toBeHidden();
  await page.getByRole('button', { name: 'Show conversation', exact: true }).click();
  await expect(page.getByRole('log')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.getByRole('button', { name: 'End conversation' }).click();
  await page.getByRole('button', { name: 'I prefer to type', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Talk it through', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('summary')).toContainText('Something to keep in mind');
  await page.getByRole('button', { name: 'End conversation' }).click();
});

test('unfinished text arrives before the completed reply', async ({ page }) => {
  await start(page);
  await send(page, 'Watch the reply arrive');
  await expect(page.getByRole('log')).toContainText('A reply is arriving');
  await expect(page.getByRole('log')).toContainText('Test reply 1: Watch the reply arrive');
  await expect(page.getByRole('log')).not.toContainText('A reply is arriving');
  await page.getByRole('button', { name: 'End conversation' }).click();
});

test('crisis resources open immediately, remain dismissible, and clear on end', async ({ page }) => {
  await start(page);
  await send(page, 'I want to die');
  const help = page.getByRole('dialog', { name: 'You deserve support right now.' });
  await expect(help).toBeVisible();
  await expect(help).toHaveAttribute('data-overlay', 'CRISIS_MODE');
  await page.getByLabel('Find support where you are').selectOption('india');
  await expect(page.getByRole('link', { name: 'Call 14416' })).toHaveAttribute('href', 'tel:14416');
  await page.getByLabel('Find support where you are').selectOption('canada');
  await expect(page.getByRole('link', { name: 'Text 988' })).toHaveAttribute('href', 'sms:988');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.keyboard.press('Escape');
  await expect(help).toBeHidden();
  await expect(page.getByRole('log')).toContainText('Your safety matters.');
  await page.getByRole('button', { name: 'Crisis help', exact: true }).click();
  await expect(help).toBeVisible();
  await page.getByRole('button', { name: 'Return to conversation' }).click();
  await page.getByRole('button', { name: 'End conversation' }).click();
  await expect(help).toBeHidden();
});

test('quiet space keeps the orb central and secondary preferences collapsed', async ({ page }, testInfo) => {
  await start(page);
  await page.getByRole('button', { name: 'Quiet view', exact: true }).click();
  await expect(page.locator('.heard-presence')).toHaveAttribute('data-status', 'PAUSED');
  await expect(page.getByRole('button', { name: 'Just listen', exact: true })).toBeHidden();
  await expect(page.getByRole('button', { name: 'End conversation' })).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Your message' })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('quiet-space.png'), fullPage: true });
  await page.getByRole('button', { name: 'End conversation' }).click();
});
