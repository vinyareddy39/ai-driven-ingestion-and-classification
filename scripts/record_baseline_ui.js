const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const targetPhase = process.argv[2] || 'before';
const EVIDENCE_DIR = path.resolve(__dirname, '..', 'evidence', targetPhase);
const SCREENSHOTS_DIR = path.join(EVIDENCE_DIR, 'screenshots');
fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });

async function main() {
  console.log(`[RECORD UI] Recording baseline for phase: ${targetPhase}`);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 950 } });
  const page = await context.newPage();

  const consoleLogs = [];
  page.on('console', msg => consoleLogs.push({ type: msg.type(), text: msg.text() }));

  try {
    await page.goto('http://localhost:5173');
    await page.waitForTimeout(1500);

    // Register / login
    const regToggle = page.locator('button.link:has-text("Register")');
    if (await regToggle.isVisible()) {
      await regToggle.click();
      await page.waitForTimeout(500);
    }

    const email = `test_${targetPhase}_${Date.now()}@baseline.local`;
    const password = 'Password123!';
    await page.locator('#nm').fill('Baseline User');
    await page.locator('#em').fill(email);
    await page.locator('#pw').fill(password);
    await page.locator('button[type="submit"]:has-text("Register")').click();
    await page.waitForTimeout(1000);

    await page.locator('#em').fill(email);
    await page.locator('#pw').fill(password);
    await page.locator('button[type="submit"]:has-text("Sign in")').click();
    await page.waitForTimeout(1500);

    // Select 1 clean PDF and 1 clean image from tests-data (fallback to data)
    let pdfPath = path.resolve(__dirname, '..', 'tests-data', 'synthetic_tests', 'syn_01_clean_digital.pdf');
    if (!fs.existsSync(pdfPath)) {
      pdfPath = path.resolve(__dirname, '..', 'data', 'synthetic_tests', 'syn_01_clean_digital.pdf');
    }
    let imgPath = path.resolve(__dirname, '..', 'tests-data', 'synthetic_tests', 'syn_02_clean_image.png');
    if (!fs.existsSync(imgPath)) {
      imgPath = path.resolve(__dirname, '..', 'data', 'synthetic_tests', 'syn_02_clean_image.png');
    }

    console.log(`[RECORD UI] Staging files: ${pdfPath}, ${imgPath}`);
    await page.locator('input[type="file"]').first().setInputFiles([pdfPath, imgPath]);
    await page.waitForTimeout(1000);

    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '01_upload_staged.png'), fullPage: true });

    // Click Start reading
    await page.locator('#start-reading-btn').click();
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '02_processing.png'), fullPage: true });

    // Wait for Results screen
    console.log('[RECORD UI] Waiting for processing to finish...');
    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(1000);
      const isResults = await page.locator('h1:has-text("Results")').count();
      if (isResults > 0) break;
    }

    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '03_results_screen.png'), fullPage: true });

    // Scrape result tables
    const resultsData = await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll('table tbody tr'));
      return rows.map(r => {
        const cells = Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim());
        return cells;
      });
    });

    // Click open the first file to inspect details view
    const openFirstBtn = page.locator('table button.link, table a:has-text("Check"), table button:has-text("Check"), table button:has-text("View")').first();
    if (await openFirstBtn.isVisible()) {
      await openFirstBtn.click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, '04_detail_view_pdf.png'), fullPage: true });
    }

    fs.writeFileSync(path.join(EVIDENCE_DIR, 'ui_results.json'), JSON.stringify(resultsData, null, 2));
    fs.writeFileSync(path.join(EVIDENCE_DIR, 'browser_console.log'), JSON.stringify(consoleLogs, null, 2));
    console.log(`[RECORD UI] Successfully captured baseline to ${EVIDENCE_DIR}`);
  } catch (err) {
    console.error('[RECORD UI] Error:', err);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'error_state.png'), fullPage: true });
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

main();
