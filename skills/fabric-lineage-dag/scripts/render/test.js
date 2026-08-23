// Headless verification of the built page. Prints JSON; exits 1 on console errors or a failed check.
// Usage: node test.js <lineage.html> <focus-node-id> [search-term] [screenshot-dir]
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const [html, focusId, term = '', shotDir = ''] = process.argv.slice(2);
if (!html || !focusId) { console.error('usage: node test.js <lineage.html> <focus-node-id> [search-term] [screenshot-dir]'); process.exit(1); }
(async () => {
  const body = fs.readFileSync(html, 'utf8');
  const doc = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head><body>' + body + '</body></html>';
  const tmp = path.join(path.dirname(path.resolve(html)), '_test.html');
  fs.writeFileSync(tmp, doc);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
  const errors = [], external = new Set();
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errors.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('request', r => { const u = r.url(); if (/^https?:/.test(u) && !/fonts\.(googleapis|gstatic)\.com/.test(u)) external.add(u); });
  const t0 = Date.now();
  await page.goto('file://' + tmp);
  await page.waitForFunction(() => window.__lineageTimings && window.__lineageTimings.length);
  await page.waitForTimeout(500);
  const shot = async name => { if (shotDir) await page.screenshot({ path: path.join(shotDir, name) }); };
  const R = { loadMs: Date.now() - t0 };
  R.overview = await page.evaluate(() => window.__lineageTimings[0]);
  R.bodyScroll = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
  await shot('lineage-overview.png');
  R.focusExists = await page.evaluate(id => window.__lineage.byId.has(id), focusId);
  if (R.focusExists) {
    await page.evaluate(id => window.__lineage.enterFocus(id), focusId);
    await page.waitForTimeout(400);
    R.focus = await page.evaluate(() => { const d = window.__lineage.disp; return { timing: window.__lineageTimings.at(-1), truncated: d.truncated, nodes: d.nodes.length }; });
    R.detailsText = await page.evaluate(() => document.querySelector('#detailsBody').innerText.slice(0, 400));
    await shot('lineage-focus.png');
    await page.selectOption('#depth', '2'); await page.waitForTimeout(300);
    R.focusDepth2 = await page.evaluate(() => window.__lineageTimings.at(-1));
  }
  if (term) {
    await page.fill('#search', term); await page.waitForTimeout(150);
    R.search = await page.evaluate(() => [...document.querySelectorAll('#searchResults [role=option]')].slice(0, 5).map(o => o.innerText.replace(/\n/g, ' ')));
    await page.keyboard.press('Enter'); await page.waitForTimeout(300);
    R.afterSearch = await page.evaluate(() => ({ selected: window.__lineage.state.selected, mode: window.__lineage.state.mode }));
  }
  await page.evaluate(() => { window.__lineage.exitFocus(); document.documentElement.setAttribute('data-theme', 'dark'); });
  await page.waitForTimeout(400);
  R.dark = await page.evaluate(() => { const cs = getComputedStyle(document.body); return { bg: cs.backgroundColor, color: cs.color }; });
  await shot('lineage-dark.png');
  await page.evaluate(() => { document.documentElement.setAttribute('data-theme', 'light'); document.querySelector('#coverage').open = true; });
  await page.waitForTimeout(200);
  await shot('lineage-panels.png');
  R.errors = errors; R.externalRequests = [...external];
  R.timings = await page.evaluate(() => window.__lineageTimings);
  await browser.close();
  const fail = errors.length || external.size || R.bodyScroll.scrollWidth > R.bodyScroll.clientWidth || !R.focusExists || (term && !R.search.length);
  console.log(JSON.stringify(R, null, 1));
  console.log(fail ? 'FAIL' : 'PASS');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
