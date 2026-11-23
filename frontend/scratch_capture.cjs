const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const outputDir = path.resolve('C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

const BASE_URL = 'http://127.0.0.1:5173';
const TOKEN = '7v0xX3WljSa89vceTyNKmhDpPO4_NIJ63jIC3mkAKbo';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });

  const page = await context.newPage();

  // 1. Upload Screen
  console.log('Capturing Upload Screen...');
  await page.goto(`${BASE_URL}/?tab=ingest`);
  await page.evaluate((tok) => {
    localStorage.setItem('ecm_token', tok);
    localStorage.setItem('ecm_role', 'admin');
  }, TOKEN);
  await page.reload();
  await page.waitForTimeout(2000);
  const uploadShot = path.join(outputDir, 'screenshot_upload.png');
  await page.screenshot({ path: uploadShot, fullPage: false });
  console.log('Saved:', uploadShot);

  // 2. Dashboard Screen
  console.log('Capturing Dashboard Screen...');
  await page.goto(`${BASE_URL}/?tab=dashboard`);
  await page.waitForTimeout(2500);
  const dashShot = path.join(outputDir, 'screenshot_dashboard.png');
  await page.screenshot({ path: dashShot, fullPage: false });
  console.log('Saved:', dashShot);

  // 3. Review Queue Screen
  console.log('Capturing Review Queue Screen...');
  await page.goto(`${BASE_URL}/?tab=review`);
  await page.waitForTimeout(2500);
  const reviewShot = path.join(outputDir, 'screenshot_review_queue.png');
  await page.screenshot({ path: reviewShot, fullPage: false });
  console.log('Saved:', reviewShot);

  // 4. Duplicate Warning Screen (Batch Results with ALREADY_UPLOADED badge)
  console.log('Capturing Duplicate Warning Screen...');
  await page.goto(`${BASE_URL}/uploads/batch-7d6e31e589f8`);
  await page.waitForTimeout(2500);
  const dupShot = path.join(outputDir, 'screenshot_duplicate_warning.png');
  await page.screenshot({ path: dupShot, fullPage: false });
  console.log('Saved:', dupShot);

  // 5. Login / Role State Screen (Clear auth and visit login view or show header role pill)
  console.log('Capturing Login Screen...');
  await page.evaluate(() => {
    localStorage.removeItem('ecm_token');
    localStorage.removeItem('ecm_role');
  });
  await page.goto(`${BASE_URL}/?tab=login`);
  await page.waitForTimeout(1500);
  const loginShot = path.join(outputDir, 'screenshot_login.png');
  await page.screenshot({ path: loginShot, fullPage: false });
  console.log('Saved:', loginShot);

  await browser.close();
  console.log('All screenshots captured successfully.');
})();
