const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });
  const page = await context.newPage();

  console.log('Navigating to http://127.0.0.1:5173 ...');
  await page.goto('http://127.0.0.1:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // Check if sign-in is required
  const emailInput = page.locator('input[type="email"], input[autocomplete="email"]');
  if (await emailInput.count() > 0 && await emailInput.isVisible()) {
    console.log('Sign-in form detected. Logging in...');
    await emailInput.fill('audit_tester@ecm.local');
    const pwInput = page.locator('input[type="password"]');
    await pwInput.fill('AuditPassword123!');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(2000);
  }

  console.log('Logged in. Waiting for dashboard...');
  await page.waitForTimeout(1000);

  // Find batch row or click on recent batch
  // Look for any batch link or table row
  const batchItem = page.locator('table tr, .batch-card, .batch-item, .batch-name').filter({ hasText: /Batch|doc_16/i }).first();
  if (await batchItem.count() > 0) {
    console.log('Clicking batch row...');
    await batchItem.click();
    await page.waitForTimeout(2000);
  }

  // Find file row for doc_16
  const fileItem = page.locator('table tr, .file-item, .file-name, .doc-item').filter({ hasText: /doc_16/i }).first();
  if (await fileItem.count() > 0) {
    console.log('Clicking doc_16 file row...');
    await fileItem.click();
    await page.waitForTimeout(2500);
  } else {
    // Click any file row
    const anyFile = page.locator('table tr[class*="file"], .file-row, button:has-text("Review"), button:has-text("Open")').first();
    if (await anyFile.count() > 0) {
      console.log('Clicking first file row...');
      await anyFile.click();
      await page.waitForTimeout(2500);
    }
  }

  // Wait for document reader screen
  await page.waitForTimeout(3000);

  const evidenceDir = 'C:/ml/evidence';
  if (!fs.existsSync(evidenceDir)) {
    fs.mkdirSync(evidenceDir, { recursive: true });
  }

  const screenshotPath = path.join(evidenceDir, 'proof_sideways_page_fixed.png');
  await page.screenshot({ path: screenshotPath, fullPage: false });
  console.log(`Saved 1920x1080 screenshot to ${screenshotPath}`);

  const artifactPath = 'C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e/proof_sideways_page_fixed.png';
  try {
    fs.copyFileSync(screenshotPath, artifactPath);
    console.log(`Copied screenshot to artifact directory: ${artifactPath}`);
  } catch (e) {
    console.log('Could not copy to artifact directory:', e.message);
  }

  await browser.close();
}

main().catch(err => {
  console.error('Error during capture:', err);
  process.exit(1);
});
