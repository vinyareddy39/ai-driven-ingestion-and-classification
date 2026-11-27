const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const EVIDENCE_DIR = path.resolve('C:/ml/evidence/screenshots');
const ARTIFACT_DIR = path.resolve('C:/Users/Sri Vidya Reddy/.gemini/antigravity/brain/0e89bfe6-519f-49b0-aeeb-e1ece1ac944e');
fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

async function run() {
  console.log('1. Launching Chromium at 1920x1080...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 }
  });
  const page = await context.newPage();

  console.log('2. Logging in via backend API to get token...');
  const loginRes = await page.request.post('http://127.0.0.1:8000/api/login', {
    data: { email: 'testuser2@example.com', password: 'password123' }
  });
  const authData = await loginRes.json();
  const token = authData.token;
  console.log('Token acquired:', token ? 'YES' : 'NO');

  // 3. Upload eval_26_letter_photo.png via API
  console.log('3. Uploading eval_26_letter_photo.png via API...');
  const filePath = 'C:/ml/backend/tests-data/seeded_eval_30/eval_26_letter_photo.png';
  const fileBuffer = fs.readFileSync(filePath);
  
  const uploadRes = await page.request.post('http://127.0.0.1:8000/api/batches', {
    headers: { 'Authorization': `Bearer ${token}` },
    multipart: {
      files: {
        name: 'eval_26_letter_photo.png',
        mimeType: 'image/png',
        buffer: fileBuffer
      }
    }
  });
  const batchData = await uploadRes.json();
  const batchId = batchData.id;
  console.log('Batch created:', batchId);

  // Poll until batch is done
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(1000);
    const bRes = await page.request.get(`http://127.0.0.1:8000/api/batches/${batchId}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    });
    const bJson = await bRes.json();
    const f = bJson.files && bJson.files[0];
    if (f && f.stage === 'Done') {
      console.log('File is Done! Fields extracted:', f.fields ? f.fields.length : 0);
      break;
    }
    console.log('Waiting for processing, stage:', f ? f.stage : 'none');
  }

  // 4. Open UI and navigate to batch
  console.log('4. Navigating to UI...');
  await page.goto('http://localhost:5173');
  await page.evaluate((tok) => {
    localStorage.setItem('token', tok);
  }, token);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);

  // 5. Click on the first batch Open button
  console.log('5. Clicking Open batch...');
  const openBatchBtn = await page.waitForSelector('button.link:has-text("Open")', { timeout: 10000 });
  await openBatchBtn.click();
  await page.waitForTimeout(1500);

  // 6. Click Review for the photo document
  console.log('6. Clicking Review on document...');
  const viewDocBtn = await page.waitForSelector('button.link:has-text("View"), button:has-text("Review")', { timeout: 10000 });
  await viewDocBtn.click();
  await page.waitForTimeout(2000);

  // 7. Check header
  const headerText = await page.locator('.details-panel-container h3, .panel h3').first().textContent();
  console.log('Header text in panel:', headerText);

  // Screenshot 1: Full-size 1920x1080 overview of photographed document in Review
  const snapOverview = path.join(EVIDENCE_DIR, 'proof_photo_doc_overview.png');
  await page.screenshot({ path: snapOverview });
  console.log('Saved overview screenshot:', snapOverview);

  // 8. Hover over a field row to highlight bounding box directly on printed text
  console.log('8. Hovering over a field row to trigger bounding box highlight...');
  const fieldRows = page.locator('.field-row, tr.field-row, div[style*="flex-direction: column"]');
  const count = await fieldRows.count();
  console.log('Found field rows count:', count);
  if (count > 2) {
    await fieldRows.nth(2).hover();
    await page.waitForTimeout(600);
  }

  const snapBBox = path.join(EVIDENCE_DIR, 'proof_photo_doc_highlight_bbox.png');
  await page.screenshot({ path: snapBBox });
  console.log('Saved bbox screenshot:', snapBBox);

  // Also copy to artifact directory
  fs.copyFileSync(snapOverview, path.join(ARTIFACT_DIR, 'proof_photo_doc_overview.png'));
  fs.copyFileSync(snapBBox, path.join(ARTIFACT_DIR, 'proof_photo_doc_highlight_bbox.png'));
  console.log('Artifacts copied successfully.');

  await browser.close();
  console.log('Done!');
}

run().catch((err) => {
  console.error('Error running photo details verification:', err);
  process.exit(1);
});
