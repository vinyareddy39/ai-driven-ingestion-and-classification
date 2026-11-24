const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1300, height: 950 } });
  const page = await context.newPage();

  console.log('--- Navigating to http://127.0.0.1:5173 ---');
  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(1000);

  // Try to register/login
  const isAuthScreen = await page.locator('input#em').count();
  if (isAuthScreen > 0) {
    console.log('Authenticating...');
    const email = `testuser_${Date.now()}@example.com`;
    const password = 'TestPassword123!';

    // Register
    await page.click('button#sw');
    await page.waitForTimeout(300);
    await page.fill('input#nm', 'UI Verifier');
    await page.fill('input#em', email);
    await page.fill('input#pw', password);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(800);

    // Login
    await page.fill('input#pw', password);
    await page.click('button[type="submit"]');
    await page.waitForTimeout(1500);
  }

  // Check if on upload screen
  console.log('Checking upload state...');
  const fileInput = await page.locator('input[type="file"]');
  if (await fileInput.count() > 0) {
    // Generate a test file with long text, units, titles
    const sampleText = `EMPLOYMENT & CLINICAL VERIFICATION
Principal Investigator: Dr. Marcus Aurelius Vance, MD, PhD, FACC
Department: Quantitative Pharmacological Research
Residential Address: 742 Evergreen Terrace, Springfield, OR 97477
Blood Pressure: 128/84 mmHg
Prescribed Dosage: Metoprolol Succinate 50 mg daily
Indemnification Scope: The receiving party agrees to defend, indemnify, and hold harmless the disclosing party from any third-party claims arising from unauthorized data disclosure.
Income Tax PAN: ABCDE1234F
Branch IFSC Code: HDFC0001234
Direct Dispatch: support-team@globalpharma.example.com`;

    const tmpFilePath = path.join(__dirname, 'test_sample_doc.txt');
    fs.writeFileSync(tmpFilePath, sampleText, 'utf8');

    console.log('Uploading test document...');
    await fileInput.setInputFiles(tmpFilePath);
    await page.waitForTimeout(2000);

    // Click Read all files
    const readBtn = page.locator('button#rd');
    if (await readBtn.count() > 0) {
      await readBtn.click();
      console.log('Clicked Read all files, waiting for completion...');
      await page.waitForTimeout(4000);
    }
  }

  // Wait for Results screen or transition
  await page.waitForTimeout(2000);

  // Click on the file name button (button.link) to open View screen
  const fileLink = page.locator('button.link');
  if (await fileLink.count() > 0) {
    console.log('Clicking file link to open Check and edit View screen...');
    await fileLink.first().click();
    await page.waitForTimeout(1500);
  }

  // Verify the Details found header
  const detailsFoundHeader = await page.locator('h2:has-text("Details found")').count();
  console.log('Details found header present:', detailsFoundHeader > 0);

  const sensitiveHeader = await page.locator('h2:has-text("Sensitive details")').count();
  console.log('Sensitive details header present (should be 0):', sensitiveHeader);

  const hideSensBtn = await page.locator('button#btn-hide-sens').count();
  console.log('Hide sensitive button present (should be 0):', hideSensBtn);

  // Take screenshot of the view screen
  const outPath1 = path.join(__dirname, '..', 'proof_details_found_view.png');
  const artifactDir = 'C:\\Users\\Sri Vidya Reddy\\.gemini\\antigravity\\brain\\0e89bfe6-519f-49b0-aeeb-e1ece1ac944e';
  const outPath2 = path.join(artifactDir, 'proof_details_found_view.png');

  await page.screenshot({ path: outPath1, fullPage: true });
  fs.copyFileSync(outPath1, outPath2);
  console.log(`Saved screenshot to ${outPath1} and ${outPath2}`);

  await browser.close();
  console.log('UI Verification script completed successfully!');
})();
