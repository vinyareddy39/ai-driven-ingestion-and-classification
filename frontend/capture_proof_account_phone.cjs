const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1350, height: 950 } });
  const page = await context.newPage();

  console.log('--- Navigating to http://127.0.0.1:5173 ---');
  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(1000);

  // Authenticate
  const isAuthScreen = await page.locator('input#em').count();
  if (isAuthScreen > 0) {
    console.log('Authenticating...');
    const email = `account_verifier_${Date.now()}@example.com`;
    const password = 'TestPassword123!';

    // Register
    await page.click('button#sw');
    await page.waitForTimeout(300);
    await page.fill('input#nm', 'Account Verifier');
    await page.fill('input#em', email);
    await page.fill('input#pw', password);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(800);

    // Login
    await page.fill('input#pw', password);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(1500);
  }

  // Upload test_account_phone_doc.pdf
  console.log('Uploading test_account_phone_doc.pdf...');
  const fileInput = await page.locator('input[type="file"]');
  const pdfPath = path.resolve(__dirname, '..', 'data', 'test_account_phone_doc.pdf');
  await fileInput.setInputFiles(pdfPath);
  await page.waitForTimeout(2000);

  // Click Read all files
  const readBtn = page.locator('button#rd');
  if (await readBtn.count() > 0) {
    console.log('Clicking Read all files...');
    await readBtn.click();
    await page.waitForTimeout(4000);
  }

  // Wait for Results screen and click file link to open View screen
  console.log('Clicking file link to open View screen...');
  await page.waitForSelector('button.link', { timeout: 10000 });
  await page.click('button.link');
  await page.waitForTimeout(1500);

  // Click the Account Number detail row to highlight on page
  console.log('Clicking Account Number row...');
  const acctRow = page.locator('.fr:has-text("Account Number")');
  if (await acctRow.count() > 0) {
    await acctRow.first().click();
    await page.waitForTimeout(800);
  }

  // Verifications
  const detailsHeader = await page.locator('h2:has-text("Details found")').count();
  console.log('Details found header present:', detailsHeader > 0);

  const sensitiveHeaders = await page.locator('h2:has-text("Sensitive details")').count();
  console.log('Sensitive details header count (should be 0):', sensitiveHeaders);

  const sensitivePills = await page.locator('.pill.sensitive').count();
  console.log('Sensitive pill count (should be 0):', sensitivePills);

  const maskedValues = await page.locator('.masked-value').count();
  console.log('Masked values count (should be 0):', maskedValues);

  // Take screenshot
  const outPath1 = path.resolve(__dirname, '..', 'proof_account_phone_normal.png');
  const artifactDir = 'C:\\Users\\Sri Vidya Reddy\\.gemini\\antigravity\\brain\\0e89bfe6-519f-49b0-aeeb-e1ece1ac944e';
  const outPath2 = path.join(artifactDir, 'proof_account_phone_normal.png');

  await page.screenshot({ path: outPath1, fullPage: true });
  fs.copyFileSync(outPath1, outPath2);
  console.log(`Saved screenshot to ${outPath1} and ${outPath2}`);

  await browser.close();
  console.log('Account & Phone proof verification completed successfully!');
})();
