const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const EVIDENCE_DIR = path.resolve(__dirname, '..', 'evidence', '20261126_212000');
const SCREENSHOTS_DIR = path.join(EVIDENCE_DIR, 'screenshots');
const RAW_DIR = path.join(EVIDENCE_DIR, 'raw_outputs');

async function scrapeResultsPage(page) {
  // Scrapes every group and every file row from the real DOM
  return await page.evaluate(() => {
    const data = [];
    const groupDivs = document.querySelectorAll('.grp');
    groupDivs.forEach(grp => {
      const groupHeading = grp.querySelector('h2');
      const groupName = groupHeading ? groupHeading.firstChild.textContent.trim() : 'Unknown';
      const rows = grp.querySelectorAll('table tbody tr');
      rows.forEach(tr => {
        const tds = Array.from(tr.querySelectorAll('td'));
        if (tds.length >= 3) {
          const fileName = tds[0].querySelector('.nm') ? tds[0].querySelector('.nm').textContent.trim() : tds[0].textContent.trim();
          const status = tds[tds.length - 3] ? tds[tds.length - 3].textContent.trim() : '';
          const checkReasons = tds[tds.length - 2] ? tds[tds.length - 2].textContent.trim() : '';
          data.push({
            group: groupName,
            file_name: fileName.split('\n')[0].trim(),
            status: status,
            check_reasons: checkReasons
          });
        }
      });
    });
    return data;
  });
}

async function run() {
  console.log('[MULTI-BATCH] Starting Playwright Chromium for multi-batch real UI upload...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 } });
  const page = await context.newPage();

  try {
    await page.goto('http://localhost:5173');
    await page.waitForTimeout(1000);

    // Register / Sign in
    console.log('[MULTI-BATCH] Registering user for multi-batch test...');
    const regToggle = page.locator('button.link:has-text("Register")');
    if (await regToggle.isVisible()) {
      await regToggle.click();
      await page.waitForTimeout(500);
    }
    const testEmail = `eval_${Date.now()}@eval.test`;
    const testPass = 'Password123!';
    await page.locator('#nm').fill('Batch Evaluator');
    await page.locator('#em').fill(testEmail);
    await page.locator('#pw').fill(testPass);
    await page.locator('button[type="submit"]:has-text("Register")').click();
    await page.waitForTimeout(1000);

    await page.locator('#em').fill(testEmail);
    await page.locator('#pw').fill(testPass);
    await page.locator('button[type="submit"]:has-text("Sign in")').click();
    await page.waitForTimeout(1500);

    // =========================================================================
    // BATCH 1: 30 EXTRA DIVERSE FILES
    // =========================================================================
    console.log('[MULTI-BATCH] === Batch 1: Uploading 30 extra files via UI file picker ===');
    const extraDir = path.resolve(__dirname, '..', 'test_inputs', 'extra_30');
    const extraFiles = fs.readdirSync(extraDir).map(f => path.join(extraDir, f));

    await page.locator('input[type="file"]').first().setInputFiles(extraFiles);
    await page.waitForTimeout(1000);
    await page.locator('#start-reading-btn').click();

    console.log('[MULTI-BATCH] Waiting for Batch 1 (30 files) to complete reading in UI...');
    for (let sec = 0; sec < 60; sec++) {
      await page.waitForTimeout(1000);
      const isResults = await page.locator('h1:has-text("Results")').count();
      if (isResults > 0) break;
    }
    await page.waitForTimeout(2000);

    const b1Screenshot = path.join(SCREENSHOTS_DIR, 'ui_batch1_30_files_results.png');
    await page.screenshot({ path: b1Screenshot, fullPage: true });
    console.log(`[MULTI-BATCH] Captured screenshot: ${b1Screenshot}`);

    const batch1Scraped = await scrapeResultsPage(page);
    console.log(`[MULTI-BATCH] Batch 1 scraped files from DOM: ${batch1Scraped.length}`);

    // Download ZIP
    const downloadPromise = page.waitForEvent('download', { timeout: 10000 }).catch(() => null);
    const zipBtn = page.locator('button:has-text("Download all as ZIP")').first();
    if (await zipBtn.isVisible()) {
      await zipBtn.click();
    }
    const download = await downloadPromise;
    let zipPath = null;
    if (download) {
      zipPath = path.join(RAW_DIR, 'batch1_export.zip');
      await download.saveAs(zipPath);
      console.log(`[MULTI-BATCH] Saved Batch 1 export ZIP to ${zipPath}`);
    }

    // Clear batch to test next batch
    await page.locator('button:has-text("Upload more")').click().catch(() => {});
    await page.waitForTimeout(1000);

    // =========================================================================
    // BATCH 2: 40 BASE MULTI-STRUCTURE DOCUMENTS
    // =========================================================================
    console.log('[MULTI-BATCH] === Batch 2: Uploading 40 multi-structure files via UI file picker ===');
    const baseDir = path.resolve(__dirname, '..', 'test_inputs');
    const baseFiles = fs.readdirSync(baseDir)
      .filter(f => !fs.statSync(path.join(baseDir, f)).isDirectory())
      .slice(0, 40)
      .map(f => path.join(baseDir, f));

    await page.locator('input[type="file"]').first().setInputFiles(baseFiles);
    await page.waitForTimeout(1000);
    await page.locator('#start-reading-btn').click();

    console.log('[MULTI-BATCH] Waiting for Batch 2 (40 files) to complete reading in UI...');
    for (let sec = 0; sec < 75; sec++) {
      await page.waitForTimeout(1000);
      const isResults = await page.locator('h1:has-text("Results")').count();
      if (isResults > 0) break;
    }
    await page.waitForTimeout(2000);

    const b2Screenshot = path.join(SCREENSHOTS_DIR, 'ui_batch2_40_files_results.png');
    await page.screenshot({ path: b2Screenshot, fullPage: true });
    console.log(`[MULTI-BATCH] Captured screenshot: ${b2Screenshot}`);

    const batch2Scraped = await scrapeResultsPage(page);
    console.log(`[MULTI-BATCH] Batch 2 scraped files from DOM: ${batch2Scraped.length}`);

    // Save all scraped UI data
    const totalScraped = {
      timestamp: new Date().toISOString(),
      batch1_extra_files: batch1Scraped,
      batch2_base_files: batch2Scraped,
      batch1_count: batch1Scraped.length,
      batch2_count: batch2Scraped.length,
      total_count: batch1Scraped.length + batch2Scraped.length
    };

    fs.writeFileSync(path.join(RAW_DIR, 'ui_scraped_results.json'), JSON.stringify(totalScraped, null, 2));
    console.log(`[MULTI-BATCH] Saved UI scraped results for ${totalScraped.total_count} files to ${path.join(RAW_DIR, 'ui_scraped_results.json')}`);

  } catch (err) {
    console.error('[MULTI-BATCH] Error in multi-batch runner:', err);
  } finally {
    await browser.close();
  }
}

run();
