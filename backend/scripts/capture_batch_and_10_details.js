const { chromium } = require('c:/ml/frontend/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');

const EVIDENCE_DIR = path.resolve(__dirname, '..', 'evidence', '20261126-235800');
if (!fs.existsSync(EVIDENCE_DIR)) fs.mkdirSync(EVIDENCE_DIR, { recursive: true });

async function main() {
  console.log('Launching browser to capture 10 file detail views and batch results screen...');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1680, height: 1050 } });
  const page = await context.newPage();

  page.on('console', msg => console.log('BROWSER:', msg.text()));

  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(1500);

  // Register fresh user
  const regBtn = page.locator('button.link:has-text("Register")');
  if (await regBtn.isVisible()) {
    await regBtn.click();
    await page.waitForTimeout(300);
  }
  const email = `proof_eval_${Date.now()}@proof.local`;
  await page.locator('#nm').fill('Proof Verifier');
  await page.locator('#em').fill(email);
  await page.locator('#pw').fill('SecretPass123!');
  await page.locator('button[type="submit"]:has-text("Register")').click();
  await page.waitForTimeout(1000);

  // Sign in
  await page.locator('#em').fill(email);
  await page.locator('#pw').fill('SecretPass123!');
  await page.locator('button[type="submit"]:has-text("Sign in")').click();
  await page.waitForTimeout(1500);

  // Select 10 files (5 good, 5 worst) + upload them as a single clean verification batch
  // 5 Good files:
  // 1. syn_01_clean_digital.pdf (clean invoice)
  // 2. tests-data/test_inputs/doc_01_two_column_article.pdf (or clean_pdf from testgen)
  // 3. scratch/testgen/files/scan_1001.pdf
  // 4. scratch/testgen/files/Document (7).pdf
  // 5. scratch/testgen/files/scan_1006.pdf
  // 5 Worst files:
  // 6. rotated_180: IMG_1103.png
  // 7. hard_photo: capture_1101.png
  // 8. paid_stamp: paper_1113.png
  // 9. composite: DOC_1033.pdf (or composite in testgen)
  // 10. blank / unrelated: IMG_1123.pdf

  const testgenFiles = fs.readdirSync(path.resolve(__dirname, '..', 'scratch', 'testgen', 'files'));
  
  // Find specific condition files
  const keyLines = fs.readFileSync(path.resolve(__dirname, '..', 'scratch', 'testgen', 'answer_key.csv'), 'utf-8').split('\n');
  const condMap = {};
  for (const line of keyLines) {
    const parts = line.split(',');
    if (parts.length >= 5) condMap[parts[0].trim()] = parts[4].trim();
  }

  const findFileByCond = (cond) => {
    for (const [fn, c] of Object.entries(condMap)) {
      if (c === cond && fs.existsSync(path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', fn))) return fn;
    }
    return null;
  };

  const goodFiles = [
    path.resolve(__dirname, '..', 'tests-data', 'synthetic_tests', 'syn_01_clean_digital.pdf'),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('clean_pdf') || testgenFiles[0]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('multipage_total_p2') || testgenFiles[1]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', testgenFiles[2]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', testgenFiles[4])
  ];

  const worstFiles = [
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('rotated_180') || testgenFiles[5]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('hard_photo') || testgenFiles[6]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('paid_stamp') || testgenFiles[7]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('composite_invoice_letter') || testgenFiles[8]),
    path.resolve(__dirname, '..', 'scratch', 'testgen', 'files', findFileByCond('blank') || testgenFiles[9])
  ];

  const batchFiles = [...goodFiles, ...worstFiles];
  console.log(`Uploading batch of 10 files: 5 good and 5 worst...`);
  await page.locator('input[type="file"]').first().setInputFiles(batchFiles);
  await page.waitForTimeout(1000);

  await page.locator('#start-reading-btn').click();
  console.log('Processing 10-file verification batch...');

  // Wait for Results screen
  await page.waitForSelector('button:has-text("Review Details"), button:has-text("View"), tr', { timeout: 45000 });
  await page.waitForTimeout(4000);

  // Capture Results screen for this batch (Item 3 of Part 4)
  const batchResultsShot = path.join(EVIDENCE_DIR, 'results_screen_batch.png');
  await page.screenshot({ path: batchResultsShot, fullPage: true });
  console.log('Saved batch results screen screenshot to:', batchResultsShot);

  // Now capture each of the 10 files in detail view
  // Detail buttons can be clicked from results table
  const viewButtons = await page.locator('button:has-text("Review Details"), button:has-text("View")').all();
  console.log(`Found ${viewButtons.length} view buttons in results table.`);

  for (let idx = 0; idx < Math.min(10, viewButtons.length); idx++) {
    const isGood = idx < 5;
    const cat = isGood ? `good_${idx + 1}` : `worst_${idx - 4}`;
    const targetFile = batchFiles[idx];
    const targetBase = path.basename(targetFile);

    console.log(`Navigating to Detail View for file ${idx + 1}/10: ${targetBase} (${cat})...`);
    
    // Click view button
    await viewButtons[idx].click();
    await page.waitForTimeout(2500);

    // Ensure detail view is visible
    await page.waitForSelector('.fr-row, .fr, h2:has-text("Details found")', { timeout: 10000 });
    await page.waitForTimeout(1000);

    const shotName = `detail_view_${cat}_${targetBase}.png`.replace(/[^a-zA-Z0-9_.-]/g, '_');
    const shotPath = path.join(EVIDENCE_DIR, shotName);
    await page.screenshot({ path: shotPath, fullPage: true });
    console.log(`Captured detail view screenshot: ${shotPath}`);

    // Click back to results
    const backBtn = page.locator('button:has-text("Back to results"), button:has-text("← Back")').first();
    if (await backBtn.isVisible()) {
      await backBtn.click();
      await page.waitForTimeout(1500);
    } else {
      // Navigate via top nav
      const navResults = page.locator('a:has-text("Results"), button:has-text("Results")').first();
      if (await navResults.isVisible()) {
        await navResults.click();
        await page.waitForTimeout(1500);
      }
    }
  }

  await browser.close();
  console.log('All screenshots captured successfully!');
}

main().catch(err => {
  console.error('ERROR in capture_batch_and_10_details:', err);
  process.exit(1);
});
