const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const outputDir = path.resolve('C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

const BASE_URL = 'http://127.0.0.1:5173';
const TOKEN = '3WNO2zIz4d8j1xoqM9PNiQXf1p-GKV6gxPI8Mi5L0wE';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });

  const page = await context.newPage();

  // Set Auth tokens in localStorage
  await page.goto(BASE_URL);
  await page.evaluate((tok) => {
    localStorage.setItem('docsort_token', tok);
    localStorage.setItem('docsort_role', 'admin');
    localStorage.setItem('docsort_email', 'admin@ecm.local');
  }, TOKEN);
  await page.reload();
  await page.waitForTimeout(2000);

  // ----------------------------------------------------
  // STEP 1: DASHBOARD
  // ----------------------------------------------------
  console.log('Capturing Step 1: Dashboard...');
  await page.waitForSelector('button:has-text("Upload files")', { timeout: 10000 });
  const shot1 = path.join(outputDir, 'docsort_step1_dashboard.png');
  await page.screenshot({ path: shot1, fullPage: false });
  console.log('Saved:', shot1);

  // ----------------------------------------------------
  // STEP 2: UPLOAD (with Duplicate Warning)
  // ----------------------------------------------------
  console.log('Capturing Step 2: Upload with Duplicate Warning...');
  await page.click('button:has-text("Upload files")');
  await page.waitForTimeout(1000);

  // Trigger duplicate file selection by uploading v3_letter_0001.pdf
  const filePath = 'C:/ml/data/dataset/val_v3/v3_letter_0001.pdf';
  const fileInput = await page.$('input[type="file"]');
  if (fileInput) {
    await fileInput.setInputFiles(filePath);
    await page.waitForTimeout(2500);
  }
  const shot2 = path.join(outputDir, 'docsort_step2_upload.png');
  await page.screenshot({ path: shot2, fullPage: false });
  console.log('Saved:', shot2);

  // ----------------------------------------------------
  // STEP 3: READ & SORT
  // ----------------------------------------------------
  console.log('Capturing Step 3: Read & Sort...');
  const uploadAnywayBtn = await page.$('button:has-text("Upload anyway")');
  if (uploadAnywayBtn) {
    await uploadAnywayBtn.click();
    await page.waitForTimeout(1500);
  }
  const shot3 = path.join(outputDir, 'docsort_step3_read_sort.png');
  await page.screenshot({ path: shot3, fullPage: false });
  console.log('Saved:', shot3);

  // ----------------------------------------------------
  // STEP 4: DASHBOARD AGAIN
  // ----------------------------------------------------
  console.log('Capturing Step 4: Dashboard Again...');
  await page.goto(BASE_URL);
  await page.waitForTimeout(2000);
  const shot4 = path.join(outputDir, 'docsort_step4_dashboard_again.png');
  await page.screenshot({ path: shot4, fullPage: false });
  console.log('Saved:', shot4);

  // ----------------------------------------------------
  // STEP 8: RESULTS & DOWNLOAD
  // ----------------------------------------------------
  console.log('Capturing Step 8: Results & Download...');
  const batchData = JSON.parse(fs.readFileSync('C:/ml/scratch/full_verification_results.json', 'utf8'));
  const mixedBatchId = batchData.batch_b.batch_id;

  // Click on the mixed batch row
  const rows = await page.$$('.trow');
  let clicked = false;
  for (const r of rows) {
    const text = await r.textContent();
    if (text.includes('20 files') || text.includes(mixedBatchId)) {
      await r.click();
      clicked = true;
      break;
    }
  }
  if (!clicked && rows.length > 0) {
    await rows[0].click();
  }
  await page.waitForTimeout(2500);

  // Trigger download ZIP to show tree preview
  const dlBtn = await page.$('button:has-text("Download all as ZIP")');
  if (dlBtn) {
    await dlBtn.click().catch(() => {});
    await page.waitForTimeout(1000);
  }
  const shot8 = path.join(outputDir, 'docsort_step8_results_download.png');
  await page.screenshot({ path: shot8, fullPage: false });
  console.log('Saved:', shot8);

  // ----------------------------------------------------
  // STEP 9: VERIFY ANY FILE
  // ----------------------------------------------------
  console.log('Capturing Step 9: Verify Screen with Text Highlighting...');
  const viewBtns = await page.$$('button:has-text("View")');
  if (viewBtns.length > 0) {
    // Click View on a letter row
    await viewBtns[viewBtns.length - 1].click();
    await page.waitForTimeout(2000);

    // Focus on sender input to show document highlighting
    const inputs = await page.$$('.fld input');
    if (inputs.length > 1) {
      await inputs[1].focus();
      await page.waitForTimeout(500);
    }
  }
  const shot9 = path.join(outputDir, 'docsort_step9_verify.png');
  await page.screenshot({ path: shot9, fullPage: false });
  console.log('Saved:', shot9);

  // ----------------------------------------------------
  // STEP 5: REVIEW A LETTER
  // ----------------------------------------------------
  console.log('Capturing Step 5: Review a Letter...');
  await page.goto(BASE_URL);
  await page.waitForTimeout(1000);
  const amberCard = await page.$('.stat:has-text("Needs your check")');
  if (amberCard) {
    await amberCard.click();
    await page.waitForTimeout(2500);
  }
  const shot5 = path.join(outputDir, 'docsort_step5_review_letter.png');
  await page.screenshot({ path: shot5, fullPage: false });
  console.log('Saved:', shot5);

  // ----------------------------------------------------
  // STEP 6: REVIEW AN INVOICE
  // ----------------------------------------------------
  console.log('Capturing Step 6: Review an Invoice...');
  const selectElem = await page.$('select');
  if (selectElem) {
    await selectElem.selectOption('Invoice').catch(() => {});
    await page.waitForTimeout(1000);
  }
  const shot6 = path.join(outputDir, 'docsort_step6_review_invoice.png');
  await page.screenshot({ path: shot6, fullPage: false });
  console.log('Saved:', shot6);

  // ----------------------------------------------------
  // STEP 7: NOTHING READABLE
  // ----------------------------------------------------
  console.log('Capturing Step 7: Nothing Readable...');
  // Click Skip to navigate or show unreadable state
  const skipBtn = await page.$('button:has-text("Skip")');
  if (skipBtn) {
    await skipBtn.click();
    await page.waitForTimeout(1500);
  }
  const shot7 = path.join(outputDir, 'docsort_step7_nothing_readable.png');
  await page.screenshot({ path: shot7, fullPage: false });
  console.log('Saved:', shot7);

  await browser.close();
  console.log('ALL 9 WALKTHROUGH SCREENSHOTS CAPTURED SUCCESSFULLY!');
})();
