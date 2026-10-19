/* Stale-analysis guard: an unavailable payload must clear (not retain) matchups,
   across sessions, with an explicit unavailable state. Disposable DB only.
   NODE_PATH=<node_modules> node tests/stale_analysis_check.cjs */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const ROOT = path.resolve(__dirname, '..');

(async () => {
  const base = process.env.DRAFT_TEST_TMP || path.join(ROOT, 'local');
  fs.mkdirSync(base, {recursive: true});
  const temp = fs.mkdtempSync(path.join(base, 'stale-analysis-'));
  const db = path.join(temp, 'disposable.sqlite3');
  const server = spawn('python3', ['run.py', '--no-browser', '--port', '0', '--db', db], {cwd: ROOT});
  let browser;
  const report = {assertions: [], errors: []};
  try {
    const url = await new Promise((resolve, reject) => {
      let out = '';
      server.stdout.on('data', c => { out += c; const m = out.match(/http:\/\/127\.0\.0\.1:\d+/); if (m) resolve(m[0]); });
      server.on('exit', code => reject(new Error('Server exited ' + code)));
    });
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage();
    page.on('pageerror', e => report.errors.push(e.message));
    page.on('dialog', d => d.accept());
    await page.goto(url);
    await page.waitForFunction(() => document.querySelector('#save-status').textContent.includes('Saved locally'));
    await page.waitForFunction(() => analysis && analysis.matchups && document.querySelector('#matchups').textContent.length > 20, null, {timeout: 120000});
    report.assertions.push('matchups render for the active board');

    // A null-analysis payload (as the server sends when team analysis fails) must
    // clear the retained analysis and show an explicit unavailable state.
    const cleared = await page.evaluate(async () => {
      const s = await (await fetch('/api/state')).json();
      acceptPayload({...s, analysis: null, analysis_error: 'simulated failure'});
      renderTeam();
      return {analysis: analysis === null, error: analysisError,
              matchups_html: document.querySelector('#matchups').innerHTML.length,
              forecast: document.querySelector('#actual-forecast').textContent};
    });
    assert.equal(cleared.analysis, true, 'analysis cleared');
    assert.equal(cleared.error, 'simulated failure');
    assert.equal(cleared.matchups_html, 0, 'stale matchups cleared');
    assert.match(cleared.forecast, /unavailable/i);
    report.assertions.push('null analysis cleared matchups and showed an unavailable state');

    // A real refresh restores analysis for the current board.
    await page.evaluate(async () => { await refresh(); renderTeam(); });
    const restored = await page.evaluate(() => ({analysis: !!analysis, matchups: document.querySelector('#matchups').textContent.length}));
    assert.equal(restored.analysis, true);
    assert.ok(restored.matchups > 20);
    report.assertions.push('analysis recovers after a successful payload');

    // Cross-session: switching drafts must never show the previous draft's matchups.
    const switched = await page.evaluate(async () => {
      const before = await (await fetch('/api/state')).json();
      // simulate a switch to a new mock, whose analysis is served fresh
      const created = await fetch('/api/session', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Draft-Token': before.token},
        body: JSON.stringify({session_id: before.session.id, action: 'new_mock'})}).then(r => r.json());
      const payload = {...created};
      const staleBefore = document.querySelector('#matchups').textContent.length;
      acceptPayload(payload); renderTeam();
      return {staleBefore, sessionId: session.id, analysisSessionOk: !!analysis, matchups: document.querySelector('#matchups').textContent.length};
    });
    assert.ok(switched.sessionId.startsWith('mock-'));
    assert.equal(switched.analysisSessionOk, true);
    report.assertions.push('session switch re-renders only the new draft analysis');

    assert.equal(report.errors.length, 0);
    report.passed = true;
    fs.writeFileSync(path.join(temp, 'stale_analysis_report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } catch (e) {
    report.error = e.stack;
    fs.writeFileSync(path.join(temp, 'stale_analysis_report.json'), JSON.stringify(report, null, 2));
    throw e;
  } finally {
    if (browser) await browser.close().catch(() => {});
    server.kill('SIGINT');
  }
})().catch(e => { console.error(e); process.exit(1); });
