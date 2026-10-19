/* Bounded operational audit against disposable SQLite sessions, never the live app. */
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');

(async()=>{
  const root=path.resolve(__dirname,'..');const run=path.resolve(process.env.AUDIT_RUN || path.join(root,'..'));
  const tmp=fs.mkdtempSync(path.join(run,'operational-'));const db=path.join(tmp,'audit.sqlite3');
  const seedScript=`
import sys,json,copy
from app.data import Data
from app.sessions import Sessions
from pathlib import Path
run=Path(sys.argv[1]);s=Sessions(sys.argv[2],Data())
prod=json.loads((run/'pilot/tasks/primary.adp_stochastic.0000.production.json').read_text())
fixtures=[]
for slot in [6,78,150,43]:
 b=copy.deepcopy(next(d for d in prod['decisions'] if d['slot']==slot)['board'])
 if slot==43:
  d=next(d for d in prod['decisions'] if d['slot']==slot)
  targets=[x['id'] for x in d['alternatives'][:2]]
  places=[x for x in b['slots'] if x['slot']<slot and x['current_team']!='Oscar' and not x['keeper'] and x['player_id']]
  for place,pid in zip(reversed(places),targets):place.update(player_id=pid)
 info=s.new_mock()
 for x in b['slots']:
  if x['player_id']:s.store().append('pick',{'slot':x['slot'],'player_id':x['player_id']})
 fixtures.append({'id':info['id'],'slot':slot,'label':'adverse_missing_top_two' if slot==43 else str(slot)})
s.switch(fixtures[0]['id']);s.close();print(json.dumps(fixtures))
`;
  const seeded=spawnSync('python3',['-B','-c',seedScript,run,db],{cwd:root,encoding:'utf8'});
  if(seeded.status!==0)throw new Error(seeded.stderr);
  const fixtures=JSON.parse(seeded.stdout);
  const server=spawn('python3',['-B','run.py','--no-browser','--port','0','--db',db],{cwd:root});
  let browser;const report={passed:false,fixtures:[],assertions:[],errors:[],isolated_database:db};
  try{
    const url=await new Promise((resolve,reject)=>{let out='';server.stdout.on('data',c=>{out+=c;const m=out.match(/http:\/\/127\.0\.0\.1:\d+/);if(m)resolve(m[0]);});server.on('exit',c=>reject(new Error('Server exit '+c)));});
    browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1050,height:900}});
    page.on('pageerror',e=>report.errors.push(e.message));page.on('dialog',d=>d.accept());
    let start=Date.now();await page.goto(url);
    for(let i=0;i<fixtures.length;i++){
      const f=fixtures[i];if(i){start=Date.now();await page.locator('#session-select').selectOption(f.id);}
      await page.waitForFunction(id=>session?.id===id && recFresh() && result.next_pick===state.current_slot, f.id,{timeout:90000});
      const freshMs=Date.now()-start;
      const info=await page.evaluate(()=>{
        const rs=result.recommendations;const realistic=rs.filter(r=>!recIsContingency(r));
        const expected=(realistic.length?realistic:rs).slice(0,3).map(r=>r.player.id);
        return {sid:session.id,revision:state.revision,slot:state.current_slot,expected,
          actual:[...document.querySelectorAll('#recommendations [data-rec-record]')].map(b=>b.dataset.recRecord),
          legal:available().map(p=>p.id),engineSeconds:result.elapsed_seconds};
      });
      assert.deepEqual(info.actual,info.expected);assert.equal(info.slot,f.slot);assert.ok(info.actual.every(x=>info.legal.includes(x)));
      if(i===0){
        const stale=await page.evaluate(async()=>{
          const oldRevision=state.revision;const oldButton=document.querySelector('#recommendations [data-rec-record]');
          const pid=oldButton.dataset.recRecord;const slot=state.current_slot;
          await event('settings',{...state.settings});const after=state.revision;
          oldButton.onclick();
          const r=await fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json','X-Draft-Token':token},body:JSON.stringify({session_id:session.id,revision:oldRevision,kind:'pick',payload:{slot,player_id:pid}})});
          return {before:after,after:state.revision,notice:document.querySelector('#notice').textContent,status:r.status};
        });
        assert.equal(stale.before,stale.after);assert.match(stale.notice,/stale/);assert.equal(stale.status,400);
        report.assertions.push('stale UI handler and stale backend revision refused');
        await page.waitForFunction(()=>recFresh(),null,{timeout:90000});
      }
      if(i===1){
        const rejected=await page.evaluate(async old=>{
          const pid=result.recommendations[0].player.id;
          const r=await fetch('/api/event',{method:'POST',headers:{'Content-Type':'application/json','X-Draft-Token':token},body:JSON.stringify({session_id:old,revision:state.revision,kind:'pick',payload:{slot:state.current_slot,player_id:pid}})});
          return r.status;
        },fixtures[0].id);
        assert.equal(rejected,400);report.assertions.push('wrong-session submission refused');
      }
      await page.locator('#search').fill('');
      const fallback=await page.evaluate(()=>({actual:document.querySelector('#search-results [data-record]')?.dataset.record,
        expected:available().sort((a,b)=>a.market_adp-b.market_adp||a.rank-b.rank||a.id.localeCompare(b.id))[0].id}));
      assert.equal(fallback.actual,fallback.expected);
      const chosen=await page.locator('#recommendations [data-rec-record]').first().getAttribute('data-rec-record');
      const t0=Date.now();await page.locator('#recommendations [data-rec-record]').first().click();
      await page.waitForFunction(({slot,pid})=>state.slots[slot-1].player_id===pid,{slot:f.slot,pid:chosen},{timeout:10000});
      const recordingMs=Date.now()-t0;
      assert.ok(freshMs+recordingMs<45000,`Clock exceeded on ${f.label}: ${freshMs+recordingMs} ms`);
      report.fixtures.push({label:f.label,slot:f.slot,fresh_seconds:freshMs/1000,record_seconds:recordingMs/1000,backend_seconds:info.engineSeconds,featured_order_matches:true});
    }
    await page.locator('#session-select').selectOption('live');
    await page.waitForFunction(()=>session?.id==='live');
    assert.equal(await page.evaluate(()=>state.drafted.length),0);
    assert.equal(report.errors.length,0);report.assertions.push('empty-search ADP fallback verified','disposable live board unchanged','early/middle/late/adverse boards within 45-second clock');
    report.passed=true;
  }catch(e){report.error=e.stack;throw e;}
  finally{
    fs.writeFileSync(path.join(run,'operational.json'),JSON.stringify(report,null,2));
    if(browser)await browser.close();server.kill('SIGINT');
  }
  console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
