// Targeted real-browser N-001 observation; no successful HTTP responses mocked.
const fs = require('node:fs'), path = require('node:path');
const assert = require('node:assert/strict'), crypto = require('node:crypto');
const { chromium } = require('playwright');

(async () => {
  const [base, expectedFile, out, mode = 'fixed'] = process.argv.slice(2);
  assert(['before', 'fixed'].includes(mode));
  const expected = JSON.parse(fs.readFileSync(expectedFile));
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}) });
  const report = { observer: 'A0, real Chrome, not independent Claude', mode, snapshot_sha256: expected.snapshot_sha256, configurations: [] };
  try {
    for (const [width, scale] of [[1440, 1], [1280, 1], [1280, 1.25]]) {
      const context = await browser.newContext({ viewport: { width: Math.round(width / scale), height: Math.round(1100 / scale) }, deviceScaleFactor: scale });
      const page = await context.newPage(), errors = [], network = [], cases = [];
      page.on('pageerror', e => errors.push(String(e)));
      page.on('response', r => { if (r.url().includes('/api/tnved/') || r.url().includes('/api/v1/tnved/')) network.push({ url: r.url(), status: r.status() }); });
      await page.goto(base + '/tnved', { waitUntil: 'networkidle' });
      const tree = page.getByTestId('tnved-tree'); await tree.waitFor();
      const index = await context.request.get(base + '/tnved');
      assert.equal(crypto.createHash('sha256').update(await index.body()).digest('hex'), expected.frontend_index_sha256);
      async function expand(id) {
        const b = tree.locator(`button[data-node-id="${id}"]`); await b.waitFor();
        if (await b.getAttribute('aria-expanded') === 'false') await b.click();
        await page.waitForFunction(id => document.querySelector(`button[data-node-id="${id}"]`)?.getAttribute('aria-expanded') === 'true', id);
        // Framer animates the container height; wait before measuring its rows.
        await page.waitForTimeout(350);
        return b;
      }
      for (const chapter of ['28', '69', '05', '14', '41', '80']) {
        await expand(expected.chapter_sections[chapter]); const chapterButton = await expand(chapter);
        const rows = expected.markers.filter(r => r.chapter === chapter);
        for (const parent of [...new Set(rows.map(r => r.expected_parent))]) {
          const children = rows.filter(r => r.expected_parent === parent);
          const caption = parent !== chapter;
          if (caption) {
            const button = tree.locator(`button[data-node-id="${parent}"]`); await button.waitFor();
            const visibleWhileCollapsed = await Promise.all(children.map(r => tree.locator(`[data-marker-id="${r.id}"]`).isVisible()));
            assert(visibleWhileCollapsed.every(v => v === (mode === 'before')));
            await button.scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(out, `${width}-${scale}-${children[0].printed_code.slice(1, -1)}-caption-collapsed.png`) });
            await expand(parent);
          }
          for (const row of children) {
            const mark = tree.locator(`[data-marker-id="${row.id}"]`); await mark.waitFor();
            assert.equal(await mark.locator('button').count(), 0);
            const inContainer = caption ? await tree.locator(`button[data-node-id="${parent}"]`).locator('xpath=..').locator(`[data-marker-id="${row.id}"]`).count() === 1 : true;
            assert.equal(inContainer, !caption || mode === 'fixed');
            const order = await tree.locator('[data-node-id], [data-marker-id]').evaluateAll(ns => ns.map(n => n.getAttribute('data-node-id') || n.getAttribute('data-marker-id')));
            const between = (!row.previous_root || order.indexOf(row.previous_root) < order.indexOf(row.id)) && (!row.next_root || order.indexOf(row.id) < order.indexOf(row.next_root));
            assert.equal(between, !caption || mode === 'fixed');
            await mark.scrollIntoViewIfNeeded(); await page.waitForTimeout(350);
            await mark.scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(out, `${width}-${scale}-${row.printed_code.slice(1, -1)}.png`), animations: 'disabled' });
            await mark.click(); assert.equal(await page.getByTestId('selected-code').count(), 0);
            const cardResponse = await context.request.get(base + '/api/v1/tnved/' + row.id), card = await cardResponse.json();
            assert.equal(card.snapshot_sha256, expected.snapshot_sha256); assert.equal(card.selectable, false); assert.equal(card.code, '');
            const crumbParent = card.breadcrumb.at(-2).node_id;
            assert.equal(crumbParent, mode === 'before' && caption ? chapter : parent);
            cases.push({ printed: row.printed_code, expected_parent: parent, in_container: inContainer, between_neighbors: between, breadcrumb_parent: crumbParent });
          }
          if (caption) {
            await tree.locator(`button[data-node-id="${parent}"]`).click();
            if (mode === 'fixed') for (const row of children) await tree.locator(`[data-marker-id="${row.id}"]`).waitFor({ state: 'hidden' });
            await expand(parent);
            for (const row of children) assert.equal(await tree.locator(`[data-marker-id="${row.id}"]`).count(), 1);
          }
        }
        await chapterButton.click();
        for (const row of rows) await tree.locator(`[data-marker-id="${row.id}"]`).waitFor({ state: 'hidden' });
      }
      assert.deepEqual(errors, []); assert(network.every(r => r.status === 200));
      fs.writeFileSync(path.join(out, `${width}-${scale}-DOM.html`), await page.content());
      fs.writeFileSync(path.join(out, `${width}-${scale}-network.json`), JSON.stringify(network, null, 2));
      report.configurations.push({ width, scale, cases, errors, request_count: network.length }); await context.close();
    }
    report.status = mode === 'before' ? 'N001_REPRODUCED' : 'PASS';
    fs.writeFileSync(path.join(out, 'browser-report.json'), JSON.stringify(report, null, 2) + '\n'); console.log(report.status);
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
