/* Instrumented draft-night rehearsal. Writes progress continuously so a stall is
   visible even if the process is killed. Disposable mock only.
   NODE_PATH=<node_modules> node tests/draft_night_rehearsal.cjs */
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const base = process.env.DRAFT_TEST_TMP || path.join(root, 'local');
  fs.mkdirSync(base, {recursive:true});
  const temp = fs.mkdtempSync(path.join(base, 'rehearsal-'));
  const db = path.join(temp, 'rehearsal.sqlite3');
  const logFile = path.join(temp, 'rehearsal_progress.log');
  const T0 = Date.now();
  const log = (event, extra={}) => {
    const row = {t:((Date.now()-T0)/1000).toFixed(1), event, ...extra};
    fs.appendFileSync(logFile, JSON.stringify(row)+'\n');
    console.error(JSON.stringify(row));
  };
  const server = spawn('python3', ['run.py','--no-browser','--port','0','--db',db], {cwd:root});
  let browser;
  const report = {policy_mismatches:[], timings:[], assertions:[], errors:[], database:db, log:logFile};
  const deadline = T0 + 9*60*1000;
  const checkTime = (label) => { if (Date.now() > deadline) throw new Error('watchdog: exceeded 9 minutes at '+label); };
  try {
    const url = await new Promise((resolve,reject)=>{
      let out='';
      server.stdout.on('data',c=>{out+=c;const m=out.match(/http:\/\/127\.0\.0\.1:\d+/);if(m)resolve(m[0]);});
      server.stderr.on('data',c=>process.stderr.write(c));
      server.on('exit',code=>reject(new Error('Server exited '+code)));
    });
    log('server_up',{url});
    browser = await chromium.launch({headless:true});
    log('browser_launched');
    const page = await browser.newPage({viewport:{width:1100,height:950}});
    page.on('pageerror',e=>report.errors.push(e.message));
    page.on('dialog',d=>d.accept());
    await page.goto(url,{timeout:60000});
    log('goto_done');
    await page.waitForSelector('#search',{timeout:60000});
    log('search_present');
    await page.waitForFunction(()=>document.querySelector('#save-status').textContent.includes('Saved locally'),null,{timeout:180000});
    log('state_loaded');
    await page.waitForSelector('.recommendation',{state:'attached',timeout:120000});
    const vis = await page.evaluate(()=>{const el=document.querySelector('.recommendation');const r=el.getBoundingClientRect();
      return {visible:!!(el.offsetParent||r.width||r.height)&&getComputedStyle(el).display!=='none'&&r.height>0, w:r.width, h:r.height,
              panelHidden:(document.querySelector('#recommendations').closest('[hidden]')||{}).id||null};});
    log('app_ready',vis);

    const snap = await page.evaluate(async()=>{
      const s = await (await fetch('/api/state')).json();
      const hunter = s.players.find(p=>p.name==="De'Andre Hunter");
      const simmons = s.players.find(p=>p.name==='Ben Simmons');
      return {players:s.players.length, hunter_rank:hunter.rank, hunter_mpg:hunter.mpg,
              simmons_rank:simmons.rank, session:s.session.id, mode:s.session.mode,
              revision:s.state.revision, keeper_count:s.players.filter(p=>p.keeper).length};
    });
    assert.equal(snap.players,430);
    assert.equal(snap.hunter_rank,202);
    assert.equal(snap.simmons_rank,292);
    assert.equal(snap.keeper_count,36);
    report.snapshot = snap;
    report.assertions.push('app loaded the Oct-12 snapshot (Hunter 202 / Simmons 292)');
    log('snapshot_ok',snap);

    const fallback = await page.evaluate(()=>{
      const first = document.querySelector('#search-results [data-record]');
      const expected = available().sort((a,b)=>marketScore(a)-marketScore(b)||a.rank-b.rank||a.id.localeCompare(b.id))[0];
      return {first:first && first.dataset.record, expected:expected.id};
    });
    assert.equal(fallback.first, fallback.expected);
    report.assertions.push('ADP fallback row verified');
    log('adp_fallback_ok');

    await page.waitForFunction(()=>recFresh(),null,{timeout:90000});
    log('initial_fresh');

    // create a DISPOSABLE mock (live board and saved mocks are never touched)
    await page.locator('#new-mock').click();
    await page.waitForFunction(()=>session.mode==='mock' && state.current_slot===1,null,{timeout:60000});
    await page.waitForFunction(()=>recFresh(),null,{timeout:90000});
    log('mock_created',{session:await page.evaluate(()=>session.id)});

    // removal of a preferred target on the opponent's turn
    const before = await page.evaluate(()=>document.querySelector('.recommendation .rec-name').textContent.replace(/^\d+\.\s*/,'').trim());
    const slot1owner = await page.evaluate(()=>state.slots[0].current_team);
    await page.locator('#search').fill(before);
    await page.locator('#search').press('Enter');
    await page.waitForFunction(n=>!document.querySelector('#recommendations').textContent.includes(n), before, {timeout:90000});
    const afterRemoval = await page.evaluate(()=>({slot0:state.slots[0].player_name, owner:state.slots[0].current_team}));
    assert.equal(afterRemoval.slot0, before);
    assert.equal(afterRemoval.owner, slot1owner);
    report.assertions.push('preferred-target removal updated recommendations');
    log('removal_ok',{removed:before,owner:slot1owner});

    const ours = [];
    let guard = 0;
    while (guard++ < 30) {
      checkTime('loop '+guard);
      const st = await page.evaluate(()=>({slot:state.current_slot, mode:session.mode}));
      if (st.slot===null) break;
      const owner = await page.evaluate(()=>state.slots[state.current_slot-1].current_team);
      if (owner !== 'Oscar') {
        log('advance',{from:st.slot,owner});
        await page.locator('#mock-until').click();
        await page.waitForFunction(()=>{const s=state.current_slot;return s===null||state.slots[s-1].current_team==='Oscar';},null,{timeout:90000});
        if (await page.evaluate(()=>state.current_slot===null)) break;
      }
      const slot = await page.evaluate(()=>state.current_slot);
      const t1 = Date.now();
      await page.waitForFunction(()=>recFresh(),null,{timeout:90000});
      const freshMs = Date.now()-t1;
      const info = await page.evaluate(()=>{
        const rs=result.recommendations; const realistic=rs.filter(r=>!recIsContingency(r));
        return {session:session.id, revision:state.revision, result_revision:result.revision, slot:state.current_slot,
                expected:(realistic.length?realistic:rs).slice(0,3).map(r=>r.player.id),
                actual:[...document.querySelectorAll('#recommendations [data-rec-record]')].map(b=>b.dataset.recRecord),
                backend_first:rs[0].player.id, contingent_first:rs[0].availability_at_next,
                owner:state.slots[state.current_slot-1].current_team, backend_seconds:result.elapsed_seconds};
      });
      assert.equal(info.result_revision, info.revision);
      assert.equal(info.owner,'Oscar');
      assert.deepEqual(info.actual, info.expected);
      if (info.expected[0] !== info.backend_first) report.policy_mismatches.push({slot, backend_first:info.backend_first, displayed_first:info.expected[0], availability:info.contingent_first});
      const chosen = info.actual[0];
      await page.locator('#recommendations [data-rec-record]').first().click();
      await page.waitForFunction(({slot,pid})=>state.slots[slot-1].player_id===pid,{slot,pid:chosen},{timeout:15000});
      const recMs = Date.now()-t1;
      ours.push({slot, end_to_end_ms:freshMs, record_ms:recMs, backend_seconds:info.backend_seconds, chosen, displayed_first_is_backend:info.expected[0]===info.backend_first});
      log('pick_recorded',{slot, end_to_end_ms:freshMs, backend_seconds:info.backend_seconds});
      const disabled = await page.evaluate(()=>[...document.querySelectorAll('[data-rec-record]')].every(b=>b.disabled));
      assert.ok(disabled,'record buttons disabled while stale');
      if (ours.length===1) {
        const rej = await page.evaluate(async()=>{
          const s=await (await fetch('/api/state')).json();
          const other=s.sessions.find(x=>x.id!==s.session.id);
          const mk=(sid,rev)=>fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json','X-Draft-Token':s.token},
            body:JSON.stringify({session_id:sid,revision:rev,kind:'pick',payload:{slot:s.state.current_slot,player_id:result.recommendations[0].player.id}})}).then(r=>r.status);
          return {stale:await mk(s.session.id,s.state.revision-1), wrong:other?await mk(other.id,s.state.revision):null};
        });
        assert.equal(rej.stale,400,'stale revision rejected by backend');
        assert.equal(rej.wrong,400,'wrong-session submission rejected by backend');
        report.assertions.push('stale and wrong-session submissions refused');
        log('rejections_ok',rej);
      }
      if (ours.length===3) {
        const mockId=await page.evaluate(()=>session.id);
        const beforeCount=await page.evaluate(()=>state.drafted.length);
        await page.locator('#session-select').selectOption('live');
        await page.waitForFunction(()=>session?.id==='live');
        await page.locator('#session-select').selectOption(mockId);
        await page.waitForFunction(id=>session?.id===id,mockId);
        const afterCount=await page.evaluate(()=>state.drafted.length);
        assert.equal(afterCount,beforeCount,'session switch preserved mock picks');
        report.assertions.push('session switching preserved the mock');
        log('session_switch_ok',{drafted:afterCount});
      }
      if (ours.length===1) {
        await page.locator('#undo').click();
        await page.waitForFunction(({slot})=>!state.slots[slot-1].player_id,{slot},{timeout:15000});
        await page.locator('#search').fill('');
        await page.locator('#search').press('Enter');
        await page.waitForFunction(({slot})=>!!state.slots[slot-1].player_id,{slot},{timeout:15000});
        report.assertions.push('undo and re-record worked');
        log('undo_reok');
        await page.waitForFunction(()=>recFresh(),null,{timeout:90000});
      }
    }
    const completed = await page.evaluate(()=>({done:state.current_slot===null, drafted:state.drafted.length,
      picks:state.slots.filter(s=>s.current_team==='Oscar'&&s.player_id).length,
      roster:owned().length}));
    assert.equal(completed.done,true);
    assert.equal(completed.picks,10);
    assert.equal(completed.roster,13);
    assert.match(await page.locator('#draft-complete-summary').textContent(), /Evaluate this draft/);
    report.assertions.push('mock completed with 13-player roster');
    log('mock_complete',completed);

    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#save-status').textContent.includes('Saved locally'));
    const restored = await page.evaluate(()=>({mode:session.mode,drafted:state.drafted.length,slot:state.current_slot}));
    assert.equal(restored.mode,'mock'); assert.equal(restored.drafted,120); assert.equal(restored.slot,null);
    report.assertions.push('refresh restored the saved mock');
    log('refresh_ok',restored);

    await page.locator('#session-select').selectOption('live');
    await page.waitForFunction(()=>session?.id==='live');
    const live = await page.evaluate(()=>({drafted:state.drafted.length,keepers:state.slots.filter(s=>s.keeper).length}));
    assert.equal(live.drafted,0); assert.equal(live.keepers,36);
    report.assertions.push('live draft untouched by the rehearsal');
    log('live_untouched',live);

    assert.equal(report.errors.length,0);
    report.ours = ours;
    const byPhase = {early:[6], middle:[67,78,91], late:[102,115,126,150]};
    report.clock = {};
    for (const [phase,slots] of Object.entries(byPhase)) {
      const ms = ours.filter(o=>slots.includes(o.slot)).map(o=>o.end_to_end_ms);
      if (ms.length) report.clock[phase] = {n:ms.length, max_ms:Math.max(...ms), mean_ms:Math.round(ms.reduce((a,b)=>a+b,0)/ms.length)};
    }
    const worst = Math.max(...ours.map(o=>o.end_to_end_ms));
    assert.ok(worst < 45000, 'every pick within 45s; worst '+worst);
    report.assertions.push('all picks within the 45-second clock (worst '+worst+'ms)');
    fs.writeFileSync(path.join(temp,'rehearsal_report.json'), JSON.stringify(report,null,2));
    log('DONE',{worst_ms:worst,clock:report.clock});
    console.log(JSON.stringify(report,null,2));
  } catch (e) {
    report.error = e.stack;
    fs.writeFileSync(path.join(temp,'rehearsal_report.json'), JSON.stringify(report,null,2));
    log('FAILED',{error:e.message});
    throw e;
  } finally {
    if (browser) await browser.close().catch(()=>{});
    server.kill('SIGINT');
  }
})().catch(e=>{console.error(e);process.exit(1);});
