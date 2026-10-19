/* Focused draft-night reliability rehearsal on a DISPOSABLE database.
   Covers the wrong-slot recommendation regression, corrections, undo, stale/wrong-session
   rejection, session/refresh/restart persistence, the real 45s window, and the ADP fallback.
   Run under caffeinate:
     NODE_PATH=<node_modules> node tests/reliability_rehearsal.cjs
   The real live database and saved mocks are never opened. */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const ROOT = path.resolve(__dirname, '..');

function startServer(dbPath) {
  return new Promise((resolve, reject) => {
    const proc = spawn('python3', ['run.py', '--no-browser', '--port', '0', '--db', dbPath], {cwd: ROOT});
    let out = '';
    proc.stdout.on('data', c => {
      out += c;
      const m = out.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (m) resolve({proc, url: m[0]});
    });
    proc.stderr.on('data', c => process.stderr.write(c));
    proc.on('exit', code => reject(new Error('Server exited ' + code)));
  });
}

(async () => {
  const base = process.env.DRAFT_TEST_TMP || path.join(ROOT, 'local');
  fs.mkdirSync(base, {recursive: true});
  const temp = fs.mkdtempSync(path.join(base, 'reliability-'));
  const db = path.join(temp, 'disposable.sqlite3');
  const report = {assertions: [], turns: [], errors: []};
  let server, browser;
  const log = (event, extra = {}) => { const row = {event, ...extra}; report.assertions.push(event); console.error(JSON.stringify(row)); };

  const waitFresh = (page, timeout = 60000) => page.waitForFunction(() => recFresh(), null, {timeout});
  const slotOf = (page, n) => page.evaluate(n => {
    const s = state.slots[n - 1];
    return {slot: s.slot, owner: s.current_team, player: s.player_id, keeper: s.keeper};
  }, n);
  const waitOscarTurn = (page, timeout = 90000) => page.waitForFunction(() => {
    const c = state.current_slot;
    return c !== null && state.slots[c - 1].current_team === 'Oscar';
  }, null, {timeout});

  try {
    server = await startServer(db);
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1150, height: 950}});
    page.on('pageerror', e => report.errors.push(e.message));
    page.on('dialog', d => d.accept());
    await page.goto(server.url);
    await page.waitForFunction(() => document.querySelector('#save-status').textContent.includes('Saved locally'));
    await page.waitForSelector('.recommendation', {state: 'attached', timeout: 120000});
    await waitFresh(page);

    // 0. intended inputs on a disposable live board
    const snap = await page.evaluate(() => ({
      players: players.length, keepers: state.slots.filter(s => s.keeper).length,
      drafted: state.drafted.length, slot: state.current_slot, mode: session.mode,
      hash: metadata.projection_sha256_short
    }));
    assert.equal(snap.players, 430); assert.equal(snap.keepers, 36);
    assert.equal(snap.drafted, 0); assert.equal(snap.slot, 1); assert.equal(snap.mode, 'live');
    assert.equal(snap.hash, 'b2a59ca7500e');
    log('disposable board loaded with Oct-15 projections');

    // 1. create a mock and reach Oscar's #6
    await page.locator('#new-mock').click();
    await page.waitForFunction(() => session.mode === 'mock' && state.current_slot === 1, null, {timeout: 60000});
    await waitFresh(page);
    const turnT0 = Date.now();
    await page.locator('#mock-until').click();
    await waitOscarTurn(page);
    await waitFresh(page);
    const firstTurnMs = Date.now() - turnT0;
    report.turns.push({slot: 6, ms: firstTurnMs});
    assert.ok(firstTurnMs < 45000, `first turn computation ${firstTurnMs}ms must fit the 45s clock`);
    assert.equal((await slotOf(page, 6)).owner, 'Oscar');
    log('reached #6 with fresh recommendations inside 45s', {ms: firstTurnMs});

    // 2. REGRESSION: correction target left on #7 must not redirect the recommendation record
    await page.getByRole('button', {name: 'Board', exact: true}).click();
    await page.locator('[data-slot="7"]').click();
    await page.locator('#correct-pick').click();
    const targetBefore = await page.evaluate(() => target);
    assert.equal(targetBefore, 7, 'correction target is #7');
    assert.equal((await slotOf(page, 6)).player, null);
    const recId = await page.locator('#recommendations [data-rec-record]').first().getAttribute('data-rec-record');
    await page.locator('#recommendations [data-rec-record]').first().click();
    await page.waitForFunction(({slot, id}) => state.slots[slot - 1].player_id === id, {slot: 6, id: recId}, {timeout: 20000});
    const afterRec = await page.evaluate(() => ({target, slot6: state.slots[5].player_id, slot7: state.slots[6].player_id, current: state.current_slot}));
    assert.equal(afterRec.slot6, recId, 'pick recorded at #6');
    assert.equal(afterRec.slot7, null, 'abandoned #7 correction must stay empty');
    assert.equal(afterRec.target, null, 'correction mode cleared after recommendation record');
    assert.notEqual(afterRec.current, 6);
    log('regression: recommendation recorded at #6 despite open #7 correction');

    // 3. undo restores the turn, then re-record normally
    await page.locator('#undo').click();
    await page.waitForFunction(() => !state.slots[5].player_id && state.current_slot === 6, null, {timeout: 20000});
    await waitFresh(page);
    await page.locator('#recommendations [data-rec-record]').first().click();
    await page.waitForFunction(() => !!state.slots[5].player_id, null, {timeout: 20000});
    log('undo and re-record worked');

    // 4. normal opponent entry via the search box (top row = best available ADP)
    await page.waitForFunction(() => { const c = state.current_slot; return c !== null && state.slots[c - 1].current_team !== 'Oscar'; }, null, {timeout: 60000});
    const opp = await page.evaluate(() => {
      const c = state.current_slot;
      const row = document.querySelector('#search-results [data-record]');
      return {slot: c, owner: state.slots[c - 1].current_team, first: row && row.dataset.record,
              expected: available().sort((a, b) => marketScore(a) - marketScore(b) || a.rank - b.rank || a.id.localeCompare(b.id))[0].id};
    });
    assert.equal(opp.first, opp.expected, 'first empty-search row is best available ADP');
    await page.locator('#search').press('Enter');
    await page.waitForFunction(({slot, id}) => state.slots[slot - 1].player_id === id, {slot: opp.slot, id: opp.first}, {timeout: 20000});
    log('normal opponent entry landed on the current opponent slot');

    // 5. deliberate correction of an earlier filled opponent pick, then undo
    await page.getByRole('button', {name: 'Board', exact: true}).click();
    const filled = await page.evaluate(() => state.slots.filter(s => s.player_id && !s.keeper && s.current_team !== 'Oscar').slice(-1)[0].slot);
    await page.locator(`[data-slot="${filled}"]`).click();
    await page.locator('#correct-pick').click();
    assert.equal(await page.evaluate(() => target), filled, 'correction target set');
    const replacement = await page.evaluate(() => {
      const current = state.slots[target - 1].player_id;
      return available().find(p => p.id !== current).id;
    });
    await page.locator('#search').fill('');
    await page.evaluate(id => { selected = 0; }, replacement);
    // choose the replacement directly through the same handler a click uses
    await page.evaluate(id => record(id), replacement);
    await page.waitForFunction(({slot, id}) => state.slots[slot - 1].player_id === id, {slot: filled, id: replacement}, {timeout: 20000});
    log('deliberate correction wrote to the requested slot');
    await page.locator('#undo').click();
    await page.waitForFunction(({slot, id}) => state.slots[slot - 1].player_id !== id, {slot: filled, id: replacement}, {timeout: 20000});
    log('correction undone');

    // 6. stale and wrong-session submissions rejected
    const rejected = await page.evaluate(async () => {
      const s = await (await fetch('/api/state')).json();
      const other = s.sessions.find(x => x.id !== s.session.id);
      const mk = (sid, rev) => fetch('/api/event', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Draft-Token': s.token},
        body: JSON.stringify({session_id: sid, revision: rev, kind: 'pick', payload: {slot: 1, player_id: 'ht:9196'}})}).then(r => r.status);
      return {stale: await mk(s.session.id, s.state.revision - 1), wrong: other ? await mk(other.id, s.state.revision) : null};
    });
    assert.equal(rejected.stale, 400); assert.equal(rejected.wrong, 400);
    const staleButtons = await page.evaluate(() => {
      result = {...result, revision: -1}; renderState();
      return [...document.querySelectorAll('[data-rec-record]')].every(b => b.disabled);
    });
    assert.ok(staleButtons, 'stale recommendation buttons are disabled');
    log('stale revision and wrong session rejected; stale buttons disabled');
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#save-status').textContent.includes('Saved locally'));
    await waitFresh(page);

    // 7. session switch + refresh preserve the right board
    const mockId = await page.evaluate(() => session.id);
    const draftedBefore = await page.evaluate(() => state.drafted.length);
    await page.locator('#session-select').selectOption('live');
    await page.waitForFunction(() => session?.id === 'live');
    assert.equal(await page.evaluate(() => state.drafted.length), 0, 'live board untouched');
    await page.locator('#session-select').selectOption(mockId);
    await page.waitForFunction(id => session?.id === id, mockId);
    assert.equal(await page.evaluate(() => state.drafted.length), draftedBefore);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#save-status').textContent.includes('Saved locally'));
    assert.equal(await page.evaluate(() => session.mode), 'mock');
    assert.equal(await page.evaluate(() => state.drafted.length), draftedBefore);
    log('session switching and refresh preserved the mock; live board untouched');

    // 8. restart the server on the same disposable DB; picks must survive
    const beforeRestart = await page.evaluate(() => ({drafted: state.drafted.length, slot: state.current_slot, session: session.id}));
    server.proc.kill('SIGINT');
    await new Promise(res => server.proc.once('exit', res));
    server = await startServer(db);
    await page.goto(server.url);
    await page.waitForFunction(() => document.querySelector('#save-status').textContent.includes('Saved locally'));
    const afterRestart = await page.evaluate(() => ({drafted: state.drafted.length, slot: state.current_slot, session: session.id}));
    assert.deepEqual(afterRestart, beforeRestart, 'restart restored the same board');
    log('server restart restored recorded picks', afterRestart);

    // 9. one more timed turn after restart (computation included)
    if (afterRestart.slot !== null) {
      const turn = Date.now();
      const owner = await page.evaluate(() => state.slots[state.current_slot - 1].current_team);
      if (owner !== 'Oscar') {
        await page.locator('#mock-until').click();
        await waitOscarTurn(page);
      }
      await waitFresh(page);
      const ms = Date.now() - turn;
      report.turns.push({slot: await page.evaluate(() => state.current_slot), ms});
      assert.ok(ms < 45000, `turn computation ${ms}ms must fit 45s`);
      log('post-restart turn inside 45s', {ms});
    }

    assert.equal(report.errors.length, 0);
    report.passed = true;
    fs.writeFileSync(path.join(temp, 'reliability_report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } catch (e) {
    report.error = e.stack;
    fs.writeFileSync(path.join(temp, 'reliability_report.json'), JSON.stringify(report, null, 2));
    throw e;
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (server) server.proc.kill('SIGINT');
  }
})().catch(e => { console.error(e); process.exit(1); });
