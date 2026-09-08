import { expect, test, type Page, type APIRequestContext } from '@playwright/test';
const apiRoot = 'http://127.0.0.1:8001';
test.beforeEach(async ({ request }) => { expect((await request.get(`${apiRoot}/api/health`)).ok()).toBeTruthy(); });
async function start(page: Page, captureWelcome = false) {
  await page.goto('/#main');
  if (captureWelcome) {
    await expect(page.getByRole('button', { name: 'Start session', exact: true })).toBeEnabled();
    await page.evaluate(() => document.fonts.ready.then(() => undefined));
    await expect(page.locator('.mode-picker').locator('..')).toHaveCSS('opacity', '1');
    const presentation = await page.evaluate(() => ({
      fonts: [...document.fonts].filter(face => face.status === 'loaded').map(face => face.family.replaceAll('"', '')),
      overflow: document.documentElement.scrollWidth > innerWidth,
    }));
    expect(presentation.fonts).toEqual(expect.arrayContaining(['Barlow Condensed', 'Public Sans']));
    expect(presentation.overflow).toBe(false);
    await page.screenshot({ path: test.info().outputPath('welcome.png'), fullPage: true, animations: 'disabled' });
  }
  await page.getByRole('button', { name: 'Start session', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What do you need to pick?' })).toBeVisible();
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0);
}
async function send(page: Page, text: string) {
  await page.locator('#fixture-turn').fill(text);
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('#fixture-turn')).toBeEnabled();
}
async function snapshot(page: Page, request: APIRequestContext) {
  const credential = await page.evaluate(() => JSON.parse(sessionStorage.getItem('pickmate.session')!));
  const response = await request.get(`${apiRoot}/api/sessions/${credential.id}`, { headers: { Authorization: `Bearer ${credential.token}` } });
  expect(response.ok()).toBeTruthy();
  return response.json();
}
async function showStockroom(page: Page) {
  const mobileTab = page.getByRole('button', { name: 'Inventory & completed', exact: true });
  if (await mobileTab.isVisible()) await mobileTab.click();
}

