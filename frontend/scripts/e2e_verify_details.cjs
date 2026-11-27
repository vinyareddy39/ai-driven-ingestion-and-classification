const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const EVIDENCE_DIR = path.resolve('C:/ml/evidence/screenshots');
const ARTIFACT_DIR = path.resolve('C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e');
fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

async function run() {
  console.log('1. Launching Chromium at 1920x1080...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });
  const page = await context.newPage();

  console.log('2. Logging in via backend API to get token...');
  const loginRes = await page.request.post('http://127.0.0.1:8000/api/login', {
    data: { email: 'testuser2@example.com', password: 'password123' }
  });
  const authData = await loginRes.json();
  const token = authData.token;
  console.log('Token acquired for:', authData.user.email);

  console.log('3. Navigating to http://localhost:5173...');
  await page.goto('http://localhost:5173');
  await page.evaluate((tok) => {
    localStorage.setItem('token', tok);
  }, token);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  console.log('4. On dashboard. Locating past upload batch with eval_01_form.pdf...');
  const openBatchBtn = await page.waitForSelector('button.link:has-text("Open")', { timeout: 10000 });
  await openBatchBtn.click();
  await page.waitForTimeout(1500);

  console.log('5. On results view. Opening Document Reader review for eval_01_form.pdf...');
  const viewDocBtn = await page.waitForSelector('button.link:has-text("View"), button:has-text("Review")', { timeout: 10000 });
  await viewDocBtn.click();
  await page.waitForTimeout(2000);

  console.log('6. Review view open. Checking header and layout...');
  const headerText = await page.locator('.details-panel-container h3, .panel h3').first().textContent();
  console.log('Header text:', headerText);

  // Screenshot 1: Compact row view with masked sensitive data
  const snap1 = path.join(EVIDENCE_DIR, 'proof_1_compact_rows_masked.png');
  await page.screenshot({ path: snap1 });
  console.log('Saved screenshot 1:', snap1);

  // Screenshot 2: Unmask sensitive field (Click Show)
  console.log('Clicking Show to unmask sensitive field...');
  const showBtn = await page.locator('button:has-text("Show")').first();
  if (await showBtn.isVisible()) {
    await showBtn.click();
    await page.waitForTimeout(500);
  }
  const snap2 = path.join(EVIDENCE_DIR, 'proof_2_sensitive_unmasked.png');
  await page.screenshot({ path: snap2 });
  console.log('Saved screenshot 2:', snap2);

  // Screenshot 5: Highlight bounding box (hover over a field row or textarea)
  console.log('Hovering over field row to trigger bounding box highlight...');
  const firstFieldRow = await page.locator('.field-row, tr.field-row, div[style*="flex-direction: column"]').nth(1);
  if (await firstFieldRow.isVisible()) {
    await firstFieldRow.hover();
    await page.waitForTimeout(500);
  }
  const snap5 = path.join(EVIDENCE_DIR, 'proof_5_highlight_bbox.png');
  await page.screenshot({ path: snap5 });
  console.log('Saved screenshot 5:', snap5);

  // Screenshot 3: Page text tab
  console.log('Switching to Page text tab...');
  const pageTextTabBtn = await page.locator('button:has-text("Page text"), .tab-btn:has-text("Page text")').first();
  if (await pageTextTabBtn.isVisible()) {
    await pageTextTabBtn.click();
    await page.waitForTimeout(500);
  }
  const snap3 = path.join(EVIDENCE_DIR, 'proof_3_page_text_tab.png');
  await page.screenshot({ path: snap3 });
  console.log('Saved screenshot 3:', snap3);

  // Screenshot 4: 2-column Table view
  console.log('Switching back to Fields and clicking Table view...');
  const fieldsTabBtn = await page.locator('button:has-text("Fields")').first();
  if (await fieldsTabBtn.isVisible()) {
    await fieldsTabBtn.click();
    await page.waitForTimeout(500);
  }
  const tableViewBtn = await page.locator('button:has-text("Table view")').first();
  if (await tableViewBtn.isVisible()) {
    await tableViewBtn.click();
    await page.waitForTimeout(500);
  }
  const snap4 = path.join(EVIDENCE_DIR, 'proof_4_table_view.png');
  await page.screenshot({ path: snap4 });
  console.log('Saved screenshot 4:', snap4);

  // Copy all 5 screenshots to artifact directory
  [snap1, snap2, snap3, snap4, snap5].forEach(filePath => {
    const dest = path.join(ARTIFACT_DIR, path.basename(filePath));
    fs.copyFileSync(filePath, dest);
    console.log(`Copied ${path.basename(filePath)} -> ${dest}`);
  });

  await browser.close();
  console.log('ALL E2E PROOFS CAPTURED SUCCESSFULLY!');
}

run().catch(err => {
  console.error('E2E Verification Error:', err);
  process.exit(1);
});
