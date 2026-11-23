const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on('console', msg => console.log('BROWSER LOG:', msg.type(), msg.text()));
  page.on('pageerror', err => console.log('BROWSER ERROR:', err.message));
  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(2000);
  const rootHtml = await page.$eval('#root', el => el.innerHTML);
  console.log('Root HTML:', rootHtml);
  await browser.close();
})();
