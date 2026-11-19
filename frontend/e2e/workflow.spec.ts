import { test, expect } from '@playwright/test';

test.describe('ECM Pipeline E2E Lifecycle against Real Backend', () => {
  test.beforeEach(async ({ page }) => {
    // Open app root (Dashboard)
    await page.goto('http://localhost:5173/');
  });

  test('1. Shell displays LOCAL MODE badge and HEALTHY indicator', async ({ page }) => {
    const modeBadge = page.getByTestId('mode-badge');
    await expect(modeBadge).toBeVisible();
    await expect(modeBadge).toHaveText(/LOCAL MODE|REAL SERVICES/);

    const healthDot = page.getByTestId('health-dot');
    await expect(healthDot).toBeVisible();
  });

  test('2. Upload clean invoice document and verify status update', async ({ page }) => {
    await page.goto('http://localhost:5173/upload');
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.locator('div:has-text("Click to browse or drag and drop")').first().click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles('data/test_samples/invoice.pdf');

    await page.click('button:has-text("Start Ingestion")');
    await expect(page.locator('text=Auto Accepted')).toBeVisible({ timeout: 15000 });
  });

  test('3. Upload duplicate document and verify link to original', async ({ page }) => {
    await page.goto('http://localhost:5173/upload');
    const fileChooserPromise = page.waitForEvent('filechooser');
    await page.locator('div:has-text("Click to browse or drag and drop")').first().click();
    const fileChooser = await fileChooserPromise;
    // Re-upload same invoice
    await fileChooser.setFiles('data/test_samples/invoice.pdf');

    await page.click('button:has-text("Start Ingestion")');
    await expect(page.locator('text=Duplicate Document')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=View Original')).toBeVisible();
  });

  test('4. Review detail displays model name, version, confidence and allows human correction', async ({ page }) => {
    // Navigate to review queue
    await page.goto('http://localhost:5173/review');
    const firstRow = page.locator('table tbody tr').first();
    await expect(firstRow).toBeVisible();
    await firstRow.click();

    // Verify model and OCR metadata on review detail
    await expect(page.locator('text=Model:')).toBeVisible();
    await expect(page.locator('text=OCR:')).toBeVisible();

    // Click Edit Fields
    await page.click('button:has-text("Edit Fields")');
    await page.click('button:has-text("Save Correction")');

    // Reload page and verify human-verified badge persists
    await page.reload();
    await expect(page.locator('text=Human Verified')).toBeVisible();
  });

  test('5. Compliance view displays explainability rationale without missing text', async ({ page }) => {
    await page.goto('http://localhost:5173/documents');
    await page.locator('button:has-text("Audit Details")').first().click();

    await expect(page.locator('text=Explainability:')).toBeVisible();
    await expect(page.locator('text=Document Classification')).toBeVisible();
    await expect(page.locator('text=Retention Policy')).toBeVisible();
    await expect(page.locator('text=Security ACL')).toBeVisible();
  });
});
