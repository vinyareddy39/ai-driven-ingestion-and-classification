const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const EVIDENCE_DIR = path.resolve(__dirname, '..', 'evidence', '20261126_212000');
const SCREENSHOTS_DIR = path.join(EVIDENCE_DIR, 'screenshots');
const LOGS_DIR = path.join(EVIDENCE_DIR, 'logs');
const RAW_DIR = path.join(EVIDENCE_DIR, 'raw_outputs');

async function run() {
  console.log('[STEP 3 FIX] Starting browser for fix verification...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 950 } });
  const page = await context.newPage();

  const consoleLogs = [];
  page.on('console', msg => consoleLogs.push({ type: msg.type(), text: msg.text() }));

  try {
    await page.goto('http://localhost:5173');
    await page.waitForTimeout(1000);

    // Register / Sign in
    console.log('[STEP 3 FIX] Registering test user...');
    const regToggle = page.locator('button.link:has-text("Register")');
    if (await regToggle.isVisible()) {
      await regToggle.click();
      await page.waitForTimeout(500);
    }
    await page.locator('#nm').fill('Verified User');
    const email = `fixed_test_${Date.now()}@verify.local`;
    const password = 'Password123!';
    await page.locator('#em').fill(email);
    await page.locator('#pw').fill(password);
    await page.locator('button[type="submit"]:has-text("Register")').click();
    await page.waitForTimeout(1000);

    // Sign in
    await page.locator('#em').fill(email);
    await page.locator('#pw').fill(password);
    await page.locator('button[type="submit"]:has-text("Sign in")').click();
    await page.waitForTimeout(1500);

    // Upload files: clean digital PDF, noisy image, scan, etc.
    const testFiles = [
      path.resolve(__dirname, '..', 'test_inputs', 'doc_01_two_column_article.pdf'),
      path.resolve(__dirname, '..', 'test_inputs', 'doc_06_table_with_totals.pdf'),
      path.resolve(__dirname, '..', 'test_inputs', 'doc_18_noisy_skewed_scan.png'),
      path.resolve(__dirname, '..', 'test_inputs', 'doc_34_clean_scan_image.png')
    ];
    console.log(`[STEP 3 FIX] Uploading ${testFiles.length} files...`);
    await page.locator('input[type="file"]').first().setInputFiles(testFiles);
    await page.waitForTimeout(1000);

    await page.locator('#start-reading-btn').click();
    console.log('[STEP 3 FIX] Processing batch...');

    // Wait for Results page
    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(1000);
      const isResults = await page.locator('h1:has-text("Results")').count();
      if (isResults > 0) break;
    }

    await page.waitForTimeout(2000);
    const resultsScreenshot = path.join(SCREENSHOTS_DIR, 'step3_01_results_after_fix.png');
    await page.screenshot({ path: resultsScreenshot, fullPage: true });
    console.log(`[STEP 3 FIX] Captured: ${resultsScreenshot}`);

    // Check page text for "couldn't read this one yet"
    const content = await page.content();
    const hasErrorPhrase = content.includes("couldn't read this one yet") || content.includes("keep trying");
    console.log(`[STEP 3 FIX] Contains legacy error phrase: ${hasErrorPhrase}`);

    // Click "Do again" on first file
    const doAgainBtn = page.locator('button:has-text("🔄 Do again")').first();
    let doAgainSuccess = false;
    if (await doAgainBtn.isVisible()) {
      console.log('[STEP 3 FIX] Clicking "🔄 Do again" on first file...');
      await doAgainBtn.click();
      await page.waitForTimeout(2500);
      const reprocessedScreenshot = path.join(SCREENSHOTS_DIR, 'step3_02_do_again_reprocessed.png');
      await page.screenshot({ path: reprocessedScreenshot, fullPage: true });
      console.log(`[STEP 3 FIX] Captured: ${reprocessedScreenshot}`);
      doAgainSuccess = true;
    }

    const testSummary = {
      timestamp: new Date().toISOString(),
      files_uploaded: testFiles.map(f => path.basename(f)),
      legacy_error_phrase_found: hasErrorPhrase,
      do_again_tested: doAgainSuccess,
      results_screenshot: 'step3_01_results_after_fix.png',
      do_again_screenshot: 'step3_02_do_again_reprocessed.png',
      status: (!hasErrorPhrase && doAgainSuccess) ? 'PASS' : 'FAIL'
    };

    fs.writeFileSync(path.join(RAW_DIR, 'step3_fix_verification.json'), JSON.stringify(testSummary, null, 2));
    console.log('[STEP 3 FIX] Verification finished with status:', testSummary.status);

  } catch (err) {
    console.error('[STEP 3 FIX] Error:', err);
  } finally {
    await browser.close();
  }
}

run();
