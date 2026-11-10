// Real HTTP/UI acceptance. No API fixtures or mocked responses.
// Requires Playwright in NODE_PATH (the desktop bundled runtime is sufficient).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const [baseUrl, expectedFile, outputDir] = process.argv.slice(2);
  assert(baseUrl && expectedFile && outputDir, 'base URL, SQLite-derived expectation file and output directory required');
  const expected = JSON.parse(fs.readFileSync(expectedFile, 'utf8'));
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
  });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
    // Permit only the local application. This does not substitute any response.
    await context.route('**/*', route => new URL(route.request().url()).origin === new URL(baseUrl).origin ? route.continue() : route.abort());
    const page = await context.newPage();
    const pageErrors = [];
    const responses = [];
    page.on('pageerror', error => pageErrors.push(String(error)));
    page.on('response', response => {
      if (/\/api\/(?:v1\/tnved|tnved\/)/.test(response.url())) responses.push({ url: response.url(), status: response.status() });
    });
    await page.goto(`${baseUrl}/tnved`, { waitUntil: 'networkidle' });
    await page.getByText('Источник не проверен. Действительность кодов и ставки не подтверждены.', { exact: true }).waitFor();
    const health = await (await context.request.get(`${baseUrl}/api/health/ready`)).json();
    assert.equal(health.recovered_catalog.snapshot_sha256, expected.snapshot_sha256);
    assert.equal(health.recovered_catalog.nodes, 18014);

    const search = page.getByPlaceholder('Поиск по коду или наименованию…');
    await search.fill(expected.code);
    const hit = page.getByText(expected.name, { exact: true });
    await hit.waitFor();
    await page.screenshot({ path: path.join(outputDir, '01-search.png'), fullPage: true });
    await hit.click();
    const card = page.getByRole('article', { name: 'Позиция восстановленного справочника' });
    await card.getByTestId('recovered-name').waitFor();
    assert.equal(await card.getByTestId('recovered-name').textContent(), expected.name);
    assert.equal(await page.getByTestId('selected-code').textContent(), expected.code);
    assert.deepEqual(await card.getByRole('list', { name: 'Полный путь из источника' }).locator('li').allTextContents(), expected.path);
    await card.getByText('Подтверждённые ставки отсутствуют', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(outputDir, '02-card.png'), fullPage: true });

    // Open the actual parent from the card, then navigate to its child.
    await card.getByRole('navigation', { name: 'Путь к позиции' }).getByRole('button').filter({ hasText: expected.parent_name }).click();
    await page.waitForFunction(name => document.querySelector('[data-testid="recovered-name"]')?.textContent === name, expected.parent_name);
    assert.equal(await page.getByTestId('selected-code').textContent(), expected.parent);
    const childSection = card.locator('section').filter({ has: page.getByRole('heading', { name: 'Дочерние узлы', exact: true }) });
    assert.equal(await childSection.getByRole('button').count(), expected.child_codes.length);
    await page.screenshot({ path: path.join(outputDir, '03-parent-children.png'), fullPage: true });
    await childSection.getByRole('button').filter({ hasText: expected.name }).click();
    await page.waitForFunction(name => document.querySelector('[data-testid="recovered-name"]')?.textContent === name, expected.name);

    const response = await context.request.get(`${baseUrl}/api/v1/tnved/${expected.code}`);
    const detail = await response.json();
    assert.equal(detail.snapshot_sha256, expected.snapshot_sha256);
    assert.equal(detail.name, expected.name);
    assert.deepEqual(detail.path, expected.path);
    assert.equal(detail.rates, null);
    assert.equal(detail.legal_status, 'unverified');
    assert.equal(detail.valid_from, null);
    assert.equal(detail.complete, false);
    assert(responses.length >= 5);
    assert(responses.every(row => row.status === 200), JSON.stringify(responses));
    assert.deepEqual(pageErrors, []);
    const result = {
      status: 'PASS', snapshot_sha256: expected.snapshot_sha256, code: expected.code,
      name: detail.name, path: detail.path, parent: expected.parent, children_count: expected.child_codes.length,
      scenario: ['search code', 'open card', 'compare source name/path', 'show unverified/no rates', 'open parent', 'navigate to child'],
      mocked_responses: 0, page_errors: pageErrors, responses,
    };
    fs.writeFileSync(path.join(outputDir, 'browser-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
