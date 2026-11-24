const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 } });
  const page = await context.newPage();

  console.log('--- Step 1: Navigate to http://127.0.0.1:5173 ---');
  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(1000);

  // Take screenshot 1: Auth screen
  await page.screenshot({ path: 'screenshot_1_auth.png' });
  console.log('Saved screenshot_1_auth.png');

  // Verify header and steps
  const headerText = await page.locator('header.bar b').textContent();
  console.log('Header text:', headerText);
  if (headerText !== 'Document Reader') throw new Error(`Expected 'Document Reader', got ${headerText}`);

  const activeStep = await page.locator('.steps li.on').textContent();
  console.log('Active step:', activeStep);
  if (activeStep !== '1 Sign in') throw new Error(`Expected '1 Sign in', got ${activeStep}`);

  // Switch to register
  console.log('--- Step 2: Switch to Register and create account ---');
  await page.click('button#sw');
  await page.waitForTimeout(500);

  const cardH1 = await page.locator('.card.auth h1').textContent();
  console.log('Card header in reg mode:', cardH1);
  if (cardH1 !== 'Create your account') throw new Error(`Expected 'Create your account', got ${cardH1}`);

  await page.fill('input#nm', 'Vidya Reddy');
  await page.fill('input#em', 'vidya_demo@example.com');
  await page.fill('input#pw', 'password123');
  await page.screenshot({ path: 'screenshot_2_register_filled.png' });
  await page.click('button[type="submit"]');
  await page.waitForTimeout(1000);

  // Verify toast
  const regMsg = await page.locator('.card.auth .err').textContent();
  console.log('Registration result message:', regMsg);
  if (!regMsg.includes('Registered. Now sign in.')) throw new Error(`Expected 'Registered. Now sign in.', got ${regMsg}`);

  // Sign in
  console.log('--- Step 3: Sign in with new user ---');
  await page.fill('input#pw', 'password123');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(1500);

  await page.screenshot({ path: 'screenshot_3_upload_screen.png' });
  console.log('Saved screenshot_3_upload_screen.png');

  const uploadStep = await page.locator('.steps li.on').textContent();
  console.log('Active step after login:', uploadStep);
  if (uploadStep !== '2 Upload') throw new Error(`Expected '2 Upload', got ${uploadStep}`);

  const userEmail = await page.locator('header.bar .who').textContent();
  console.log('Logged in user email in header:', userEmail);
  if (userEmail !== 'vidya_demo@example.com') throw new Error(`Expected 'vidya_demo@example.com', got ${userEmail}`);

  // Test sign out and re-sign-in
  console.log('--- Step 4: Test Sign out and Re-sign-in ---');
  await page.click('button#out');
  await page.waitForTimeout(500);
  const outStep = await page.locator('.steps li.on').textContent();
  console.log('Active step after logout:', outStep);
  if (outStep !== '1 Sign in') throw new Error(`Expected '1 Sign in' after signout, got ${outStep}`);

  // Sign back in
  await page.fill('input#em', 'vidya_demo@example.com');
  await page.fill('input#pw', 'password123');
  await page.click('button[type="submit"]');
  await page.waitForTimeout(1500);

  // Upload file
  console.log('--- Step 5: Upload test file ---');
  const filePath = path.resolve('test_files/trap_02_lab_report.pdf');
  const fileInput = await page.locator('input[type="file"]');
  await fileInput.setInputFiles(filePath);
  await page.waitForTimeout(1000);

  // Now on reading screen
  await page.screenshot({ path: 'screenshot_4_reading_screen.png' });
  console.log('Saved screenshot_4_reading_screen.png');

  // Wait for transition to results
  console.log('--- Step 6: Wait for Results screen ---');
  await page.waitForSelector('button#again', { timeout: 10000 });
  await page.waitForTimeout(1000);

  await page.screenshot({ path: 'screenshot_5_results_screen.png' });
  console.log('Saved screenshot_5_results_screen.png');

  const resultsStep = await page.locator('.steps li.on').textContent();
  console.log('Active step on results:', resultsStep);
  if (resultsStep !== '4 Results') throw new Error(`Expected '4 Results', got ${resultsStep}`);

  // Open View screen
  console.log('--- Step 7: Open View screen (Split screen check and edit) ---');
  await page.click('button.link');
  await page.waitForTimeout(1500);

  await page.screenshot({ path: 'screenshot_6_view_screen.png' });
  console.log('Saved screenshot_6_view_screen.png');

  const viewStep = await page.locator('.steps li.on').textContent();
  console.log('Active step on view screen:', viewStep);
  if (viewStep !== '5 Check and edit') throw new Error(`Expected '5 Check and edit', got ${viewStep}`);

  const pageCap = await page.locator('.paperbox .cap').textContent();
  console.log('Page condition caption:', pageCap);
  if (!pageCap.includes('Page condition detected: clean')) {
    throw new Error(`Expected condition caption to contain 'clean', got ${pageCap}`);
  }

  // Add detail row and save
  console.log('--- Step 8: Add detail and save changes ---');
  await page.click('button:has-text("Add a detail")');
  await page.waitForTimeout(500);

  const inputs = await page.locator('.fr input');
  const count = await inputs.count();
  console.log('Total input count in form:', count);
  await inputs.nth(count - 2).fill('Department');
  await inputs.nth(count - 1).fill('Pathology');

  await page.click('button.pri:has-text("Save changes")');
  await page.waitForTimeout(1000);

  await page.screenshot({ path: 'screenshot_7_saved_changes.png' });
  console.log('Saved screenshot_7_saved_changes.png');

  const saveToast = await page.locator('.toast').textContent();
  console.log('Save toast message:', saveToast);
  if (!saveToast.includes('Saved at') || !saveToast.includes('It stays after a refresh.')) {
    throw new Error(`Toast unexpected: ${saveToast}`);
  }

  // Back to results
  console.log('--- Step 9: Return to Results ---');
  await page.click('button#bk');
  await page.waitForTimeout(1000);

  await page.screenshot({ path: 'screenshot_8_results_after_save.png' });
  console.log('Saved screenshot_8_results_after_save.png');

  console.log('\n===========================================');
  console.log('ALL BROWSER E2E TESTS PASSED 100% CLEANLY!');
  console.log('===========================================');

  await browser.close();
})();
