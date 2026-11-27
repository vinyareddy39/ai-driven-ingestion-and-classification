const { chromium } = require('c:/ml/frontend/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const EVIDENCE_DIR = path.resolve(__dirname, '..', 'evidence', '20261126-235800');
if (!fs.existsSync(EVIDENCE_DIR)) fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

async function main() {
  console.log('Launching browser for AFTER screenshot (width 1680)...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1680, height: 1050 } });
  const page = await context.newPage();

  page.on('console', msg => console.log('BROWSER CONSOLE:', msg.text()));

  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(1500);

  // Register a fresh user
  const regBtn = page.locator('button.link:has-text("Register")');
  if (await regBtn.isVisible()) {
    await regBtn.click();
    await page.waitForTimeout(300);
  }
  const email = `after_eval_${Date.now()}@test.local`;
  await page.locator('#nm').fill('Evaluator After');
  await page.locator('#em').fill(email);
  await page.locator('#pw').fill('SecretPass123!');
  await page.locator('button[type="submit"]:has-text("Register")').click();
  await page.waitForTimeout(1000);

  // Sign in
  await page.locator('#em').fill(email);
  await page.locator('#pw').fill('SecretPass123!');
  await page.locator('button[type="submit"]:has-text("Sign in")').click();
  await page.waitForTimeout(1500);

  // Upload the invoice
  const invoicePath = path.resolve(__dirname, '..', 'tests-data', 'synthetic_tests', 'syn_01_clean_digital.pdf');
  console.log('Uploading invoice for AFTER:', invoicePath);
  await page.locator('input[type="file"]').first().setInputFiles([invoicePath]);
  await page.waitForTimeout(1000);

  await page.locator('#start-reading-btn').click();
  console.log('Processing invoice, awaiting results...');

  await page.waitForSelector('button:has-text("Review Details"), button:has-text("View"), tr', { timeout: 35000 });
  await page.waitForTimeout(3000);

  const reviewBtn = page.locator('button:has-text("Review Details"), button:has-text("View")').first();
  if (await reviewBtn.isVisible()) {
    await reviewBtn.click();
    await page.waitForTimeout(2000);
  }

  await page.waitForSelector('.fr-row, .fr, h2:has-text("Details found")', { timeout: 15000 });
  await page.waitForTimeout(2000);

  const screenshotPath = path.join(EVIDENCE_DIR, 'after_detail_view_invoice.png');
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log('Saved AFTER detail view screenshot to:', screenshotPath);

  await browser.close();
}

main().catch(err => {
  console.error('ERROR in capture_after_detail:', err);
  process.exit(1);
});
