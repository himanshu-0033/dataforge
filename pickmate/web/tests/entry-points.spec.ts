import { expect, test } from '@playwright/test';

test('Heard remains the main app and PickMate has its own page and styles', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle('Heard — A space to talk');
  await expect(page.getByRole('link', { name: 'Heard home' })).toBeVisible();
  await expect(page.locator('.heard-intro h1')).toBeVisible();
  await expect(page.locator('.welcome-story')).toHaveCount(0);
  await expect(page.locator('body')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
  await expect(page.locator('html')).toHaveCSS('background-color', 'rgb(250, 249, 246)');

  await page.goto('/pickmate.html');
  await expect(page).toHaveTitle('PickMate — Stockroom workspace');
  await expect(page.getByRole('link', { name: 'PickMate home' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start session', exact: true })).toBeEnabled();
  await expect(page.locator('.heard-app')).toHaveCount(0);
  await expect(page.locator('html')).toHaveCSS('background-color', 'rgb(244, 245, 241)');
});
