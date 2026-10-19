/* Optional: NODE_PATH=/path/to/playwright/node_modules node tests/browser.cjs */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const base = process.env.DRAFT_TEST_TMP || path.join(root, 'local');
  fs.mkdirSync(base, {recursive:true});
  const temp = fs.mkdtempSync(path.join(base, 'browser-test-'));
  const server = spawn('python3', ['run.py','--no-browser','--port','0','--db',path.join(temp,'draft.sqlite3')], {cwd:root});
  let browser;
  try {
    const url = await new Promise((resolve,reject) => {
      let output = '';
      server.stdout.on('data', chunk => {output+=chunk.toString();const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match)resolve(match[0]);});
      server.stderr.on('data', chunk=>process.stderr.write(chunk));
      server.on('exit',code=>reject(new Error('Server exited '+code)));
    });
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:820,height:950}});
    const errors = [], external = [];
    page.on('pageerror',e=>{errors.push(e.message);console.log('PAGEERROR:',e.message);});
    page.on('request',r=>{if(!r.url().startsWith(url))external.push(r.url());});
    await page.goto(url);
    await page.waitForSelector('.recommendation');
    const count=await page.locator('.recommendation').count();
    assert.ok(count>0 && count<=15);
    assert.match(await page.locator('.recommendation').first().textContent(),/Yahoo ADP/);
    assert.match(await page.locator('.recommendation').first().textContent(),/MC interval/);
    assert.ok(!(await page.locator('#recommendations').textContent()).includes('survival heuristic'));
    assert.match(await page.locator('#current-pick').textContent(),/^#1/);
    // Category labels: equal teams (0.5) are Close; both directions are distinguishable.
    assert.deepEqual(await page.evaluate(()=>[categoryLabel(0.5),categoryLabel(0.7),categoryLabel(0.3)]),['Close','Advantage','Disadvantage']);
    // While it is not my turn, my-pick recording is disabled and names the current picker.
    assert.equal(await page.locator('.recommendation [data-rec-record]').count(),0,'no my-pick record button off-turn');
    assert.match(await page.locator('.recommendation .rec-actions').first().textContent(),/Not your turn/);
    assert.match(await page.locator('#entry-target').textContent(),/#1/);
    assert.match(await page.locator('#entry-target').textContent(),/Shiven/);
    // Contingency gate uses survival to MY pick (availability_at_next), not the following pick.
    assert.deepEqual(await page.evaluate(()=>[recIsContingency({availability_at_next:1.0,availability_later:0.0}),recIsContingency({availability_at_next:0.1,availability_later:1.0}),recIsContingency({availability_at_next:0.4}),recIsContingency({availability_at_next:0.6}),recIsContingency({availability_at_next:null,availability_later:null})]),[false,true,true,false,false]);
    // Empty-search recording order follows market data, not recommendations.
    const initial=await page.evaluate(async()=>await (await fetch('/api/state')).json());
    const expected=initial.players.filter(p=>!p.keeper).sort((a,b)=>a.market_adp-b.market_adp||a.rank-b.rank||a.id.localeCompare(b.id)).slice(0,12).map(p=>p.id);
    assert.deepEqual(await page.locator('#search-results [data-record]').evaluateAll(els=>els.map(el=>el.dataset.record)),expected);
    assert.match(await page.locator('#search-results').textContent(),/ADP/);
    await page.waitForSelector('.priority-row');
    assert.match(await page.locator('#strategy-summary').textContent(),/Current strengths/);
    await page.locator('#search').fill('jokic');
    await page.locator('#search').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#2'));
    await page.locator('#undo').click();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#1'));
    await page.locator('#search').fill('Shai');
    assert.match(await page.locator('#search-results').textContent(),/No available matches/);
    await page.locator('#search').fill('wemb');
    await page.locator('#search').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#2'));
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#2'));
    await page.getByRole('button',{name:'Board',exact:true}).click();
    await page.locator('[data-slot="106"]').click();
    await page.locator('#slot-owner').selectOption('Raul');
    await page.getByRole('button',{name:'Save slot settings'}).click();
    await page.waitForFunction(()=>!document.querySelector('#slot-dialog').open);
    assert.match(await page.locator('[data-slot="106"]').textContent(),/Raul/);
    await page.getByRole('button',{name:'Settings',exact:true}).click();
    await page.locator('[name="punt"][value="TO"]').check();
    await page.getByRole('button',{name:'Apply & recalculate'}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Assumptions saved'));
    await page.getByRole('button',{name:'Team & matchups'}).click();
    await page.waitForSelector('#actual-forecast table');
    await page.getByRole('button',{name:'Research',exact:true}).click();
    assert.match(await page.locator('#persona-validation').textContent(),/default: baseline/);
    assert.match(await page.locator('#persona-observed').textContent(),/Discretionary picks/);
    assert.match(await page.locator('#persona-validation').textContent(),/Cross-season transfer/);
    assert.match(await page.locator('#persona-validation').textContent(),/2023-24/);
    assert.ok((await page.locator('#persona-observed').textContent()).includes('replicated')||(await page.locator('#persona-observed').textContent()).includes('not replicated'));
    await page.locator('#persona-manager').selectOption('Shiven');
    await page.locator('#persona-fields [name="adherence"]').fill('2.5');
    await page.getByRole('button',{name:'Save manager adjustments',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Subjective manager adjustments saved'));
    assert.equal(await page.locator('#persona-fields [name="adherence"]').inputValue(),'2.5');
    await page.getByRole('button',{name:'Reset this manager',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#notice').textContent.includes('Manager assumptions reset'));
    assert.equal(await page.locator('#persona-fields [name="adherence"]').inputValue(),'');
    // Season lab: renders, loads verified matchup metadata, and estimates batch size.
    await page.getByRole('button',{name:'Research',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('[name="bench-mode"]').length>0);
    assert.match(await page.locator('#bench-input-notes').textContent(),/scoring-week dates are verified/);
    assert.ok((await page.locator('#bench-calendar-view').textContent()).includes('2026-10-20'));
    assert.ok((await page.locator('#bench-calendar-view').textContent()).includes('nba_cup'));
    assert.ok((await page.locator('#bench-strategies').inputValue()).includes('policy'));
    assert.match(await page.locator('#bench-estimate').textContent(),/season simulations/);
    page.once('dialog',d=>d.accept());
    await page.locator('#bench-example-assets').click();
    assert.ok((await page.locator('#bench-assets').inputValue()).includes('Illustrative'));
    await page.getByRole('button',{name:'Draft',exact:true}).click();
    await page.screenshot({path:path.join(temp,'draft.png'),fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Page must fit half-screen width');
    // Unknown selection must save without a made-up projection.
    page.once('dialog',d=>d.accept('Unlisted Browser Prospect'));
    await page.locator('#manual-player').click();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#3'));
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#3'));
    const liveState=await page.evaluate(async()=>await (await fetch('/api/state')).json());
    await page.locator('#new-mock').click();
    await page.waitForFunction(()=>document.querySelector('#mode-badge').textContent.includes('PRACTICE'));
    assert.match(await page.locator('#current-pick').textContent(),/^#1/);
    await page.locator('#mock-until').click();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#6'));
    // On my turn the destination is named and enabled: "Record → #6 Oscar".
    await page.waitForFunction(()=>{const b=document.querySelector('.recommendation [data-rec-record]');return b&&!b.disabled;},{timeout:60000});
    assert.match(await page.locator('.recommendation [data-rec-record]').first().textContent(),/#6 Oscar/);
    const teamLabels=await page.locator('#matchups td.adv, #matchups td.close, #matchups td.dis').allTextContents();
    assert.ok(teamLabels.length>0 && teamLabels.every(l=>['Advantage','Disadvantage','Close'].includes(l)),'category labels restricted to the three levels');
    assert.equal(await page.locator('#mock-until').isDisabled(),true);
    // Pick priorities fill search but never auto-record an opponent or user pick.
    await page.waitForFunction(()=>document.querySelectorAll('.priority-row').length>0);
    await page.locator('.priority-row').first().click();
    assert.match(await page.locator('#current-pick').textContent(),/^#6/);
    await page.locator('#search').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#7'));
    assert.equal(await page.locator('#mock-until').isEnabled(),true);
    // Stale recommendation buttons must not record into the new (opponent) slot.
    const staleBtns=page.locator('.recommendation [data-rec-record]');
    const staleN=await staleBtns.count();
    for(let k=0;k<staleN;k++) assert.equal(await staleBtns.nth(k).isDisabled(),true,'stale rec button disabled immediately after my pick');
    const beforeCount=await page.evaluate(async()=>(await (await fetch('/api/state')).json()).state.drafted.length);
    await page.evaluate(()=>{const b=document.querySelector('.recommendation [data-rec-record]');if(b){b.disabled=false;b.click();}});
    await page.waitForTimeout(600);
    const afterCount=await page.evaluate(async()=>(await (await fetch('/api/state')).json()).state.drafted.length);
    assert.equal(afterCount,beforeCount,'stale recommendation click must not record into the opponent slot');
    assert.match(await page.locator('#notice').textContent(),/stale|Not your pick/i);
    await page.locator('#mock-until').click();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#43'));
    page.once('dialog',d=>d.accept());
    await page.locator('#reset-mock').click();
    await page.waitForFunction(()=>document.querySelector('#current-pick').textContent.startsWith('#1'));
    await page.locator('#session-select').selectOption('live');
    await page.waitForFunction(()=>document.querySelector('#mode-badge').textContent==='LIVE DRAFT');
    const after=await page.evaluate(async()=>await (await fetch('/api/state')).json());
    assert.deepEqual(after.state,liveState.state,'Mock actions and reset must never change live state');
    // Local asset/API requests only, even while recording and recalculating.
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
    console.log('Browser checks passed: ADP order, strategy/priorities, keyboard pick, undo, keeper exclusion, reload, ownership, settings, forecasts, unlisted player, mock progression/reset, live isolation, season lab wiring, half-screen layout, no external requests.');
    console.log('Screenshot: '+path.join(temp,'draft.png'));
  } finally {
    if(browser)await browser.close();
    server.kill('SIGINT');
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
