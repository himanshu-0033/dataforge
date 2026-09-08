import { expect, test } from '@playwright/test';

test.beforeEach(async ({request})=>{expect((await request.get('http://127.0.0.1:8001/api/health')).ok()).toBeTruthy()});

test('fixture session uses real API and labels simulated playback',async({page})=>{
  await page.goto('/');await expect(page.getByRole('heading',{name:'Keep your hands on the work.'})).toBeVisible();
  await page.getByRole('button',{name:'Start session'}).click();
  await expect(page.getByText('Fixture · typed only')).toBeVisible();
  await expect(page.getByText('Synthetic inventory')).toBeVisible();
  await expect(page.getByText('Fixture input is text only. Playback events are simulated and are not audio measurements.')).toBeVisible();
  await page.getByLabel('Type what the worker says').fill('Pick six blue cartons');
  await page.getByRole('button',{name:'Send turn'}).click();
  await expect(page.getByRole('heading',{name:'blue cartons'})).toBeVisible({timeout:15_000});
  await expect(page.locator('.pick-grid').getByText('6',{exact:true})).toBeVisible();
  await expect(page.locator('.pick-grid').getByText('A-03',{exact:true})).toBeVisible();
  await expect(page.locator('.transcript').getByText('Pick 6 blue cartons from aisle A, bin 3. Tell me when you have them.')).toBeVisible();
  await expect(page.locator('.transcript').getByText(/Playback completion estimate|Generated; delivery unverified/).last()).toBeVisible();
  await page.getByLabel('Type what the worker says').fill('I picked them');await page.getByRole('button',{name:'Send turn'}).click();
  await expect(page.getByText('awaiting confirmation')).toBeVisible();
  await page.getByLabel('Type what the worker says').fill('Confirm six blue cartons');await page.getByRole('button',{name:'Send turn'}).click();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  if(test.info().project.name==='chromium')await page.screenshot({path:'../evidence/browser/pickmate-session.png',fullPage:true});
  await page.getByLabel('Type what the worker says').fill('Confirm six blue cartons');await page.getByRole('button',{name:'Send turn'}).click();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('heading',{name:'blue cartons'})).toBeVisible();
  await expect(page.locator('.history-list article')).toHaveCount(1);
  await page.getByRole('button',{name:'End session'}).click();
  await expect(page.getByRole('heading',{name:'Keep your hands on the work.'})).toBeVisible();
});

test('developer faults drive backend correction and stale result fencing',async({page})=>{
  await page.goto('/');await page.getByRole('button',{name:'Start session'}).click();await page.getByRole('button',{name:'Developer'}).click();
  await page.getByLabel('Lookup delay').fill('5000');await page.getByLabel('Return stale lookup after cancellation').check();await page.getByRole('button',{name:'Apply fault settings'}).click();
  await page.getByRole('button',{name:'Close developer panel'}).click();
  await page.getByLabel('Type what the worker says').fill('Pick six blue cartons');await page.getByRole('button',{name:'Send turn'}).click();
  await expect(page.locator('.pick-grid').getByText('Pending',{exact:true})).toBeVisible();
  await page.getByLabel('Type what the worker says').fill('Change to four red cartons');await page.getByRole('button',{name:'Send turn'}).click();
  await expect(page.getByRole('heading',{name:'red cartons'})).toBeVisible({timeout:15_000});
  await expect(page.locator('.pick-grid').getByText('4',{exact:true})).toBeVisible();
  await page.waitForTimeout(5500);await expect(page.getByRole('heading',{name:'red cartons'})).toBeVisible();
});
