/* Timed check: remove preferred targets during a mock and confirm the live plan stays
   coherent (needs/strengths summary + Helps/Costs/Tested-build + next-pick line).
   Optional: NODE_PATH=/path/to/playwright/node_modules node tests/plan_check.cjs */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const base = process.env.DRAFT_TEST_TMP || path.join(root, 'local');
  fs.mkdirSync(base, {recursive:true});
  const temp = fs.mkdtempSync(path.join(base, 'plan-test-'));
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
    await page.waitForSelector('.recommendation');

    const coherent = async (label) => {
      assert.match(await page.locator('#build-summary').textContent(), /Your needs:/, label+': needs summary present');
      assert.match(await page.locator('#build-summary').textContent(), /roster strengths:/, label+': strengths summary present');
      assert.match(await page.locator('#build-summary').textContent(), /provisional Yahoo eligibility/, label+': positions flagged provisional');
      const n = await page.locator('.recommendation').count();
      assert.ok(n>=1 && n<=3, label+': 1-3 featured candidates');
      for(let i=0;i<n;i++){
        const t = await page.locator('.recommendation').nth(i).textContent();
        assert.match(t, /(Helps address:|Addresses:)/, label+': candidate states needs addressed');
        assert.match(t, /Tested build:/, label+': build punt label is separate');
        assert.match(t, /Position:/, label+': position fit shown');
        assert.match(t, /starts at/, label+': start slot shown');
        assert.match(t, /Δ usable starts/, label+': starts/blocked delta shown');
        assert.match(t, /After adding:/, label+': post-addition roster needs recomputed');
      }
      assert.ok(await page.locator('#contingency').count()===1, label+': lower-survival section exists');
      assert.match(await page.locator('#contingency summary').textContent(), /Lower-survival alternatives/, label+': heuristic labelled');
      return n;
    };
    await coherent('initial');

    const removeTopTarget = async () => {
      const name = (await page.locator('.recommendation .rec-name').first().textContent()).replace(/^\d+\.\s*/, '').trim();
      const t0 = Date.now();
      await page.locator('#search').fill(name);
      await page.locator('#search').press('Enter');   // records to the current (opponent) slot -> target removed
      await page.waitForFunction(n=>!document.querySelector('#recommendations').textContent.includes(n), name, {timeout:90000});
      const seconds=(Date.now()-t0)/1000;
      assert.ok(seconds<45, 'must be readable within the 45s clock, took '+seconds.toFixed(1)+'s');
      return {name, seconds};
    };
    const first = await removeTopTarget();
    console.log('removed target', JSON.stringify(first.name), 'recalculated in', first.seconds.toFixed(1)+'s');
    await coherent('after 1st removal');
    const second = await removeTopTarget();
    console.log('removed target', JSON.stringify(second.name), 'recalculated in', second.seconds.toFixed(1)+'s');
    await coherent('after 2nd removal');

    assert.ok(errors.length===0, 'page errors: '+errors.join('; '));
    await page.screenshot({path:path.join(temp,'plan.png'),fullPage:true});
    console.log('Plan workflow checks passed:', {first:first.seconds.toFixed(1)+'s', second:second.seconds.toFixed(1)+'s', errors:errors.length});
  } finally {
    if (browser) await browser.close().catch(()=>{});
    server.kill();
  }
})().catch(e=>{console.error(e);process.exit(1);});