test('guided picking is readable and requires explicit confirmation before stock changes', async ({ page, request }) => {
  await start(page, true);
  await expect(page.getByText('Text session · Your microphone is off.')).toBeVisible();
  const initial = await snapshot(page, request);
  const available = initial.inventory.find((item: {sku: string}) => item.sku === 'CT-BLU').available;
  const sizes = await page.evaluate(() => ({
    input: parseFloat(getComputedStyle(document.querySelector('.composer input')!).fontSize),
    item: parseFloat(getComputedStyle(document.querySelector('.inventory tbody strong')!).fontSize),
    send: document.querySelector('.composer .primary')!.getBoundingClientRect().height,
    overflow: document.documentElement.scrollWidth > innerWidth,
    titleTop: document.querySelector('.workspace-heading')!.getBoundingClientRect().top,
    headerBottom: document.querySelector('.site-header')!.getBoundingClientRect().bottom,
  }));
  expect(sizes.input).toBeGreaterThanOrEqual(16);
  expect(sizes.item).toBeGreaterThanOrEqual(16);
  expect(sizes.send).toBeGreaterThanOrEqual(44);
  expect(sizes.overflow).toBe(false);
  expect(sizes.titleTop).toBeGreaterThanOrEqual(sizes.headerBottom);
  await page.getByRole('button', { name: 'Browse inventory' }).click();
  await page.getByRole('textbox', { name: 'Search inventory' }).fill('blue cartons');
  await page.getByRole('button', { name: 'Choose blue cartons', exact: true }).click();
  await expect(page.locator('#fixture-turn')).toHaveValue('Find 1 blue cartons');
  await expect(page.locator('#fixture-turn')).toBeFocused();
  await page.getByRole('button', { name: '6 blue cartons', exact: true }).click();
  await expect(page.locator('#fixture-turn')).toHaveValue('Find 6 blue cartons');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.locator('.pick-grid').getByText('6', { exact: true })).toBeVisible();
  await expect(page.locator('.pick-grid').getByText('A-03', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('region', { name: 'Latest assistant instruction' })).toContainText('bin 3');
  await page.screenshot({ path: test.info().outputPath('guided-pick.png'), fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: "I've picked these", exact: true }).click();
  await expect(page.getByRole('button', { name: 'Confirm 6 blue cartons', exact: true })).toBeVisible();
  const beforeConfirmation = await snapshot(page, request);
  expect(beforeConfirmation.history).toHaveLength(0);
  expect(beforeConfirmation.inventory.find((item: {sku: string}) => item.sku === 'CT-BLU').available).toBe(available);
  await page.getByRole('button', { name: 'Confirm 6 blue cartons', exact: true }).click();
  await expect(page.getByText("Pick recorded. Request another item when you're ready.")).toBeVisible();
  await send(page, 'Confirm six blue cartons');
  const committed = await snapshot(page, request);
  expect(committed.history).toHaveLength(1);
  expect(committed.inventory.find((item: {sku: string}) => item.sku === 'CT-BLU').available).toBe(available - 6);
  await showStockroom(page);
  await page.getByRole('tab', { name: /Completed/ }).click();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('heading', { name: 'blue cartons', exact: true })).toBeVisible();
  await showStockroom(page);
  await page.getByRole('tab', { name: /Completed/ }).click();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  await page.getByRole('button', { name: 'End session', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start session', exact: true })).toBeEnabled();
});

test('correction during lookup keeps the latest item and session controls work', async ({ page }) => {
  await start(page);
  await page.getByRole('button', { name: 'Developer', exact: true }).click();
  await page.getByRole('slider', { name: 'Lookup delay' }).fill('5000');
  await page.getByLabel('Return stale lookup after cancellation').check();
  await page.getByRole('button', { name: 'Apply fault settings' }).click();
  await expect(page.getByRole('button', { name: 'Apply fault settings' })).toBeEnabled();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Developer', exact: true })).toBeFocused();
  await send(page, 'Find six blue cartons');
  await expect(page.locator('.pick-grid').getByText('Pending', { exact: true })).toBeVisible();
  await send(page, 'Change to four red cartons');
  await expect(page.getByRole('heading', { name: 'red cartons', exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.pick-grid').getByText('B-07', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('.pick-grid').getByText('4', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect(page.locator('#fixture-turn')).toBeDisabled();
  await expect(page.getByRole('button', { name: "I've picked these", exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Resume', exact: true }).click();
  await expect(page.locator('#fixture-turn')).toBeEnabled();
  await page.getByRole('button', { name: 'Change request', exact: true }).click();
  await expect(page.locator('#fixture-turn')).toHaveValue('Find 4 red cartons');
  await page.getByRole('button', { name: 'Cancel pick', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What do you need to pick?' })).toBeVisible();
  await page.getByRole('button', { name: 'End session', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start session', exact: true })).toBeEnabled();
});

test('slow requests show progress and block duplicate actions', async ({ page }) => {
  let releaseHealth!: () => void;
  const healthGate = new Promise<void>(resolve => { releaseHealth = resolve; });
  await page.route('**/api/health', async route => { await healthGate; await route.continue(); });
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('status', { name: 'Loading session modes' })).toBeVisible();
  await expect(page.locator('.primary.start .inline-spinner')).toBeVisible();
  releaseHealth();
  await page.getByRole('button', { name: 'Start session', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What do you need to pick?' })).toBeVisible();
  let releaseTurn!: () => void;
  const turnGate = new Promise<void>(resolve => { releaseTurn = resolve; });
  await page.route('**/api/sessions/*/turn', async route => { await turnGate; await route.continue(); });
  await page.locator('#fixture-turn').fill('Find six blue cartons');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Sending', exact: true })).toBeDisabled();
  await expect(page.getByRole('region', { name: 'Latest assistant instruction' })).toContainText('Checking your request');
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeDisabled();
  releaseTurn();
  await expect(page.locator('.pick-grid').getByText('A-03', { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#fixture-turn')).toBeEnabled();
  await page.getByRole('button', { name: 'Cancel pick', exact: true }).click();
  await page.getByRole('button', { name: 'End session', exact: true }).click();
});
