const path = require('path');
const fs = require('fs');
const { chromium } = require(path.resolve(__dirname, '../frontend/node_modules/@playwright/test'));

const ARTIFACT_DIR = 'C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e';
const LOCAL_DIR = path.resolve(__dirname, '../artifacts/screenshots');

if (!fs.existsSync(LOCAL_DIR)) {
  fs.mkdirSync(LOCAL_DIR, { recursive: true });
}

async function saveScreenshot(page, filename) {
  const localPath = path.join(LOCAL_DIR, filename);
  await page.screenshot({ path: localPath, fullPage: true });
  try {
    const artifactPath = path.join(ARTIFACT_DIR, filename);
    fs.copyFileSync(localPath, artifactPath);
    console.log(`Saved screenshot: ${filename} to both local and artifact dir`);
  } catch (err) {
    console.warn(`Could not copy to artifact dir: ${err.message}`);
  }
}

async function run() {
  console.log('Launching browser...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
  const page = await context.newPage();

  // 1. Authenticate via API
  console.log('Authenticating...');
  const loginRes = await page.request.post('http://127.0.0.1:8000/api/login', {
    data: {
      email: 'verifier_1795515916@enterprise.com',
      password: 'Password123!'
    }
  });

  if (!loginRes.ok()) {
    throw new Error(`Login failed: ${loginRes.status()} ${await loginRes.text()}`);
  }

  const { token, user } = await loginRes.json();
  console.log(`Logged in as ${user.email}`);

  // Set localStorage and navigate to root
  await page.goto('http://localhost:5173');
  await page.evaluate((tok) => {
    localStorage.setItem('token', tok);
  }, token);

  // Reload to pick up session and load dash
  await page.reload();
  await page.waitForTimeout(1000);

  // Open the batch
  const batchId = '44b801ec-d085-44d5-9334-2effeed72567';
  console.log(`Opening batch ${batchId}...`);
  await page.evaluate(async (id) => {
    // Call openBatch on window / App component or fetch directly
    // Through the UI: the past batches table has an "Open" button for this batch
  }, batchId);

  // Look for past batches table and click Open for our batch
  const openButtons = await page.$$('button:has-text("Open")');
  if (openButtons.length > 0) {
    await openButtons[0].click();
  } else {
    // If not found in past batches list, invoke open directly via React or refresh
    await page.evaluate((id) => {
      // Find openBatch button or trigger
    }, batchId);
  }

  await page.waitForSelector('h1:has-text("Results")', { timeout: 10000 });
  await page.waitForTimeout(1500);

  // --- Proof A: Screenshot 1 - Results screen grouped by type ---
  console.log('Capturing Proof A: Results screen...');
  await saveScreenshot(page, 'proof_a_results_screen.png');

  // Helper to open view for a specific file by its name
  async function openFileView(fileName) {
    console.log(`Navigating to file view: ${fileName}...`);
    // Find the row with fileName, then click the "View" button in that row
    const row = page.locator('tr', { has: page.locator(`text="${fileName}"`) });
    const viewBtn = row.locator('button:has-text("View")');
    await viewBtn.click();
    await page.waitForSelector('button:has-text("Back to results")', { timeout: 5000 });
    await page.waitForTimeout(1000);
  }

  async function backToResults() {
    await page.click('button#bk');
    await page.waitForSelector('h1:has-text("Results")', { timeout: 5000 });
    await page.waitForTimeout(500);
  }

  // --- Proof A: Screenshot 2 - Multipage file ---
  await openFileView('proof_05_multipage_report.pdf');
  console.log('Capturing Proof A: Multipage file...');
  await saveScreenshot(page, 'proof_a_multipage_view.png');
  await backToResults();

  // --- Proof A: Screenshot 3 - Table file ---
  await openFileView('proof_04_financial_table.pdf');
  console.log('Capturing Proof A: Table file...');
  await saveScreenshot(page, 'proof_a_table_view.png');
  await backToResults();

  // --- Proof A: Screenshot 4 - Scanned receipt OCR ---
  await openFileView('proof_03_scanned_receipt.pdf');
  console.log('Capturing Proof A: Scanned OCR file...');
  await saveScreenshot(page, 'proof_a_scanned_view.png');
  await backToResults();

  // --- Proof C: Sensitive Details File ---
  await openFileView('proof_11_comprehensive_sensitive.pdf');
  console.log('Capturing Proof C: Sensitive visible...');
  await saveScreenshot(page, 'proof_c_sensitive_visible.png');

  // Turn on "Hide sensitive values"
  console.log('Toggling Hide sensitive values...');
  await page.click('button#btn-hide-sens');
  await page.waitForTimeout(500);
  console.log('Capturing Proof C: Sensitive masked...');
  await saveScreenshot(page, 'proof_c_sensitive_masked.png');

  // Click on one sensitive masked value to reveal it and highlight bbox
  console.log('Revealing Aadhaar number and highlighting bbox...');
  const aadhaarValueSpan = page.locator('.masked-value').first();
  await aadhaarValueSpan.click();
  await page.waitForTimeout(800);
  console.log('Capturing Proof C: Sensitive revealed with bbox...');
  await saveScreenshot(page, 'proof_c_sensitive_revealed_bbox.png');
  await backToResults();

  // --- Proof G: Unplanned file (astronomy log) ---
  await openFileView('proof_12_unplanned_astronomy_log.pdf');
  console.log('Capturing Proof G: Unplanned astronomy log...');
  await saveScreenshot(page, 'proof_g_unplanned_astronomy.png');

  console.log('All screenshots captured successfully!');
  await browser.close();
}

run().catch((err) => {
  console.error('Screenshot capture failed:', err);
  process.exit(1);
});
