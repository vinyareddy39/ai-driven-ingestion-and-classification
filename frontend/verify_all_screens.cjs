const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const outputDir = path.resolve('C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

const BASE_URL = 'http://127.0.0.1:5173';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1200, height: 800 },
    acceptDownloads: true
  });

  const page = await context.newPage();

  console.log('Navigating to app...');
  await page.goto(BASE_URL);
  await page.waitForTimeout(2000);

  // 1. TEST SIGN OUT & LOGIN SCREEN
  console.log('1. Testing Sign out & Login Screen...');
  const signOutBtn = await page.$('button:has-text("Sign out")');
  if (signOutBtn) {
    await signOutBtn.click();
    await page.waitForTimeout(1000);
  }

  const loginShot = path.join(outputDir, 'screenshot_login.png');
  await page.screenshot({ path: loginShot });
  console.log('Saved screenshot_login.png');

  // Perform real login
  console.log('Signing in as admin@example.com...');
  await page.fill('input[type="email"]', 'admin@example.com');
  await page.fill('input[type="password"]', 'AdminPass123!');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(2000);

  // 2. DASHBOARD SCREEN
  console.log('2. Testing Dashboard Screen...');
  const dashShot = path.join(outputDir, 'screenshot_dashboard.png');
  await page.screenshot({ path: dashShot });
  console.log('Saved screenshot_dashboard.png');

  // 3. UPLOAD SCREEN & DUPLICATE WARNING
  console.log('3. Testing Upload Screen...');
  await page.click('button:has-text("Upload files")');
  await page.waitForTimeout(1000);
  const uploadShot = path.join(outputDir, 'screenshot_upload.png');
  await page.screenshot({ path: uploadShot });
  console.log('Saved screenshot_upload.png');

  // Upload a file to test duplicate detection
  const testFile = path.resolve('C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e/.user_uploaded/media_1795413804459_e728cad9.pdf');
  if (fs.existsSync(testFile)) {
    console.log('Uploading test file to verify duplicate warning card...');
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.click('button:has-text("Choose files")');
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(testFile);
    await page.waitForTimeout(3500);

    const dupShot = path.join(outputDir, 'screenshot_duplicate_warning.png');
    await page.screenshot({ path: dupShot });
    console.log('Saved screenshot_duplicate_warning.png');
  }

  // Navigate back to dashboard
  await page.click('button:has-text("Back to dashboard")');
  await page.waitForTimeout(1000);

  // 4. REVIEW QUEUE SCREEN
  console.log('4. Testing Review Queue Screen...');
  const checkBtn = await page.$('button:has-text("Check files")');
  if (checkBtn) {
    await checkBtn.click();
    await page.waitForTimeout(2500);
    const reviewShot = path.join(outputDir, 'screenshot_review_queue.png');
    await page.screenshot({ path: reviewShot });
    console.log('Saved screenshot_review_queue.png');

    // Click Approve to test real review action
    const approveBtn = await page.$('button.primary:has-text("Approve")');
    if (approveBtn) {
      console.log('Testing Approve action in Review Queue...');
      await approveBtn.click();
      await page.waitForTimeout(2000);
    }

    // Return to dashboard
    const backLink = await page.$('text=Dashboard');
    if (backLink) {
      await backLink.click();
      await page.waitForTimeout(1500);
    } else {
      await page.goto(BASE_URL);
      await page.waitForTimeout(1500);
    }
  }

  // 5. RESULTS & DOWNLOAD SCREEN
  console.log('5. Testing Results & Download Screen...');
  const firstBatch = await page.$('.row.clickable');
  if (firstBatch) {
    await firstBatch.click();
    await page.waitForTimeout(2000);
    const resShot = path.join(outputDir, 'screenshot_results.png');
    await page.screenshot({ path: resShot });
    console.log('Saved screenshot_results.png');

    // Test real ZIP download
    console.log('Triggering "Download all as ZIP"...');
    const downloadPromise = page.waitForEvent('download', { timeout: 15000 }).catch(e => {
      console.log('Download catch:', e.message);
      return null;
    });

    await page.click('button:has-text("Download all as ZIP")');
    const download = await downloadPromise;
    if (download) {
      const downloadPath = path.join(outputDir, 'test_downloaded.zip');
      await download.saveAs(downloadPath);
      console.log('SUCCESS: ZIP downloaded to:', downloadPath);
      const stats = fs.statSync(downloadPath);
      console.log('Downloaded ZIP file size:', stats.size, 'bytes');
    }
  }

  await browser.close();
  console.log('=== All Screen Verifications Completed ===');
})();
