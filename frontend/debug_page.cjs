const { chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://127.0.0.1:5173');
  await page.waitForTimeout(2000);
  const html = await page.content();
  console.log('HTML snippet:');
  console.log(html.substring(0, 1000));
  await browser.close();
})();
