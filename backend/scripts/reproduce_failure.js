const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const EVIDENCE_DIR = path.resolve(__dirname, '..', 'evidence', '20261126_212000');
const SCREENSHOTS_DIR = path.join(EVIDENCE_DIR, 'screenshots');
const LOGS_DIR = path.join(EVIDENCE_DIR, 'logs');
const REQ_RES_DIR = path.join(EVIDENCE_DIR, 'requests_responses');

fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
fs.mkdirSync(LOGS_DIR, { recursive: true });
fs.mkdirSync(REQ_RES_DIR, { recursive: true });

async function run() {
  console.log('[REPRODUCE] Starting browser for reproduction test...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  const consoleLogs = [];
  page.on('console', msg => {
    consoleLogs.push({ type: msg.type(), text: msg.text(), time: new Date().toISOString() });
  });

  const networkRequests = [];
  page.on('request', req => {
    networkRequests.push({
      method: req.method(),
      url: req.url(),
      postData: req.postData() ? req.postData().substring(0, 200) : null,
      time: new Date().toISOString()
    });
  });

  page.on('response', async res => {
    try {
      if (res.url().includes('/api/')) {
        const text = await res.text().catch(() => '');
        networkRequests.push({
          type: 'response',
          url: res.url(),
          status: res.status(),
          body: text.substring(0, 500),
          time: new Date().toISOString()
        });
      }
    } catch {}
  });

  try {
    console.log('[REPRODUCE] Navigating to http://localhost:5173...');
    await page.goto('http://localhost:5173');
    await page.waitForTimeout(1000);

    // Register / Sign in
    console.log('[REPRODUCE] Registering new reproduction user...');
    const regToggle = page.locator('button.link:has-text("Register")');
    if (await regToggle.isVisible()) {
      await regToggle.click();
      await page.waitForTimeout(500);
    }
    await page.locator('#nm').fill('Reproduce User');
    const email = `repro_${Date.now()}@test.local`;
    const password = 'Password123!';
    await page.locator('#em').fill(email);
    await page.locator('#pw').fill(password);
    await page.locator('button[type="submit"]:has-text("Register")').click();
    await page.waitForTimeout(1000);

    // Sign in
    console.log('[REPRODUCE] Signing in...');
    await page.locator('#em').fill(email);
    await page.locator('#pw').fill(password);
    await page.locator('button[type="submit"]:has-text("Sign in")').click();
    await page.waitForTimeout(1500);

    // Stage files
    console.log('[REPRODUCE] Staging test files...');
    const testFiles = [
      path.resolve(__dirname, '..', 'test_inputs', 'doc_01_two_column_article.pdf'),
      path.resolve(__dirname, '..', 'test_inputs', 'doc_18_noisy_skewed_scan.png')
    ];
    await page.locator('input[type="file"]').first().setInputFiles(testFiles);
    await page.waitForTimeout(1000);

    // Upload & start reading
    console.log('[REPRODUCE] Clicking Start reading...');
    await page.locator('#start-reading-btn').click();
    await page.waitForTimeout(2000);

    // Wait for processing to complete or enter Results page
    for (let i = 0; i < 30; i++) {
      await page.waitForTimeout(1000);
      const isResults = await page.locator('h1:has-text("Results")').count();
      if (isResults > 0) break;
    }

    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'reproduce_01_results_error.png'), fullPage: true });
    console.log('[REPRODUCE] Captured screenshot: reproduce_01_results_error.png');

    // Check for "Do again" button and click it
    const doAgainBtn = page.locator('button:has-text("🔄 Do again")').first();
    if (await doAgainBtn.isVisible()) {
      console.log('[REPRODUCE] Clicking "Do again" on failing file...');
      await doAgainBtn.click();
      await page.waitForTimeout(2500);
      await page.screenshot({ path: path.join(SCREENSHOTS_DIR, 'reproduce_02_do_again_clicked.png'), fullPage: true });
      console.log('[REPRODUCE] Captured screenshot: reproduce_02_do_again_clicked.png');
    }

  } catch (err) {
    console.error('[REPRODUCE] Error during reproduction:', err);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(LOGS_DIR, 'reproduce_browser_console.json'), JSON.stringify(consoleLogs, null, 2));
    fs.writeFileSync(path.join(REQ_RES_DIR, 'reproduce_network_requests.json'), JSON.stringify(networkRequests, null, 2));
    console.log('[REPRODUCE] Saved logs and network request captures.');
  }
}

run();
