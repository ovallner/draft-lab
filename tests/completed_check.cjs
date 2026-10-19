/* Focused check: completed draft UI (draft-complete summary + recorded-roster matchups)
   and live/mock isolation. Optional: NODE_PATH=/path/to/playwright/node_modules node tests/completed_check.cjs */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const base = process.env.DRAFT_TEST_TMP || path.join(root, 'local');
  fs.mkdirSync(base, {recursive:true});
  const temp = fs.mkdtempSync(path.join(base, 'completed-test-'));
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
    const page = await browser.newPage({viewport:{width:900,height:1000}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    page.on('dialog',d=>d.accept());
    await page.goto(url);
    await page.waitForSelector('#search');
    await page.waitForFunction(()=>document.querySelector('#save-status').textContent.includes('Saved locally'), null, {timeout:30000});
    // Incomplete draft: recorded-roster matchups exist without any build.
    await page.getByRole('button',{name:'Team & matchups',exact:true}).click();
    await page.waitForSelector('#matchups table');
    const incompleteRows = await page.locator('#matchups table').first().locator('tbody tr').count();
    assert.equal(incompleteRows, 11, 'incomplete draft must show 11 opponent rows');
    await page.getByRole('button',{name:'Draft',exact:true}).click();
    // Complete a mock (practice only) and confirm the completed-draft presentation.
    await page.locator('#new-mock').click();
    await page.waitForFunction(()=>document.querySelector('#mode-badge').textContent.includes('PRACTICE'));
    await page.locator('#mock-complete').click();
    await page.waitForFunction(()=>document.body.classList.contains('draft-complete'), null, {timeout:120000});
    assert.match(await page.locator('#current-pick').textContent(),/Draft complete/);
    assert.equal(await page.locator('#draft-complete-summary').isVisible(), true);
    assert.equal(await page.locator('.entry').isVisible(), false, 'entry panel hidden when complete');
    assert.equal(await page.locator('.recommendations').isVisible(), false, 'empty drafting panel hidden when complete');
    await page.getByRole('button',{name:'Team & matchups',exact:true}).click();
    await page.waitForSelector('#matchups table');
    assert.equal(await page.locator('#matchups table').first().locator('tbody tr').count(), 11, 'completed draft keeps opponent matchups');
    assert.equal(await page.locator('#matchups .adv, #matchups .close, #matchups .dis').count() > 0, true, 'Advantage/Close/Disadvantage labels present');
    await page.locator('#matchup-week').selectOption('2');
    assert.match(await page.locator('#matchups').textContent(),/Final/);
    assert.ok(errors.length===0, 'page errors: '+errors.join('; '));
    await page.screenshot({path:path.join(temp,'completed.png'),fullPage:true});
    console.log('Completed-draft checks passed:',{incompleteRows,errors:errors.length});
  } finally {
    if (browser) await browser.close().catch(()=>{});
    server.kill();
  }
})().catch(e=>{console.error(e);process.exit(1);});
