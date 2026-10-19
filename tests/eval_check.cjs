/* End-to-end completed-draft evaluation journey.
   Optional: NODE_PATH=/path/to/playwright/node_modules node tests/eval_check.cjs */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const base = process.env.DRAFT_TEST_TMP || path.join(root, 'local');
  fs.mkdirSync(base, {recursive:true});
  const temp = fs.mkdtempSync(path.join(base, 'eval-test-'));
  const server = spawn('python3', ['run.py','--no-browser','--port','0','--db',path.join(temp,'draft.sqlite3')], {cwd:root});
  let browser;
  try {
    const url = await new Promise((resolve,reject) => {
      let out='';
      server.stdout.on('data',c=>{out+=c;const m=out.match(/http:\/\/127\.0\.0\.1:\d+/);if(m)resolve(m[0]);});
      server.stderr.on('data',c=>process.stderr.write(c));
      server.on('exit',code=>reject(new Error('Server exited '+code)));
    });
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:960,height:1000}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    page.on('dialog',d=>d.accept());
    await page.goto(url);
    await page.waitForSelector('#search');
    await page.waitForFunction(()=>document.querySelector('#save-status').textContent.includes('Saved locally'), null, {timeout:30000});

    // 1. Incomplete draft is identified, never silently "completed".
    await page.getByRole('button',{name:'Draft review',exact:true}).click();
    await page.waitForTimeout(1500);
    assert.match(await page.locator('#review-issues').textContent(), /not a completed draft/);
    await page.getByRole('button',{name:'Draft',exact:true}).click();

    // 2. Complete a mock, then Evaluate this draft.
    await page.locator('#new-mock').click();
    await page.waitForFunction(()=>document.querySelector('#mode-badge').textContent.includes('PRACTICE'));
    await page.locator('#mock-complete').click();
    await page.waitForFunction(()=>document.body.classList.contains('draft-complete'), null, {timeout:120000});
    assert.match(await page.locator('#draft-complete-summary').textContent(), /Evaluate this draft/);
    await page.locator('#to-evaluate').click();
    await page.waitForFunction(()=>document.querySelector('#review-title').textContent.includes('all recorded rosters'));
    const shots = path.join(root,'local','eval_screens'); fs.mkdirSync(shots,{recursive:true});
    await page.screenshot({path:path.join(shots,'1-ready.png'),fullPage:true});
    assert.match(await page.locator('#review-assessment').textContent(), /What are my strengths and weaknesses/);
    assert.match(await page.locator('#review-assessment').textContent(), /How do I compare with each opponent/);
    assert.match(await page.locator('#review-assessment').textContent(), /usable starts/);

    // 3. Run season simulation (small sample for speed) and see results.
    await page.locator('#eval-seasons').fill('8');
    await page.locator('#eval-run').click();
    await page.waitForTimeout(1200);
    await page.screenshot({path:path.join(shots,'2-running.png'),fullPage:true});
    await page.waitForFunction(()=>/complete/.test(document.querySelector('#eval-progress').textContent), null, {timeout:180000});
    await page.waitForFunction(()=>document.querySelector('#eval-results').textContent.includes('Simulated season outcomes'), null, {timeout:60000});
    await page.screenshot({path:path.join(shots,'3-results.png'),fullPage:true});
    assert.equal(await page.locator('#eval-results tbody tr').count(), 12, 'all 12 teams reported');
    assert.match(await page.locator('#eval-results').textContent(), /not independent draft constructions/);
    assert.match(await page.locator('#eval-results').textContent(), /separate/);

    // 4. Duplicate submissions are idempotent for the same session+revision.
    const jobA = await page.evaluate(()=>JSON.parse(sessionStorage.getItem('ignore')||'null'));
    const dup = await page.evaluate(async()=>{
      const s=await (await fetch('/api/state')).json();
      const before=await (await fetch('/api/evaluations')).json();
      const r=await fetch('/api/evaluate',{method:'POST',headers:{'Content-Type':'application/json','X-Draft-Token':s.token},body:JSON.stringify({session_id:s.session.id,revision:s.state.revision,seasons:8,streaming:'aggressive'})});
      const after=await (await fetch('/api/evaluations')).json();
      return {status:r.status, before:before.evaluations.length, after:after.evaluations.length};
    });
    assert.equal(dup.status, 200);
    assert.equal(dup.after, dup.before, 'duplicate submit must not create a new job');

    // 5. Refresh restores the completed evaluation for this session.
    await page.reload();
    await page.getByRole('button',{name:'Draft review',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#eval-results').textContent.includes('Simulated season outcomes'), null, {timeout:30000});

    // 6. Mock evaluation leaves the live draft unchanged.
    const live = await page.evaluate(async()=>{
      const s=await (await fetch('/api/state')).json();
      const r=await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json','X-Draft-Token':s.token},body:JSON.stringify({session_id:s.session.id,action:'switch',target_id:'live'})});
      const live=await r.json();
      return {drafted:live.state.drafted.length, keepers:live.state.slots.filter(x=>x.keeper).length};
    });
    assert.equal(live.drafted, 0, 'live draft unchanged by mock evaluation');
    assert.equal(live.keepers, 36);

    assert.ok(errors.length===0, 'page errors: '+errors.join('; '));
    await page.screenshot({path:path.join(temp,'eval.png'),fullPage:true});
    console.log('Evaluation journey checks passed:', {dup, live, errors:errors.length});
  } finally {
    if (browser) await browser.close().catch(()=>{});
    server.kill();
  }
})().catch(e=>{console.error(e);process.exit(1);});
