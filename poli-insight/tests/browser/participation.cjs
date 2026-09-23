// Run against participation_app.py with Playwright installed.
// Optional: PLAYWRIGHT_MODULE, PARTICIPATION_URL, and PARTICIPATION_SCREENSHOTS.
const modulePath = process.argv[2] || process.env.PLAYWRIGHT_MODULE || 'playwright';
const screenshots = process.argv[3] || process.env.PARTICIPATION_SCREENSHOTS;
const { chromium } = require(modulePath);
const { expect } = require(`${modulePath}/test`);
const path = require('node:path');
const fs = require('node:fs');

(async () => {
  const channel = process.env.BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ channel, headless: true });
  const errors = [];
  try {
    for (const count of [5, 7]) {
      const mobile = count === 7;
      const context = await browser.newContext({
        viewport: mobile ? { width: 375, height: 1100 } : { width: 1280, height: 1000 },
        hasTouch: mobile,
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(`${process.env.PARTICIPATION_URL || 'http://127.0.0.1:8517'}/?count=${count}`);
      await page.getByText('I have read this statement and voluntarily consent to participate.', { exact: true }).click();
      await page.getByRole('button', { name: /Record consent/ }).click();
      const radios = page.getByRole('radio');
      await expect(radios).toHaveCount(count);
      const total = Number((await page.getByText(/^Question 1 of \d+$/).textContent()).split(' of ')[1]);
      const next = page.getByRole('button', { name: /Next/, exact: false });
      const previous = page.getByRole('button', { name: /Previous/ });
      const review = page.getByRole('button', { name: /Save and review/ });
      const position = n => expect(page.getByText(`Question ${n} of ${total}`, { exact: true })).toBeVisible();
      const choose = async index => {
        if (mobile) await radios.nth(index).tap();
        else await radios.nth(index).click();
        await expect(radios.nth(index)).toHaveAttribute('aria-checked', 'true');
      };
      await expect(page.locator('.left-description')).toBeVisible();
      await expect(page.locator('.right-description')).toBeVisible();
      await expect(page.locator('.left-description')).not.toBeEmpty();
      await expect(page.locator('.right-description')).not.toBeEmpty();
      await expect(previous).toBeDisabled();
      await expect(review).toBeDisabled();
      await expect(page.getByRole('radio', { checked: true })).toHaveCount(0);
      // Skip the first question; completing the last one must not unlock review.
      await next.click();
      await position(2);
      for (let n = 2; n <= total; n++) {
        await choose(Math.floor(count / 2));
        if (!mobile && n === 2) {
          await radios.nth(Math.floor(count / 2)).press('ArrowLeft');
          await expect(radios.nth(Math.floor(count / 2) - 1)).toHaveAttribute('aria-checked', 'true');
          await choose(Math.floor(count / 2));
        }
        await expect(review).toBeDisabled();
        if (n < total) { await next.click(); await position(n + 1); }
      }
      await expect(next).toBeDisabled();
      await page.getByRole('combobox', { name: 'Question' }).click();
      // Streamlit virtualizes long option lists: select by label, not DOM index.
      await page.getByRole('combobox', { name: 'Question' }).fill('1. ');
      await page.getByRole('option', { name: /^1\. / }).click();
      await position(1);
      await expect(page.getByRole('radio', { checked: true })).toHaveCount(0);
      await choose(0);
      await expect(review).toBeEnabled();
      await next.click();
      await position(2);
      await expect(radios.nth(Math.floor(count / 2))).toHaveAttribute('aria-checked', 'true');
      await page.getByRole('button', { name: 'Clear answer', exact: true }).click();
      await expect(review).toBeDisabled();
      await previous.click();
      await position(1);
      await next.click();
      await position(2);
      await expect(page.getByRole('radio', { checked: true })).toHaveCount(0);
      // Reload the private resume URL; the first missing required question is 2.
      await page.reload();
      await page.getByRole('button', { name: 'Continue to questionnaire', exact: true }).click();
      await position(2);
      await expect(page.getByRole('radio', { checked: true })).toHaveCount(0);
      await choose(count - 1);
      await expect(review).toBeEnabled();
      if (mobile) {
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        const left = await page.locator('.criterion').first().boundingBox();
        const right = await page.locator('.criterion').last().boundingBox();
        expect(right.y).toBeGreaterThan(left.y + left.height);
      }
      if (screenshots) {
        fs.mkdirSync(screenshots, { recursive: true });
        // Streamlit scrolls its main panel, so use a tall viewport to capture
        // the whole question, descriptions, and navigation together.
        const viewport = page.viewportSize();
        await page.setViewportSize({ width: viewport.width, height: mobile ? 2400 : 1800 });
        await page.getByTestId('stMain').evaluate(element => element.scrollTo(0, 0));
        await page.screenshot({
          path: path.join(screenshots, `questionnaire-${count}.png`), fullPage: true,
        });
        await page.setViewportSize(viewport);
      }
      await review.click();
      await expect(page.getByText('Review your responses', { exact: true })).toBeVisible();
      await expect(radios).toHaveCount(0);
      await page.getByRole('button', { name: /Edit answers/ }).click();
      await position(2);
      await expect(radios.last()).toHaveAttribute('aria-checked', 'true');
      await choose(1);
      await review.click();
      const submit = page.getByRole('button', { name: /Submit questionnaire/ });
      await expect(submit).toBeDisabled();
      await page.getByText('I have reviewed these responses and understand submission is final.', { exact: true }).click();
      await submit.click();
      await expect(page.getByText('Your questionnaire has been submitted successfully.', { exact: true })).toBeVisible();
      await page.reload();
      await expect(page.getByText('Your questionnaire has been submitted successfully.', { exact: true })).toBeVisible();
      console.log(`PASS ${count} points, ${total} questions: consent, skip, navigation, selector, clear, resume, review/edit, real submission${mobile ? ', mobile touch and layout' : ', keyboard'}`);
      await context.close();
    }
    expect(errors).toEqual([]);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
