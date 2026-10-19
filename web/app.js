'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const normalize = s => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, '');
const pct = x => `${Math.round(x * 100)}%`;
const index = x => (x * 100).toFixed(1);
function categoryLabel(p){ return p > .65 ? 'Advantage' : p < .35 ? 'Disadvantage' : 'Close'; }
function categoryClass(p){ return p > .65 ? 'adv' : p < .35 ? 'dis' : 'close'; }
// A candidate's OWN categories it helps / costs (from its z-scores), kept separate from
// the punt labels of the tested build.
function catHelp(z){ return [0,1,2,3,4,5,6,7,8].filter(j=>z[j]>.5).sort((a,b)=>z[b]-z[a]).slice(0,2).map(j=>metadata.categories[j]); }
function catCost(z){ return [0,1,2,3,4,5,6,7,8].filter(j=>z[j]<-.5).sort((a,b)=>z[a]-z[b]).slice(0,2).map(j=>metadata.categories[j]); }
// A featured target must be realistically available AT MY PICK (availability_at_next),
// not necessarily at my following pick. Survival to a later pick must never hide a
// player who is available now.
function recIsContingency(r){ return r.availability_at_next !== null && r.availability_at_next !== undefined && r.availability_at_next < .5; }
function recFresh(){ return !!result && result.session_id === session.id && result.revision === state.revision; }
function disableStaleRecButtons(){ if (recFresh()) return; document.querySelectorAll('[data-rec-record]').forEach(b => { b.disabled = true; }); }
const adpText = p => p.adp === null || p.adp === undefined ? `Yahoo ADP unavailable · Est. market ${Number(p.market_adp ?? p.rank).toFixed(1)} · Hashtag #${p.rank}` : `Yahoo ADP ${p.adp.toFixed(1)} · Hashtag #${p.rank}`;
let state, metadata, players = [], token, result, selected = 0, searchRows = [], target = null, busy = false, analysis = null, analysisError = null, matchupWeek = 0;
let session, sessions = [], mockPrediction;
let watch;
try { watch = new Set(JSON.parse(localStorage.getItem('draft-watchlist') || '[]')); } catch { watch = new Set(); }
let recTimer, pollFailures = 0, correctionSlot = null, clockInterval = null, currentEvalId = null, evalTimer = null;

function notice(message, error = false) { $('#notice').textContent = message; $('#notice').classList.toggle('error', error); }
async function api(path, body) {
  if (body) body = {...body, session_id:session?.id};
  const response = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json','X-Draft-Token':token}, body:JSON.stringify(body)} : {});
  const payload = await response.json();
  if (!response.ok) { const err = new Error(payload.error || `Request failed (${response.status})`); err.issues = payload.issues; throw err; }
  return payload;
}
async function refresh() {
  const payload = await api('/api/state');
  acceptPayload(payload);
  renderState(); renderSettings(); renderQuality(); renderPersonaControls(); renderPersona();
}
function acceptPayload(payload) {
  const changed = session && session.id !== payload.session.id;
  state = payload.state; session = payload.session; sessions = payload.sessions; mockPrediction = payload.mock_prediction;
  // Never retain a previous session's/board's analysis: a null payload means it is
  // unavailable and must be cleared, not silently kept.
  analysis = payload.analysis || null;
  analysisError = analysis ? null : (payload.analysis_error || null);
  if (payload.metadata) metadata = payload.metadata;
  if (payload.token) token = payload.token;
  players = (payload.players || players.filter(p=>p.projected)).concat(state.custom_players);
  if (changed) {
    result = null; target = null; selected = 0; $('#search').value = ''; resetClock(false);
    $('#recommendations').innerHTML = '<p class="empty">Calculating recommendations for this draft session…</p>';
    $('#build-summary').innerHTML = ''; $('#actual-forecast').innerHTML = '';
    $('#later-targets').innerHTML = '';
    $('#projected-build').innerHTML = ''; $('#matchups').innerHTML = '';
  }
}
async function event(kind, payload) {
  const response = await api('/api/event', {kind, payload, revision:state.revision});
  acceptPayload(response);
  renderState();
  $('#engine-status').textContent = 'Updating · previous rankings stale';
  $('#engine-status').classList.add('stale');
  return state;
}
function owned() {
  const ids = new Set(state.slots.filter(s => s.current_team === 'Oscar' && s.player_id).map(s => s.player_id));
  return players.filter(p => p.keeper === 'Oscar' || ids.has(p.id));
}
function available() { const taken = new Set(state.drafted); return players.filter(p => !p.keeper && !taken.has(p.id)); }
function marketScore(p) { return p.market_adp ?? p.adp ?? (p.projected ? p.rank : 10000); }
function activeSlot() { return state.slots[(target || state.current_slot || 1) - 1]; }
function playerById(id) { return players.find(p => p.id === id); }
function switchTab(name) {
  const show = name === 'settings' ? ['setup'] : name === 'research' ? ['personas', 'season'] : [name];
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', show.includes(el.id)));
  document.querySelectorAll('nav button').forEach(el => el.classList.toggle('active', el.dataset.tab === name));
  if (name === 'draft') $('#search').focus();
  if (show.includes('season')) initializeBench().then(loadBenchRuns).catch(e => notice(e.message, true));
  if (name === 'review') renderReview().catch(e => notice(e.message, true));
}
function renderState() {
  renderSession();
  const complete = !state.current_slot;
  document.body.classList.toggle('draft-complete', complete);
  const current = state.slots[(state.current_slot || 1) - 1];
  $('#current-pick').textContent = state.current_slot ? `#${current.slot} · ${current.current_team || 'Owner unresolved'}` : 'Draft complete';
  const next = state.slots.find(s => s.current_team === 'Oscar' && !s.keeper && !s.player_id);
  const gap = next ? state.slots.filter(s => s.slot < next.slot && !s.keeper && !s.player_id).length : 0;
  $('#next-pick').textContent = next ? `#${next.slot} · ${gap} pick${gap === 1 ? '' : 's'} away` : 'All picks recorded';
  const rosterComplete = owned().length >= 13;
  $('#draft-complete-summary').innerHTML = complete
    ? `<div class="panel-title"><h2>Draft complete · ${esc(session.name)}</h2></div><p>${owned().length}/13 recorded for you, and every opponent's roster is stored. Evaluate without touching Settings or JSON.</p><div class="rec-actions"><button id="to-evaluate">Evaluate this draft</button><button id="to-team" class="secondary">View team & matchups</button>${session.mode === 'mock' ? '<button id="to-newmock" class="secondary">Start another mock</button>' : ''}</div>`
    : '';
  $('#draft-complete-summary').hidden = !complete;
  const toEval = $('#to-evaluate'); if (toEval) toEval.onclick = () => switchTab('review');
  const toTeam = $('#to-team'); if (toTeam) toTeam.onclick = () => switchTab('team');
  const toNew = $('#to-newmock'); if (toNew) toNew.onclick = () => changeSession('new_mock');
  $('#save-status').textContent = `Saved locally · event ${state.revision}`;
  const bs = $('#bench-source');
  if (bs) bs.textContent = `Runs in a separate process against session “${session.name}” (${session.mode}). Projections captured ${metadata?.projection_source_date || 'unknown'}; board event ${state.revision}. Simulated, not calibrated odds.`;
  $('#undo').disabled = !state.undo_event;
  const roster = owned();
  $('#roster-count').textContent = `${roster.length}/13`;
  $('#roster').innerHTML = roster.map(p => `<div class="player-row"><strong>${esc(p.name)}</strong><div class="player-meta">${p.keeper ? 'KEEPER · ' : ''}${esc(p.team)} ${esc(p.positions.join('/'))}${!p.projected ? ' · No projection' : ''}</div></div>`).join('');
  const picks = state.slots.filter(s => s.player_id).sort((a,b) => b.slot-a.slot).slice(0,8);
  $('#recent').innerHTML = picks.map(s => `<div class="recent-row">#${s.slot} <strong>${esc(s.player_name)}</strong> · ${esc(s.current_team)}</div>`).join('') || '<p class="empty">No live picks recorded yet.</p>';
  renderSearch(); renderWatch(); renderBoard(); renderPersonal(); renderTeam(); disableStaleRecButtons();
  $('#history').innerHTML = [...state.events].reverse().map(e => `<div class="recent-row">${e.id} · ${esc(e.kind)} · ${esc(new Date(e.timestamp).toLocaleTimeString())}<br><span class="muted">${esc(JSON.stringify(e.payload))}</span></div>`).join('') || '<p class="empty">Append-only history will appear here.</p>';
}
function renderSearch() {
  const q = normalize($('#search').value);
  searchRows = available().map(p => {
    const name = normalize(p.name); let score = 999;
    if (!q) score = 0;
    else if (name === q) score = 0;
    else if (name.startsWith(q)) score = 1;
    else if (name.includes(q)) score = 2;
    else if (q.length >= 5) {
      let at = 0; for (const c of q) { at = name.indexOf(c,at); if (at < 0) break; at++; }
      if (at >= 0) score = 3;
    }
    return {p,score};
  }).filter(x => x.score < 999).sort((a,b) => a.score-b.score || marketScore(a.p)-marketScore(b.p) || a.p.rank-b.p.rank || a.p.id.localeCompare(b.p.id)).slice(0,12).map(x => x.p);
  selected = Math.max(0, Math.min(selected, searchRows.length-1));
  const slot = activeSlot();
  $('#entry-target').textContent = state.current_slot || target ? `${target ? 'CORRECTION' : 'Recording'} → #${slot.slot} · ${slot.current_team || 'Choose owner on the board first'}` : 'Draft complete';
  $('#search-results').innerHTML = searchRows.map((p,i) => `<button class="search-row ${i===selected?'selected':''}" role="option" aria-selected="${i===selected}" data-record="${esc(p.id)}"><span>${esc(p.name)}<span class="player-meta"> · ${esc(p.team)} ${esc(p.positions.join('/'))}</span></span><span class="player-meta" title="${p.adp!==null&&p.adp!==undefined?'Yahoo ADP from imported capture':'Estimated ADP scale from Hashtag source rank; not a Yahoo observation'}">${p.projected?`${p.adp_estimated?'Est.':'ADP'} ${marketScore(p).toFixed(1)}<br>HT #${p.rank}`:'unlisted'}</span></button>`).join('') || '<p class="empty">No available matches. Kept and drafted players are excluded.</p>';
  if(result?.session_id===session.id && result.revision===state.revision && result.survival) {
    $('#search-results').querySelectorAll('[data-record]').forEach(el=>{
      const estimates=result.survival.scenarios.map(s=>({name:s.name,...(s.estimates[el.dataset.record] || {})}));
      if(estimates.some(s=>s.next)) {
        const hint=document.createElement('div');hint.className='player-meta';
        hint.textContent=estimates.map(s=>{
          const h=s.later || s.next;
          return `${estimates.length>1?s.name+' · ':''}Survive to #${h.slot}: ${h.probability===null?'uncertain':pct(h.probability)}${h.conditional?' if passed':''}`;
        }).join(' / ');
        el.querySelector('span').append(hint);
      }
    });
  }
  document.querySelectorAll('[data-record]').forEach(el => el.addEventListener('click', () => record(el.dataset.record)));
}
async function record(id, custom = null, slotNumber = null) {
  if (busy) return;
  // A recommendation record must always write to the explicitly requested slot
  // (the current owned pick), never to a correction `target` left open elsewhere.
  const slot = slotNumber ? state.slots[slotNumber - 1] : activeSlot();
  if (!state.current_slot && !target) return;
  if (slot.keeper) { notice('Keeper slot: change the slot settings before entering a live pick.',true); return; }
  if (!slot.current_team) { openSlot(slot.slot); notice('Select the actual pick owner first.'); return; }
  const player = custom || playerById(id);
  if (target && slot.player_id && !confirm(`Replace ${slot.player_name} at #${slot.slot} with ${player.name}?`)) return;
  busy = true;
  try {
    await event('pick', {slot:slot.slot, player_id:id, ...(custom ? {custom_player:custom} : {})});
    notice(`Saved #${slot.slot}: ${player.name} → ${slot.current_team}. ${session.mode==='mock'?'Practice only; live draft untouched.':'Advisory only—submit your own pick in Yahoo.'}`);
    target = null; selected = 0; $('#search').value = ''; renderSearch(); resetClock(false);
  } catch (e) { notice(e.message,true); await refresh().catch(()=>{}); }
  finally { busy = false; $('#search').focus(); }
}
function renderWatch() {
  const taken = new Set(state.drafted);
  $('#watchlist').innerHTML = [...watch].map(id => {
    const p = playerById(id); if (!p) return '';
    return `<div class="player-row"><button class="secondary" data-unwatch="${esc(id)}" aria-label="Remove ${esc(p.name)} from watchlist">×</button><strong>${esc(p.name)}</strong><div class="player-meta">${taken.has(id)?'TAKEN':p.keeper?'KEPT':esc(p.team)}</div></div>`;
  }).join('') || '<p class="empty">Star candidates to keep a shortlist. Stored in this browser.</p>';
  document.querySelectorAll('[data-unwatch]').forEach(el => el.onclick = () => toggleWatch(el.dataset.unwatch));
}
function toggleWatch(id) { if (watch.has(id)) watch.delete(id); else watch.add(id); try { localStorage.setItem('draft-watchlist',JSON.stringify([...watch])); } catch { notice('Browser watchlist storage unavailable; draft picks still save to SQLite.'); } renderWatch(); if(result) renderRecommendations(); }
function renderRecommendations() {
  const stale = result.revision !== state.revision || result.session_id !== session.id;
  $('#engine-status').textContent = stale ? 'Updating · stale rankings' : `${result.candidates_tested || 0} candidates · ${result.elapsed_seconds}s`;
  $('#engine-status').classList.toggle('stale',stale);
  const build = result.builds?.[0];
  const strat = result.strategy || {};
  const needs = strat.needs || [], strengths = strat.strengths || [];
  $('#build-summary').innerHTML = `<p class="plan-line"><strong>Your needs:</strong> ${needs.length ? needs.map(esc).join(', ') : '—'} <span class="muted">· roster strengths: ${strengths.length ? strengths.map(esc).join(', ') : '—'}</span></p>`
    + (build ? `<span class="badge muted">Tested build: ${build.punt.length ? esc(build.punt.join(' + ')) + ' punt' : 'balanced'}</span><span class="badge muted">${result.strategies_screened} builds screened</span>` : '')
    + '<p class="hint">Positions are provisional Yahoo eligibility — verify in the draft room.</p>';
  if(result.valuation_incomplete)$('#build-summary').innerHTML+=`<p class="hint validation-warning">Provisional playoff valuation: paths stop before #${result.valuation_barrier.slot} (${esc(result.valuation_barrier.reason)}). Remaining rosters are partial. Survival to earlier confirmed picks still uses Monte Carlo.</p>`;
  if(result.valuation_scenario)$('#build-summary').innerHTML+=`<span class="badge warn">Hypothetical valuation scenario: ${esc(result.valuation_scenario)}</span>`;
  const cs = state.current_slot ? state.slots[state.current_slot-1] : null;
  const myTurn = !!cs && cs.current_team === 'Oscar' && !cs.keeper;
  const recs = result.recommendations || [];
  const contingency = recs.filter(recIsContingency);
  const realistic = recs.filter(r => !recIsContingency(r));
  const featured = (realistic.length ? realistic : recs).slice(0, 3);
  $('#recommendations').innerHTML = featured.map((r,i) => `<article class="recommendation"><div class="rec-title"><span class="rec-name">${i+1}. ${esc(r.player.name)}</span><div class="rec-actions"><button class="secondary" data-watch="${esc(r.player.id)}" aria-label="Watch ${esc(r.player.name)}">${watch.has(r.player.id)?'★':'☆'}</button><button class="secondary" data-inspect="${esc(r.player.id)}">Inspect</button>${myTurn?`<button data-rec-record="${esc(r.player.id)}">Record → #${cs.slot} Oscar</button>`:`<button disabled title="Recording is only for your own pick; use the entry panel for opponents">Not your turn · #${cs?cs.slot:'-'} ${esc(cs?cs.current_team||'—':'')}</button>`}</div></div><div class="player-meta">${esc(r.player.team)} · ${esc(r.player.positions.join('/'))} · GP ${r.player.gp}</div><p class="hint">${esc((r.reasons||[])[0]||'')}</p><div class="rec-metrics"><span>Path index <b class="score">${index(r.score)}</b></span><span>No-stream ${index(r.baseline_score)}</span><span>Equal 9-cat ${r.equal_value.toFixed(2)}</span></div><span class="badge">Playoffs ${r.scheduled_games.join('/')}</span>${(()=>{const h=catHelp(r.category_z),c=catCost(r.category_z),fit=r.fit||{},after=fit.after_needs||[];const helpsAddr=needs.filter(n=>h.includes(n));const addressed=helpsAddr.filter(n=>!after.includes(n));const still=needs.filter(n=>after.includes(n));return `<span class="badge">${addressed.length?'Addresses: '+addressed.join(', '):'Helps address: '+(helpsAddr.join(', ')||'no current need')}</span>${c.length?`<span class="badge warn">Costs: ${c.join(', ')}</span>`:''}<span class="badge muted">Tested build: ${r.punt.length?'punts '+esc(r.punt.join(' + ')):'balanced'}</span><p class="hint">Position: ${esc(fit.role||'—')} (${esc((fit.positions||[]).join('/'))}) · starts at <strong>${esc(fit.start_slot||'?')}</strong>${fit.util_dependent?' · ⚠ UTIL-dependent':''} · Δ usable starts ${fit.delta_starts>=0?'+':''}${fit.delta_starts} / Δ blocked ${fit.delta_blocked>=0?'+':''}${fit.delta_blocked}.</p>${after.length?`<p class="hint">After adding: needs ${after.join(', ')}${still.length?' (still open: '+still.join(', ')+')':' (current needs resolved)'} · strengths ${(fit.after_strengths||[]).join(', ')}.</p>`:''}`;})()}${r.availability_later !== null ? `<span class="badge ${r.availability_later<.35?'warn':''}">${r.availability_later<.35?'Draft now':'Possible later target'} · ${pct(r.availability_later)} survival heuristic</span>`:''}${r.streaming_sensitive?'<span class="badge warn">Streaming-sensitive</span>':''}<details><summary>Why this player / projected draft path</summary><ul>${r.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}<li>Estimated survival to your next pick: ${pct(r.availability_at_next)}. Not a calibrated probability.</li><li>Path improvement versus best same-strategy completion: ${(r.marginal*100).toFixed(2)} index points. Draft-path comparisons are approximate.</li><li>Next-year draft-round cost if eligible: R${r.keeper_next_round}; keeper-clock eligibility not verified.</li></ul><p class="hint">Illustrative completed roster: ${r.completed_roster.map(id=>esc(playerById(id)?.name || id)).join(', ')}</p><div class="table-scroll">${zTable(r.category_z)}</div></details></article>`).join('') || '<p class="empty">No remaining owned draft picks. Use the board to review or correct selections.</p>';
  $('#contingency').hidden = !contingency.length;
  $('#contingency-list').innerHTML = contingency.slice(0, 4).map(r => `<article class="later-card"><strong>${esc(r.player.name)}</strong><div class="player-meta">${esc(adpText(r.player))}</div><p class="hint">${esc((r.reasons||[])[0]||'')}${r.availability_later!==null&&r.availability_later!==undefined?` · survival to your pick ${pct(r.availability_later)} (unlikely)`:' · survival uncertain'}</p></article>`).join('');
  document.querySelectorAll('.recommendation').forEach((el,i)=>{
    const rec=featured[i]; if(!rec)return;
    const spread=document.createElement('p');
    const adp=document.createElement('div');adp.className='player-meta adp-line';adp.textContent=adpText(rec.player);
    el.querySelector('.player-meta').after(adp);
    spread.className='hint';
    spread.textContent=`Two market scenarios: ${index(rec.score_range[0])}–${index(rec.score_range[1])} index range (not a confidence interval).`;
    el.querySelector('details').append(spread);
    if(rec.wait_comparison) {
      const w=rec.wait_comparison, comparison=document.createElement('p');comparison.className='hint';
      comparison.textContent=`Wait comparison: take ${playerById(w.alternative_now)?.name || w.alternative_now} now, target ${rec.player.name} at #${w.target_slot}. Wait index ${index(w.score)} vs now ${index(rec.score)}; obtained this player in ${w.survived_scenarios}/${w.scenarios} modeled drafts (not a probability).`;
      el.querySelector('details').append(comparison);
    }
    if(rec.passed_market_players?.length) {
      const denial=document.createElement('p');denial.className='hint';
      denial.textContent='Changed opponent allocation in this hypothetical path: '+rec.passed_market_players.map(p=>`${p.name} → ${p.team==='Oscar'?'you later':p.team} at #${p.slot}`).join('; ')+'. These are modeled future picks, not confirmed selections.';
      el.querySelector('details').append(denial);
    }
    if(rec.market_tiebreak) {
      const badge=document.createElement('span');badge.className='badge';badge.textContent='Near-tie · simulated scarcity considered';
      el.querySelector('.rec-metrics').after(badge);
    }
    const streamed=document.createElement('span');
    streamed.textContent=`With-stream ${index(rec.streamed_score)}`;
    el.querySelector('.rec-metrics').append(streamed);
    if(rec.availability_at_next!==null && rec.availability_at_next<.8) {
      const badge=document.createElement('span');badge.className='badge warn';
      badge.textContent=`May go before #${result.next_pick} · ${pct(rec.availability_at_next)} simulated survival`;
      el.querySelector('.rec-metrics').after(badge);
    }
    // Replace old heuristic badges/text; probabilities now come from trials.
    el.querySelectorAll('.badge').forEach(b=>{if(b.textContent.includes('survival heuristic'))b.remove();});
    const survival=document.createElement('div');survival.className='survival-line';
    survival.innerHTML=survivalHTML(rec.survival_scenarios || []);
    el.querySelector('.adp-line').after(survival);
    el.querySelectorAll('details li').forEach(li=>{
      if(li.textContent.startsWith('Estimated survival to your next pick:'))li.textContent='Survival frequencies and sampling intervals are shown above. Model calibration and ADP snapshot limitations remain.';
    });
  });
  const targets=result.later_targets || [];
  $('#later-panel').hidden=!targets.length;
  $('#later-targets').innerHTML=targets.map(r=>{
    const w=r.wait_comparison;
    return `<article class="later-card"><div class="rec-title"><strong>${esc(r.player.name)}</strong><div class="rec-actions"><button class="secondary" data-watch="${esc(r.player.id)}">${watch.has(r.player.id)?'★':'☆'}</button>${myTurn?`<button class="secondary" data-rec-record="${esc(r.player.id)}">Record → #${cs.slot} Oscar</button>`:`<button disabled title="Recording is only for your own pick">Not your turn</button>`}</div></div><div class="player-meta adp-line">${esc(adpText(r.player))}</div><div class="survival-line">${survivalHTML(r.survival_scenarios || [])}</div><p class="hint">Take ${esc(playerById(w.alternative_now)?.name || w.alternative_now)} now; target this player at #${w.target_slot}. Value comparison uses ${w.scenarios} paired league paths; survival frequencies above use separate Monte Carlo trials.</p><span class="badge">Target later · ${r.punt.length?'Punt '+esc(r.punt.join(' + ')):'Balanced'}</span><p class="hint">Now index ${index(r.score)} / wait-plan index ${index(w.score)}. No player is reserved against opponents in the wait plan.</p></article>`;
  }).join('');
  document.querySelectorAll('[data-watch]').forEach(el=>el.onclick=()=>toggleWatch(el.dataset.watch));
  document.querySelectorAll('[data-rec-record]').forEach(el=>el.onclick=()=>{
    const current=state.current_slot;
    const slot=current?state.slots[current-1]:null;
    if(!recFresh()){ notice('Recommendations are stale; wait for recalculation before recording.',true); renderState(); return; }
    if(!slot || slot.current_team!=='Oscar' || slot.keeper){ notice('Not your pick — recording is disabled. Use the entry panel only for the current owner.',true); return; }
    // Bind to the current owned slot independently of any open correction target.
    record(el.dataset.recRecord, null, current);
  });
  document.querySelectorAll('[data-inspect]').forEach(el=>el.onclick=()=>{target=null;switchTab('draft');$('#search').value=playerById(el.dataset.inspect)?.name||'';selected=0;renderSearch();$('#search').focus();});
  $('#actual-forecast').innerHTML = forecastTable(result.actual_weeks);
  $('#projected-build').innerHTML = build ? `<p>${build.punt.length?'Punt '+esc(build.punt.join(' + ')):'Balanced'} · hypothetical completed roster, not your actual current team.</p>${forecastTable(build.weeks)}<p class="hint">Streaming net starts after 50% discount: ${build.stream_plans.map(p=>p.net_starts.toFixed(1)).join(' / ')}. Proposed adds: ${build.stream_plans.map(p=>p.adds).join(' / ')}.</p>` : '<p class="hint">No hypothetical completion shown. Team & matchups uses your recorded rosters only.</p>';
  renderQuality(); renderSearch(); renderPersonal(); renderSurvivalSummary(); renderTeam();
}
function survivalHTML(scenarios) {
  return scenarios.map(s=>{
    const show=(h,label)=>{
      if(!h)return '';
      if(h.probability===null)return `${label} #${h.slot}: ${h.censored?'uncertain assets · no estimate':'insufficient surviving trials'}`;
      const interval=h.mc_95_interval?` · MC interval ${pct(h.mc_95_interval[0])}–${pct(h.mc_95_interval[1])}`:'';
      return `${label} #${h.slot}: <strong>${pct(h.probability)}</strong> · n=${h.n}${interval}`;
    };
    return `<div>${esc(s.name)}: ${show(s.next,'Upcoming turn')}<br>${show(s.later,'Following turn if passed')}</div>`;
  }).join('');
}
function renderSurvivalSummary() {
  const survival=result?.survival;
  $('#survival-summary').innerHTML=survival?`<h3>Latest Monte Carlo run · ${esc(survival.model)}</h3>${survival.scenarios.map(s=>`<p class="hint"><strong>${esc(s.name)}</strong> · ${s.trials} survival trials · ${s.full_paths_n} full remaining-draft samples${s.barrier?'<br><span class="validation-warning">Censored from #'+s.barrier.slot+': '+esc(s.barrier.reason)+'</span>':''}</p>`).join('')}<ul class="hint">${survival.notes.map(n=>'<li>'+esc(n)+'</li>').join('')}</ul>`:'<p class="hint">Monte Carlo survival updates with the active draft.</p>';
}
function renderPersonaControls() {
  const previous=$('#persona-manager').value;
  $('#persona-manager').innerHTML=metadata.teams.filter(t=>t!=='Oscar').map(t=>`<option ${t===previous?'selected':''}>${esc(t)}</option>`).join('');
  $('#draft-model').value=state.settings.draft_model || 'auto';
  $('#mc-trials').value=String(state.settings.mc_trials || 300);
  $('#draft-scenarios').value=JSON.stringify(state.settings.draft_scenarios || [],null,2);
}
function renderPersona() {
  const historical=metadata.historical_profiles;
  if(!historical){$('#persona-validation').textContent='Historical profiles not imported. Run python3 scripts/import_history3.py (or import_history.py) before restarting.';return;}
  const validation=historical.validation, selected=$('#persona-manager').value, profile=historical.profiles[selected];
  const number=x=>x===null||x===undefined?'unknown':Number(x).toFixed(2);
  const signed=x=>x===null||x===undefined?'—':(x>=0?'+':'')+Number(x).toFixed(2);
  const metrics=validation.metrics||{};
  const metricRow=(label,key)=>`<tr><td>${esc(label)}</td><td>${number(metrics.baseline&&metrics.baseline[key])}</td><td>${number(metrics.persona_manager&&metrics.persona_manager[key])}</td></tr>`;
  const crossRows=Object.entries(validation.cross_season||{}).map(([pair,r])=>`<tr><td>${esc(pair)}<br><span class="muted">test pool: ${esc(r.test_pool)}</span></td><td>${number(r.baseline_log_loss)}</td><td>${number(r.persona_pooled_log_loss)}</td><td>${number(r.persona_manager_log_loss)}</td></tr>`).join('');
  const interval=validation.round_bootstrap_95_interval||[null,null];
  const coverage=historical.report && historical.report.coverage ? historical.report.coverage : {};
  const coverageRows=Object.values(coverage).map(c=>`<tr><td>${esc(c.season)}</td><td>${esc(c.adp_tier)}</td><td>${c.discretionary_with_adp}</td><td>${c.market_pool}</td><td>${c.choice_sets||0}</td><td>${c.years?c.years.age:''}</td></tr>`).join('');
  $('#persona-validation').innerHTML=`<p><strong>Validation-approved default: ${esc(validation.decision)}</strong></p><p class="hint validation-warning">${validation.persona_enabled_by_default?'Persona passed the declared validation gate.':'Persona effects did not improve held-out prediction, so Auto keeps the ADP baseline. Experimental mode and subjective adjustments stay opt-in.'}</p>
  <h3>Season data tiers</h3><div class="table-scroll"><table><thead><tr><th>Season</th><th>ADP tier</th><th>Discretionary w/ ADP</th><th>Market pool</th><th>Choice sets used</th><th>Age known</th></tr></thead><tbody>${coverageRows}</tbody></table></div>
  <p class="hint">Only <strong>2025-26</strong> has a complete market. <strong>2024-25</strong> has ADP for taken players only, so its pool is truncated (late-round reach understated by ~26 slots) and its ADP slope is fitted separately, never pooled. <strong>2023-24</strong> has no usable ADP (the supplied export duplicates 2024), so it informs descriptive preferences only.</p>
  <h3>Held-out choice prediction · ${validation.n_pooled_sets||0} pooled ADP choice sets</h3><div class="table-scroll"><table><thead><tr><th>Metric (${validation.n_test||0} held-out picks)</th><th>ADP baseline</th><th>Persona</th></tr></thead><tbody>${metricRow('Choice log loss','log_loss')}${metricRow('Mean selected rank','mean_choice_rank')}${metricRow('Top-5 accuracy','top5_accuracy')}</tbody></table></div>
  <p class="hint">Persona − baseline log loss: <strong>${signed(validation.persona_minus_baseline_log_loss)}</strong> (round-block 95% interval ${signed(interval[0])} to ${signed(interval[1])}). Personas must be better on the holdout, exclude zero, <em>and</em> transfer to a different season.</p>
  ${crossRows?`<h3>Cross-season transfer · the real robustness test</h3><div class="table-scroll"><table><thead><tr><th>Trained → tested</th><th>ADP baseline</th><th>Persona (pooled)</th><th>Persona (per-manager)</th></tr></thead><tbody>${crossRows}</tbody></table></div><p class="hint">${validation.cross_season_persona_wins}/${validation.cross_season_pairs} cross-season pairs favour the persona. With more data the personas still did not transfer, which is why the baseline is kept.</p>`:''}
  <ul class="hint">${(validation.limitations||[]).map(x=>'<li>'+esc(x)+'</li>').join('')}</ul>`;
  if(!profile)return;
  const observed=profile.observations, learned=profile.learned, overrides=state.settings.manager_overrides?.[selected] || {};
  const stat=(label,value)=>`<div class="profile-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
  const disc=observed.discretionary||{}, keepers=observed.keeper_counts||{};
  const cons=observed.consistency||{};
  const consRows=Object.entries(cons).map(([trait,c])=>`<tr><td>${esc(trait)}</td><td>${(c.values||[]).map(v=>signed(v)).join(', ')||'—'}</td><td>${signed(c.mean_deviation)}</td><td>${c.same_sign?'<strong>replicated</strong>':'not replicated'}</td></tr>`).join('');
  $('#persona-observed').innerHTML=`<p class="hint">Discretionary picks per season: ${Object.entries(disc).map(([s,n])=>esc(s)+' '+n).join(' · ')}. Keepers: ${Object.entries(keepers).map(([s,n])=>esc(s)+' '+n).join(' · ')}.</p>
  <h3>Preference deviation vs the same-season, same-phase league baseline</h3><div class="table-scroll"><table><thead><tr><th>Trait</th><th>Deviation by season</th><th>Mean</th><th>Across seasons</th></tr></thead><tbody>${consRows}</tbody></table></div>
  <p class="hint">Slot-controlled: each trait is compared with the league mix in the same round phase, so draft-slot availability is roughly held constant. "Replicated" means the deviation keeps the same sign in every season. Negative age deviation = older players; positive = younger.</p>`;
  const labels=['ADP adherence','Young-player association','Rookie association','Guard association','Forward association','Center association'];
  $('#persona-inferred').innerHTML=labels.map((label,i)=>stat(label,number(learned.coefficients[i])+' ± '+number(1.96*learned.sd[i]))).join('')+`<p class="hint">Experimental persona parameters, shrunk toward the pooled prior; not active while the baseline is selected. ${esc(profile.confidence)}. Ranges are regularized curvature approximations, not calibrated confidence intervals. Where the descriptive deviation replicates but the fitted coefficient sits near zero, ADP is already pricing that trait in.</p><p class="hint">Phase samples: ${Object.entries(learned.phases).map(([ph,v])=>esc(ph)+': '+v.n+(v.prior_only?' (prior only)':' (strong shrinkage)')).join(' · ')}</p><ul class="hint">${profile.unsupported.map(x=>'<li>'+esc(x)+'</li>').join('')}</ul>`;
  const keys=['adherence','young','rookie','guard','forward','center'];
  $('#persona-fields').innerHTML=keys.map((k,i)=>`<label>${esc(labels[i])}<input name="${k}" type="number" min="${i ? -.7 : .35}" max="${i ? .7 : 4}" step=".05" placeholder="Persona ${number(learned.coefficients[i])}" value="${overrides[k]??''}"></label>`).join('');
  $('#persona-target').innerHTML='<option value="">No new targeting override</option>'+players.filter(p=>p.projected).sort((a,b)=>a.name.localeCompare(b.name)).map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  $('#persona-targets').textContent='Current subjective targets: '+(Object.entries(overrides.targets || {}).map(([id,v])=>(playerById(id)?.name || id)+' '+v).join(', ') || 'none');
}
function renderPersonal() {
  const current = result && result.session_id===session.id && result.revision===state.revision;
  const summary = result?.session_id===session.id ? result.strategy : null;
  const locked=state.settings.punt || [];
  if (!summary) {
    $('#strategy-summary').innerHTML=`<p class="hint">${locked.length?'Locked punt: '+esc(locked.join(' + ')):'Auto strategy · comparing balanced and punt builds.'} Updating roster analysis…</p>`;
  } else {
    const punts=locked.length?locked:summary.suggested_punt;
    $('#strategy-summary').innerHTML=`${!current?'<span class="badge warn">Updating · previous analysis</span>':''}<p class="strategy-line"><strong>${locked.length?'Locked strategy':punts.length?'Tentative direction':'Leading direction'}:</strong> ${punts.length?'Punt '+esc(punts.join(' + ')):'Balanced'}</p><p class="strategy-line"><strong>Current strengths:</strong> ${esc(summary.strengths.join(', '))}</p><p class="strategy-line"><strong>Needs to monitor:</strong> ${esc(summary.needs.filter(c=>!punts.includes(c)).join(', ') || 'Remaining competitive categories')}</p><p class="hint">${locked.length?'Punt explicitly locked in Assumptions.':'Auto suggestion, not a commitment.'} Strengths are per-game impacts, not guaranteed wins.</p>`;
  }
  const taken=new Set(state.drafted);
  const priorities=result?.session_id===session.id?result.recommendations.filter(r=>!taken.has(r.player.id)).slice(0,8):[];
  $('#pick-priorities').innerHTML=(priorities.length?`${!current?'<p class="hint stale">Updating priorities…</p>':''}`+priorities.map((r,i)=>`<button class="priority-row" data-priority="${esc(r.player.id)}">${i+1}. ${esc(r.player.name)}<div class="player-meta">${r.punt.length?'Punt '+esc(r.punt.join(' + ')):'Balanced'} · index ${index(r.score)}</div></button>`).join(''):'<p class="empty">'+(state.slots.some(s=>s.current_team==='Oscar'&&!s.keeper&&!s.player_id)?'Calculating your priorities…':'All of your picks are recorded.')+'</p>');
  document.querySelectorAll('[data-priority]').forEach(el=>el.onclick=()=>{target=null;switchTab('draft');$('#search').value=playerById(el.dataset.priority).name;selected=0;renderSearch();$('#search').focus();});
}
function renderSession() {
  const mock=session.mode==='mock';
  $('#mode-badge').textContent=mock?'MOCK DRAFT · PRACTICE':'LIVE DRAFT';$('#mode-badge').classList.toggle('mock',mock);
  $('#session-select').innerHTML=sessions.map(s=>`<option value="${esc(s.id)}" ${s.id===session.id?'selected':''}>${esc(s.name)}</option>`).join('');
  $('#reset-mock').hidden=!mock;$('#mock-controls').hidden=!mock;$('#mock-actions').hidden=!mock;
  $('#session-hint').textContent=mock?'Practice picks are isolated. Reset keeps this run saved.':'Live picks are saved separately from practice.';
  $('#mock-model').value=session.model || 'fit';$('#mock-randomness').value=String(session.randomness ?? .35);
  const blocked=!mockPrediction?.choices?.length;
  $('#mock-one').disabled=blocked;$('#mock-until').disabled=blocked;
  $('#mock-complete').disabled=!state.current_slot;
  $('#mock-prediction').innerHTML=mockPrediction?`${mockPrediction.blocked?`<p class="hint">${esc(mockPrediction.blocked)}</p>`:`<p class="hint">Guesses for ${esc(mockPrediction.team)} at #${mockPrediction.slot}. Practice weights—not actual pick probabilities.</p>`}${mockPrediction.choices.slice(0,5).map(c=>`<div class="mock-choice"><strong>${esc(c.name)}</strong> · ${pct(c.weight)} simulation weight<p class="hint">${c.reasons.map(esc).join(' · ')}</p></div>`).join('')}`:'';
}
function zTable(values) { return `<table><thead><tr>${metadata.categories.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody><tr>${values.map(v=>`<td>${v.toFixed(2)}</td>`).join('')}</tr></tbody></table>`; }
function forecastTable(weeks) {
  return `<div class="table-scroll"><table><thead><tr><th>Week</th><th>Starts</th><th>Blocked*</th>${metadata.categories.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${weeks.map((w,i)=>`<tr><td>${['Mar 1–7','Mar 8–14','Mar 15–21'][i]}</td><td>${w.usable_starts.toFixed(1)}</td><td>${w.blocked_games}</td>${w.categories.map((v,j)=>`<td>${j<2?v.toFixed(3):v.toFixed(1)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="hint">*Scheduled bench games blocked by position/start-slot matching, before availability discount. No weekly game cap assumed.</p>`;
}
function renderTeam() {
  const ownEl = $('#actual-forecast'), matchEl = $('#matchups');
  if (!analysis) {
    const msg = analysisError
      ? `Roster/matchup analysis unavailable: ${esc(analysisError)}. Figures are hidden until it recovers; pick recording still works.`
      : 'Roster/matchup analysis unavailable for this board. Figures are hidden until it recovers; pick recording still works.';
    if (ownEl) ownEl.innerHTML = `<p class="validation-warning">${msg}</p>`;
    if (matchEl) matchEl.innerHTML = '';
    return;
  }
  const cats = analysis.categories, comp = analysis.own.completeness;
  ownEl.innerHTML = `<p class="hint">Recorded roster · <strong>${comp.players}/13</strong> players${comp.unprojected ? ` · ${comp.unprojected} without projections` : ''}${comp.complete ? '' : ' · <strong>incomplete</strong>'}. ${analysis.own.punts.length ? 'Locked punt: ' + esc(analysis.own.punts.join(' + ')) : 'No punt locked (not assumed balanced).'}</p>`
    + forecastTable(analysis.own.weeks)
    + '<p class="hint">Recorded players only — no hypothetical completion. Ratio categories use projected makes/attempts; availability uses season GP.</p>';
  const rows = analysis.matchups.map(m => {
    const w = m.weeks[matchupWeek];
    const cells = w.category_edges.map(p => `<td class="${categoryClass(p)}">${categoryLabel(p)}</td>`).join('');
    return `<tr><td>${esc(m.team)}</td><td>${pct(w.win_proxy)}</td>${cells}</tr>`;
  }).join('');
  const detail = analysis.matchups.map(m => {
    const w = m.weeks[matchupWeek], oc = analysis.teams[m.team].completeness;
    const row = (label, c) => `<tr><td>${esc(label)}</td>${c.map((v, j) => `<td>${j < 2 ? v.toFixed(3) : v.toFixed(1)}</td>`).join('')}</tr>`;
    return `<details><summary>${esc(m.team)} · ${pct(w.win_proxy)} win proxy · ${oc.players}/13${oc.complete ? '' : ' (incomplete)'}</summary><div class="table-scroll"><table><thead><tr><th>Team</th>${cats.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${row('You', w.my_categories)}${row(m.team, w.opp_categories)}</tbody></table></div>${oc.unprojected ? `<p class="hint">${oc.unprojected} unlisted player(s) have no projected contribution.</p>` : ''}</details>`;
  }).join('');
  matchEl.innerHTML = `<h3>Opponent matchup matrix · recorded rosters</h3>`
    + `<label>Playoff week <select id="matchup-week">${analysis.week_labels.map((l, i) => `<option value="${i}" ${i === matchupWeek ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></label>`
    + `<div class="table-scroll"><table><thead><tr><th>Opponent</th><th>Win proxy</th>${cats.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`
    + `<p class="hint">${esc(analysis.note)} Category labels are per-category win probabilities: >65% Advantage, <35% Disadvantage, otherwise Close.</p>`
    + `<h3>Opponent detail · ${esc(analysis.week_labels[matchupWeek])}</h3>${detail}`;
  $('#matchup-week').onchange = e => { matchupWeek = Number(e.target.value); renderTeam(); };
}
async function renderReview() {
  const complete = !state.current_slot;
  $('#review-title').textContent = `Evaluating ${session.name} · all recorded rosters`;
  $('#review-status').textContent = complete ? '' : 'draft in progress';
  const teams = analysis ? Object.keys(analysis.teams) : [];
  const incomplete = teams.filter(t => analysis.teams[t].completeness.players !== 13);
  $('#review-issues').innerHTML = !complete
    ? `<p class="validation-warning">This session is not a completed draft (${state.slots.filter(s => !s.keeper && !s.player_id).length} picks left). Finish it, or open a completed mock.</p><button id="review-to-board" class="secondary">Go to Board</button>`
    : !analysis
      ? `<p class="validation-warning">${analysisError ? 'Roster analysis unavailable: ' + esc(analysisError) : 'Roster analysis unavailable for this board.'} Matchups and completeness cannot be shown.</p>`
      : (incomplete.length
        ? `<p class="validation-warning">Rosters not complete: ${incomplete.map(t => t + ' ' + analysis.teams[t].completeness.players + '/13').join(', ')}.</p><button id="review-to-board" class="secondary">Go to Board</button>`
        : '<p class="hint">Board integrity: 12 teams at 13/13, projections present. Snapshot is taken at submit time.</p>');
  const rb = $('#review-to-board'); if (rb) rb.onclick = () => switchTab('board');
  renderReviewAssessment();
  await loadEvaluations();
}

function renderReviewAssessment() {
  if (!analysis) { $('#review-assessment').innerHTML = `<p class="validation-warning">${analysisError ? 'Roster analysis unavailable: ' + esc(analysisError) : 'Roster analysis unavailable for this board.'}</p>`; return; }
  const cats = analysis.categories;
  const edges = cats.map((c, j) => analysis.matchups.reduce((s, m) => s + m.weeks[0].category_edges[j], 0) / Math.max(1, analysis.matchups.length));
  const close = cats.filter((c, j) => edges[j] >= .35 && edges[j] <= .65);
  const starts = analysis.own.weeks.reduce((s, x) => s + x.usable_starts, 0);
  const blocked = analysis.own.weeks.reduce((s, x) => s + x.blocked_games, 0);
  const sc = result && result.session_id === session.id ? result.strategy : null;
  const needs = sc ? sc.needs : [], strengths = sc ? sc.strengths : [];
  const lowGP = owned().filter(p => p.projected && p.gp < 65);
  const rows = analysis.matchups.map(m => {
    const wk = m.weeks[0];
    const td = wk.category_edges.map(e => `<td class="${categoryClass(e)}">${categoryLabel(e)}</td>`).join('');
    return `<tr><td>${esc(m.team)}</td><td>${pct(wk.win_proxy)}</td>${td}</tr>`;
  }).join('');
  $('#review-assessment').innerHTML =
    `<h3>What are my strengths and weaknesses?</h3><p class="hint">Strengths: <strong>${strengths.join(', ') || '—'}</strong> · Weaknesses: <strong>${needs.join(', ') || '—'}</strong> (your recorded roster).</p>`
    + `<h3>Which categories are close enough to improve?</h3><p class="hint">${close.length ? close.join(', ') : 'None — categories are clearly won or lost.'} <span class="muted">(projected per-category win probability 35–65% vs the average opponent, week 18).</span></p>`
    + `<h3>How do I compare with each opponent?</h3><div class="table-scroll"><table><thead><tr><th>Opponent</th><th>Win proxy</th>${cats.map(c => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div><p class="hint">Recorded-roster projection (Advantage &gt;65%, Disadvantage &lt;35%) — separate from the simulated outcomes below.</p>`
    + `<h3>Do congestion or schedules cost usable starts?</h3><p class="hint">Projected usable starts weeks 18–20: <strong>${starts.toFixed(1)}</strong> · blocked bench games: <strong>${blocked}</strong> (position/lineup congestion, not injuries).</p>`
    + `<h3>What should I watch during the season?</h3><p class="hint">${needs.length ? 'Improve ' + needs.join(', ') + ' via waivers/streaming. ' : ''}${lowGP.length ? 'Availability risk (projected GP&lt;65): ' + lowGP.map(p => esc(p.name) + ' ' + p.gp).join(', ') + '.' : 'No low-GP players on your roster.'}</p>`;
}

async function loadEvaluations() {
  const resp = await api('/api/evaluations');
  renderEvalHistory(resp.evaluations || []);
  const mine = (resp.evaluations || []).filter(e => e.session && e.session.id === session.id);
  if (!mine.length) { currentEvalId = null; $('#eval-progress').innerHTML = ''; $('#eval-results').innerHTML = ''; $('#eval-run').disabled = !state.current_slot ? false : false; return; }
  const latest = mine[0];
  currentEvalId = latest.id;
  const job = await api('/api/evaluations/' + latest.id);
  if (job.state === 'running') { renderEvalProgress(job); startEvalPolling(latest.id); }
  else if (job.result) renderEvalResults(job.result);
  else if (job.state === 'failed') $('#eval-progress').innerHTML = `<p class="validation-warning">Evaluation failed: ${esc(job.error || 'unknown')}</p>`;
}

async function runEvaluation() {
  $('#eval-run').disabled = true;
  const seasons = Math.max(5, Math.min(200, Number($('#eval-seasons').value) || 40));
  try {
    const job = await api('/api/evaluate', { revision: state.revision, seasons, streaming: 'aggressive' });
    currentEvalId = job.id; renderEvalProgress(job); startEvalPolling(job.id);
  } catch (e) {
    $('#eval-run').disabled = false;
    notice(e.message || 'Evaluation failed', true);
    if (e.issues) $('#review-issues').innerHTML = `<p class="validation-warning">${e.issues.map(i => esc(i.message) + ' (fix: ' + esc(i.repair) + ')').join('<br>')}</p>`;
  }
}

function startEvalPolling(id) {
  clearInterval(evalTimer);
  evalTimer = setInterval(async () => {
    try {
      const job = await api('/api/evaluations/' + id);
      renderEvalProgress(job);
      if (job.state !== 'running') { clearInterval(evalTimer); if (job.result) renderEvalResults(job.result); }
    } catch (e) { clearInterval(evalTimer); }
  }, 1500);
}

function renderEvalProgress(job) {
  if (!job) { $('#eval-progress').innerHTML = ''; return; }
  const done = job.total ? Math.round(100 * job.done / job.total) : 0;
  $('#eval-progress').innerHTML = `<p><strong>${esc(job.state)}</strong> · ${job.done || 0}/${job.total || '?'} seasons${job.elapsed_seconds ? ` · ${job.elapsed_seconds}s elapsed` : ''}${job.eta_seconds ? ` · ~${job.eta_seconds}s left` : ''}</p><div class="progress-track"><div style="width:${done}%"></div></div>`;
  $('#eval-run').disabled = job.state === 'running';
}

function renderEvalResults(res) {
  const rows = Object.keys(res.teams).sort((a, b) => res.teams[b].title_rate - res.teams[a].title_rate).map(t => {
    const r = res.teams[t], iv = r.title_interval || {};
    const span = iv.low === null || iv.low === undefined ? '—' : `[${pct(iv.low)}, ${pct(iv.high)}]`;
    return `<tr class="${t === 'Oscar' ? 'mine' : ''}"><td>${esc(t)}</td><td>${pct(r.title_rate)}</td><td>${span}</td><td>${pct(r.qualification_rate)}</td><td>${r.advancement.toFixed(2)}</td></tr>`;
  }).join('');
  const stale = res.session.id !== session.id || res.revision !== state.revision;
  const staleNote = stale ? '<p class="validation-warning">These results belong to an earlier roster revision/session snapshot — not your current board.</p>' : '';
  $('#eval-results').innerHTML = `<h3>Simulated season outcomes · ${esc(res.session.name)}</h3>${staleNote}<p class="hint">${res.season_count} seasons in ${res.elapsed_seconds}s · fixed recorded rosters. The projected category comparison above is <strong>separate</strong> from these simulated outcomes. Uncertainty is season sampling conditional on the model — <strong>not</strong> independent draft constructions, and there is no drafting to vary.</p><div class="table-scroll"><table><thead><tr><th>Team</th><th>Championship</th><th>95% (season)</th><th>Top 8</th><th>Advancement</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  $('#eval-assumptions').innerHTML = '<ul class="hint">' + Object.entries(res.assumptions || {}).map(([k, v]) => `<li><strong>${esc(k)}:</strong> ${esc(String(v))}</li>`).join('') + `<li><strong>projections sha256:</strong> ${esc((res.projections_sha256 || '').slice(0, 12))}</li><li><strong>source revision:</strong> ${res.revision}</li></ul>`;
  $('#eval-raw').textContent = JSON.stringify(res, null, 1);
}

function renderEvalHistory(rows) {
  $('#eval-history').innerHTML = (rows || []).map(e => `<div class="recent-row">${esc((e.session && e.session.name) || '?')} · rev ${e.revision} · ${esc(e.state)} · ${e.seasons || '?'} seasons</div>`).join('') || '<p class="empty">No evaluations yet.</p>';
}

function renderBoard() {
  let html = '<div class="board-grid">' + metadata.teams.map(t=>`<div class="board-header">${esc(t)}</div>`).join('');
  for(let round=1;round<=13;round++) {
    for(const team of metadata.teams) {
      const s=state.slots.find(s=>Number(s.round)===round && s.original_team===team);
      html += `<button class="board-cell ${s.keeper?'keeper':''} ${s.current_team==='Oscar'?'mine':''} ${!s.current_team?'unresolved':''} ${s.slot===state.current_slot?'current':''}" data-slot="${s.slot}"><small>R${round} · #${s.slot}</small>${esc(s.player_name || (s.keeper?s.keeper_player:'—'))}<small>${s.current_team!==team?esc(s.current_team || 'OWNER UNKNOWN'):''}${s.keeper?' · KEEPER':''}</small></button>`;
    }
  }
  $('#draft-board').innerHTML=html+'</div>';
  document.querySelectorAll('[data-slot]').forEach(el=>el.onclick=()=>openSlot(Number(el.dataset.slot)));
}
function keeperChoices() {
  const team=$('#slot-owner').value;
  const keepers=players.filter(p=>p.keeper===team);
  const s=state.slots[correctionSlot-1];
  $('#slot-keeper-name').innerHTML='<option value="">Select confirmed keeper</option>'+keepers.map(p=> {
    // Sheet alias uses Alex Sarr rather than Alexandre Sarr; server validates source name.
    const name=p.name==='Alexandre Sarr'?'Alex Sarr':p.name;
    return `<option value="${esc(name)}" ${s.keeper_player===name?'selected':''}>${esc(name)}</option>`;
  }).join('');
}
function openSlot(number) {
  correctionSlot=number; const s=state.slots[number-1];
  $('#slot-title').textContent=`Slot #${number} · Round ${s.round}`;
  $('#slot-owner').innerHTML='<option value="">Ownership unresolved</option>'+metadata.teams.map(t=>`<option ${s.current_team===t?'selected':''}>${esc(t)}</option>`).join('');
  $('#slot-keeper').checked=s.keeper; keeperChoices();
  $('#clear-pick').disabled=!s.player_id; $('#correct-pick').disabled=s.keeper;
  $('#slot-dialog').showModal();
}
function renderSettings() {
  const settings={streaming:true,playoff_priority:.85,risk:.5,history_weight:.15,future_keeper:.08,punt:[],week_weights:[1,1,1],...state.settings};
  $('#streaming').checked=settings.streaming;
  for(const key of ['playoff_priority','risk','history_weight','future_keeper']) { $('#'+key).value=settings[key]; $('#'+key).nextElementSibling.textContent=settings[key]; }
  $('#punt-options').innerHTML=metadata.categories.map(c=>`<label class="check"><input type="checkbox" name="punt" value="${esc(c)}" ${settings.punt.includes(c)?'checked':''}>${esc(c)}</label>`).join('');
  settings.week_weights.forEach((w,i)=>$('#week-'+i).value=w);
}
function renderQuality() {
  const schedule=metadata.schedule;
  const unresolved=state.slots.filter(s=>!s.current_team);
  const warnings = result?.session_id===session.id && result.revision===state.revision ? result.warnings : metadata.warnings;
  $('#data-quality').innerHTML=`<p><strong>${metadata.players} projections · ${metadata.keepers} keepers matched</strong></p><p class="hint">${esc(metadata.projection_file)}<br>Capture: ${esc(metadata.projection_source_date)}</p><p><strong>${schedule?`${schedule.playoff_games} daily playoff fixtures · weekly counts reconciled`:'Weekly schedule fallback only'}</strong></p>${schedule?`<p class="hint">Retrieved ${esc(schedule.retrieved_at)}<br>Source: ${esc(schedule.source)}<br>Official fixture cross-check: ${schedule.official_fixture_crosscheck?'complete':'pending'}</p>`:''}<ul class="quality-list">${warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul><h3>Ownership / keeper reconciliation</h3><p>${unresolved.length?'Unresolved slots: '+unresolved.map(s=>s.slot).join(', '):'All pick owners assigned locally.'}</p>${metadata.exceptions.map(e=>`<p class="hint">${esc(e.team)} · R${e.round}: ${esc(e.players)}. Resolve exact slots on the board.</p>`).join('')}<p class="hint">Confirmed: same-day free agents; two-day FAB waivers; four adds/week; fixed playoff bracket; no reseeding. Exact playoff ties are not implemented in this model.</p>`;
  $('#model-notes').innerHTML='<ul class="hint">'+(result?.model_notes || ['Recommendation engine loading.']).map(n=>`<li>${esc(n)}</li>`).join('')+'</ul>';
}
async function poll() {
  try {
    const payload=await api('/api/recommendations'); pollFailures=0;
    if(payload.session_id!==session.id || payload.revision!==state.revision) {
      const changed=payload.session_id!==session.id;
      await refresh();
      if(changed) notice(`Active draft changed to ${session.name}. Picks will be recorded only in this session.`);
    }
    if(payload.error) notice(`Recommendation error: ${payload.error}. Pick recording remains available.`,true);
    if(payload.result?.session_id===session.id && (!result || result.revision!==payload.result.revision || result.session_id!==payload.result.session_id)) { result=payload.result; renderRecommendations(); }
    if(payload.running) { $('#engine-status').textContent='Calculating · pick entry remains available'; $('#engine-status').classList.add('stale'); }
  } catch(e) { pollFailures++; if(pollFailures>2) notice('Local server unavailable. Restart python3 run.py, then reload. Unsaved clicks are not recorded.',true); }
  recTimer=setTimeout(poll,1000);
}
function resetClock(start) {
  clearInterval(clockInterval); let seconds=45; $('#clock').textContent=seconds; $('.clock').classList.remove('warning');
  $('#clock-start').textContent=start?'Reset timer':'Start timer';
  if(start) clockInterval=setInterval(()=>{ seconds=Math.max(0,seconds-1); $('#clock').textContent=seconds; $('.clock').classList.toggle('warning',seconds<=10); if(!seconds) clearInterval(clockInterval); },1000);
}
document.querySelectorAll('nav button').forEach(el=>el.onclick=()=>switchTab(el.dataset.tab));
$('#search').addEventListener('input',()=>{selected=0;renderSearch();});
$('#search').addEventListener('keydown',e=>{
  const down=e.key==='ArrowDown'||(e.ctrlKey&&e.key==='j'), up=e.key==='ArrowUp'||(e.ctrlKey&&e.key==='k');
  if(down||up) { e.preventDefault(); selected=Math.max(0,Math.min(searchRows.length-1,selected+(down?1:-1)));renderSearch(); $('.search-row.selected')?.scrollIntoView({block:'nearest'}); }
  if(e.key==='Enter') { e.preventDefault(); if(searchRows[selected]) record(searchRows[selected].id); }
  if(e.key==='Escape') { $('#search').value='';target=null;selected=0;renderSearch(); }
});
document.addEventListener('keydown',e=>{
  const typing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName);
  if(e.key==='/'&&!typing&&!$('#slot-dialog').open) { e.preventDefault();switchTab('draft');$('#search').select(); }
  if((e.metaKey||e.ctrlKey)&&e.key==='z'&&(!typing||!$('#search').value)&&!$('#slot-dialog').open) {e.preventDefault();$('#undo').click();}
});
window.addEventListener('focus',()=>{if(state&&$('#draft').classList.contains('active')&&!$('#slot-dialog').open) $('#search').focus();});
$('#undo').onclick=async()=>{if(busy||!state.undo_event)return;busy=true;try{await event('undo',{event_id:state.undo_event});target=null;renderSearch();notice('Last action undone; availability and board restored.');}catch(e){notice(e.message,true);}finally{busy=false;$('#search').focus();}};
$('#manual-player').onclick=()=>{
  const name=prompt('Unlisted player name (no projection will be invented):',$('#search').value);
  if(name?.trim()) { const id='manual:'+crypto.randomUUID(); record(id,{id,name:name.trim()}); }
};
$('#batch-submit').onclick=async()=>{
  if(busy)return;
  const names=$('#batch').value.split('\n').map(s=>s.trim()).filter(Boolean);
  if(!names.length)return;
  const pool=available(), batch=[], seen=new Set();
  for(const name of names) {
    const matches=pool.filter(p=>normalize(p.name)===normalize(name));
    if(matches.length!==1||seen.has(matches[0]?.id)){notice(`Batch not recorded: "${name}" is missing, ambiguous, kept, drafted, or repeated. Use exact listed names.`,true);return;}
    seen.add(matches[0].id);batch.push(matches[0]);
  }
  const slots=state.slots.filter(s=>!s.keeper&&!s.player_id).slice(0,batch.length);
  if(slots.length!==batch.length||slots.some(s=>!s.current_team)){notice('Batch not recorded: insufficient slots or unresolved ownership.',true);return;}
  if(!confirm(batch.map((p,i)=>`#${slots[i].slot} ${slots[i].current_team}: ${p.name}`).join('\n')))return;
  busy=true;let saved=0;
  try {for(let i=0;i<batch.length;i++){await event('pick',{slot:slots[i].slot,player_id:batch[i].id});saved++;}$('#batch').value='';notice(`Saved ${saved} picks.`);}
  catch(e){$('#batch').value=names.slice(saved).join('\n');notice(`${saved} picks saved. Remaining names preserved. ${e.message}`,true);await refresh().catch(()=>{});}
  finally{busy=false;$('#search').focus();}
};
$('#slot-owner').onchange=keeperChoices;
$('#slot-keeper').onchange=()=>$('#correct-pick').disabled=$('#slot-keeper').checked;
$('#close-dialog').onclick=()=>$('#slot-dialog').close();
$('#slot-form').onsubmit=async e=>{
  e.preventDefault();const keeper=$('#slot-keeper').checked,name=keeper?$('#slot-keeper-name').value:'';
  if(!$('#slot-owner').value){notice('Choose the confirmed owner.',true);return;}
  try{await event('slot_override',{slot:correctionSlot,changes:{current_team:$('#slot-owner').value,keeper,keeper_player:name,player_name:state.slots[correctionSlot-1].player_id?state.slots[correctionSlot-1].player_name:name,confidence:'user_confirmed'}});$('#slot-dialog').close();notice('Slot settings saved.');}
  catch(e){notice(e.message,true);}
};
$('#correct-pick').onclick=()=>{target=correctionSlot;$('#slot-dialog').close();switchTab('draft');$('#search').value='';renderSearch();$('#search').focus();};
$('#clear-pick').onclick=async()=>{if(!confirm('Clear this live pick? The action remains in history and can be undone.'))return;try{await event('clear_pick',{slot:correctionSlot});$('#slot-dialog').close();notice('Pick cleared.');}catch(e){notice(e.message,true);}};
$('#clock-start').onclick=()=>resetClock(true);
document.querySelectorAll('[data-preset]').forEach(el=>el.onclick=()=>{const [d,s]=el.dataset.preset.split(',');$('#bench-drafts').value=d;$('#bench-seasons').value=s;notice(`Preset applied: ${d} drafts × ${s} seasons. Saved results stay above; adjust and run.`);});
const evalRunBtn=$('#eval-run'); if(evalRunBtn) evalRunBtn.onclick=runEvaluation;
document.querySelectorAll('input[type=range]').forEach(el=>el.oninput=()=>el.nextElementSibling.textContent=el.value);
$('#settings-form').onsubmit=async e=>{
  e.preventDefault();const payload={streaming:$('#streaming').checked,punt:[...document.querySelectorAll('input[name=punt]:checked')].map(el=>el.value),week_weights:[0,1,2].map(i=>Number($('#week-'+i).value))};
  if(payload.punt.length>2){notice('Choose at most two punt categories.',true);return;}
  for(const key of ['playoff_priority','risk','history_weight','future_keeper'])payload[key]=Number($('#'+key).value);
  try{await event('settings',payload);notice('Assumptions saved; recalculating.');}catch(e){notice(e.message,true);}
};
$('#restore').onclick=async()=>{const file=$('#restore-file').files[0];if(!file)return;try{const backup=JSON.parse(await file.text());await api('/api/restore',backup);await refresh();notice('Backup restored.');}catch(e){notice(e.message,true);}};
async function changeSession(action,targetId) {
  if(busy)return;busy=true;
  try {
    const payload=await api('/api/session',{action,target_id:targetId});
    acceptPayload(payload);renderState();renderSettings();renderQuality();
    $('#engine-status').textContent='Calculating for '+session.name;
    notice(`${session.name} active. ${session.mode==='mock'?'Practice picks do not change your live draft.':'Your saved live draft is restored.'}`);
  } catch(e) { notice(e.message,true);await refresh().catch(()=>{}); }
  finally {busy=false;renderSession();}
}
$('#new-mock').onclick=()=>changeSession('new_mock');
$('#reset-mock').onclick=()=>{if(confirm('Start a fresh mock with current setup and assumptions? This run stays saved, and your live picks are untouched.'))changeSession('reset_mock');};
$('#session-select').onchange=e=>changeSession('switch',e.target.value);
async function simulateOpponents(untilMe) {
  if(busy)return;busy=true;renderSession();
  try {
    const response=await api('/api/mock/advance',{revision:state.revision,until_me:untilMe});
    acceptPayload(response);target=null;selected=0;$('#search').value='';renderState();
    const picks=response.simulated.map(p=>`#${p.slot} ${p.team}: ${p.name}`).join(' · ');
    notice(`${picks || 'No picks recorded.'}${response.blocked?' · '+response.blocked:''}`);
    $('#engine-status').textContent='Updating mock recommendations…';
  } catch(e) {notice(e.message,true);await refresh().catch(()=>{});}
  finally {busy=false;renderSession();$('#search').focus();}
}
$('#mock-one').onclick=()=>simulateOpponents(false);$('#mock-until').onclick=()=>simulateOpponents(true);
async function mockConfig() {
  try {const response=await api('/api/mock/config',{model:$('#mock-model').value,randomness:Number($('#mock-randomness').value)});acceptPayload(response);renderState();notice('Mock opponent assumptions saved.');}
  catch(e){notice(e.message,true);}
}
$('#mock-model').onchange=mockConfig;$('#mock-randomness').onchange=mockConfig;
$('#persona-manager').onchange=renderPersona;
$('#save-draft-model').onclick=async()=>{try{await event('settings',{draft_model:$('#draft-model').value,mc_trials:Number($('#mc-trials').value)});notice('Prediction model saved; survival recalculating.');}catch(e){notice(e.message,true);}};
$('#persona-form').onsubmit=async e=>{
  e.preventDefault();const manager=$('#persona-manager').value, overrides={...(state.settings.manager_overrides || {})}, values={};
  for(const field of document.querySelectorAll('#persona-fields input'))if(field.value!=='')values[field.name]=Number(field.value);
  values.targets={...(overrides[manager]?.targets || {})};
  if($('#persona-target').value)values.targets[$('#persona-target').value]=Number($('#persona-target-weight').value);
  overrides[manager]=values;
  try{await event('settings',{manager_overrides:overrides});renderPersona();notice('Subjective manager adjustments saved separately from observations.');}catch(e){notice(e.message,true);}
};
$('#reset-persona').onclick=async()=>{const overrides={...(state.settings.manager_overrides || {})};delete overrides[$('#persona-manager').value];try{await event('settings',{manager_overrides:overrides});renderPersona();notice('Manager assumptions reset; historical observations unchanged.');}catch(e){notice(e.message,true);}};
$('#save-scenarios').onclick=async()=>{try{const scenarios=JSON.parse($('#draft-scenarios').value);await event('settings',{draft_scenarios:scenarios});notice('Named scenarios validated. No live pick ownership or keeper slots were changed.');}catch(e){notice(e.message,true);}};
$('#roster-details').open=innerWidth>1100 || innerWidth<=700;
refresh().then(poll).catch(e=>notice(`Could not load local app: ${e.message}`,true));

// Season experiments run in an isolated process against an immutable snapshot.
let benchMetadata,benchResult,benchStatus,benchTimer,benchLoading=false;
const MODEL_LABELS={adp_stochastic:'ADP stochastic · pooled adherence (recommended primary)',validated:'Validated model + modest fit (sensitivity)',fit:'ADP + modest roster fit (sensitivity)',persona_experimental:'Experimental draft personas · n=1 season (sensitivity)',adp_deterministic:'Strict Yahoo ADP · deterministic (compresses league spread; baseline only)'};
const HYPOTHESIS={name:'Illustrative unverified cycle · 106 Raul / 113 Samet / 123 Nick',owners:{'106':'Raul','113':'Samet','123':'Nick'},keeper_slots:{'111':'VJ Edgecombe','113':'Dylan Harper','123':'Jabari Smith Jr.','128':'Ace Bailey'}};
async function initializeBench() {
  if(benchMetadata)return;
  benchMetadata=await api('/api/benchmark-config');
  $('#bench-input-notes').innerHTML='<ul class="hint">'+benchMetadata.notes.map(n=>'<li>'+esc(n)+'</li>').join('')+'</ul>';
  const strategies=structuredClone(benchMetadata.default_strategies);
  const cal=benchMetadata.calendar || [];
  const league=cal.filter(w=>w.week<=20);
  $('#bench-calendar-view').innerHTML=league.length?`<p class="hint">${cal.length} Yahoo weeks verified (${league.length} league + ${cal.length-league.length} post-league).</p><div class="table-scroll"><table><thead><tr><th>Week</th><th>Start</th><th>End</th><th>Days</th><th>Type</th></tr></thead><tbody>${league.map(w=>`<tr><td>${w.week}${w.extended?' ●':''}</td><td>${esc(w.start)}</td><td>${esc(w.end)}</td><td>${w.days}</td><td>${esc(w.week_type)}</td></tr>`).join('')}</tbody></table></div>`:'';
  if(state.settings.punt?.length)strategies[0]={name:'Current locked build',policy:'playoff',punts:state.settings.punt,streaming:'aggressive'};
  $('#bench-strategies').value=JSON.stringify(strategies,null,2);
  $('#bench-assets').value=JSON.stringify(state.settings.draft_scenarios || [],null,2);
  $('#bench-opponents').innerHTML=benchMetadata.opponent_modes.map(m=>`<label class="check"><input type="checkbox" name="bench-mode" value="${esc(m)}" ${['adp_stochastic','validated'].includes(m)?'checked':''}>${esc(MODEL_LABELS[m])}</label>`).join('');
  estimateBench();
}
function estimateBench() {
  try {
    const strategies=JSON.parse($('#bench-strategies').value),assets=JSON.parse($('#bench-assets').value);
    const modes=document.querySelectorAll('[name="bench-mode"]:checked').length;
    const total=strategies.length*Math.max(1,assets.length)*modes*Number($('#bench-drafts').value)*Number($('#bench-seasons').value);
    $('#bench-estimate').textContent=`${total} season simulations · roughly ${(total*3/60).toFixed(1)} min in a background job · small samples may be inconclusive`;
  } catch {$('#bench-estimate').textContent='Complete valid JSON to estimate batch size.';}
}
function benchmarkConfig() {
  const config={strategies:JSON.parse($('#bench-strategies').value),opponent_modes:[...document.querySelectorAll('[name="bench-mode"]:checked')].map(el=>el.value),
    drafts:Number($('#bench-drafts').value),seasons_per_draft:Number($('#bench-seasons').value),seed:Number($('#bench-seed').value),
    start_mode:$('#bench-start').value,manager_policies:JSON.parse($('#bench-manager-policies').value),
    asset_scenarios:JSON.parse($('#bench-assets').value),
    injury_scale:Number($('#bench-injury').value),mean_injury_days:Number($('#bench-duration').value),il_delay_days:Number($('#bench-il-delay').value),
    protected_core:Number($('#bench-core').value),starting_fab:Number($('#bench-fab').value),minimum_bid:Number($('#bench-minbid').value),
    waiver_days:Number($('#bench-waivers').value),eligibility:$('#bench-eligibility').value,streaming_model:$('#bench-streaming').value,extended_adds:$('#bench-extended').value};
  if($('#bench-calendar').value.trim()){config.calendar=JSON.parse($('#bench-calendar').value);config.calendar_source=$('#bench-calendar-source').value;}
  return config;
}
$('#bench-form').addEventListener('input',estimateBench);
$('#bench-example-assets').onclick=()=>{if(confirm('Fill a structurally valid but UNVERIFIED hypothesis? These owners and keeper assets are not confirmed facts and will not edit your draft.')){$('#bench-assets').value=JSON.stringify([HYPOTHESIS],null,2);estimateBench();}};
$('#bench-form').onsubmit=async e=>{
  e.preventDefault();if(benchLoading)return;benchLoading=true;$('#bench-run').disabled=true;
  try {
    const config=benchmarkConfig();
    const response=await api('/api/benchmarks',{config,revision:state.revision});
    await loadBenchRuns(response.run_id);notice('Benchmark started in a separate process. Your draft state is unchanged.');
    await pollBench();
  }catch(e){notice(e.message,true);}
  finally{benchLoading=false;$('#bench-run').disabled=false;}
};
async function loadBenchRuns(selectId) {
  const previous=selectId || $('#bench-runs').value;
  const response=await api('/api/benchmarks');
  $('#bench-runs').innerHTML=response.runs.length?response.runs.map(r=>`<option value="${esc(r.run_id)}" ${r.run_id===previous?'selected':''}>${esc(r.created_at.slice(0,19))} · ${esc(r.state)} · ${r.completed || 0}/${r.total || '?'} seasons · ${esc(r.source_session.name)}</option>`).join(''):'<option value="">No saved benchmarks</option>';
  if($('#bench-runs').value)await pollBench();
}
async function pollBench() {
  clearTimeout(benchTimer);const id=$('#bench-runs').value;if(!id)return;
  try {
    benchStatus=await api('/api/benchmarks/'+id);
    $('#bench-progress').innerHTML=`<strong>${esc(benchStatus.state)}</strong> · ${benchStatus.completed || 0}/${benchStatus.total || '?'} seasons${benchStatus.current?' · '+esc(benchStatus.current.strategy)+' · draft '+benchStatus.current.draft+' / season '+benchStatus.current.season:''}${benchStatus.error?'<p class="validation-warning">'+esc(benchStatus.error)+'</p>':''}<div class="progress-track"><div></div></div>`;
    $('#bench-progress .progress-track>div').style.width=`${benchStatus.total?Math.min(100,100*benchStatus.completed/benchStatus.total):0}%`;
    $('#bench-cancel').disabled=benchStatus.state!=='running';$('#bench-resume').disabled=!['cancelled','interrupted','failed'].includes(benchStatus.state);
    $('#bench-export').href='/api/benchmarks/'+id+'/export';
    const response=await api('/api/benchmarks/'+id+'/results');
    if(response.result){benchResult=response.result;renderBench();}
    if(benchStatus.state==='running')benchTimer=setTimeout(pollBench,2000);
  }catch(e){$('#bench-progress').textContent=e.message;}
}
function renderRecommendation(rec) {
  if(!rec)return '';
  const tone={strong:'badge',equivalent:'badge',lean:'badge warn',inconclusive:'badge warn',baseline:'badge',pending:'badge warn'}[rec.status] || 'badge warn';
  if(rec.status==='pending')return `<div class="recommendation-box"><p><span class="${tone}">RECOMMENDATION</span> ${esc(rec.message)}</p></div>`;
  const rows=rec.case_results.map(p=>{
    const gap=(p.gap_title_interval&&p.gap_title_interval.low!==null)?`${(100*p.gap_title).toFixed(1)} pts (${(100*p.gap_title_interval.low).toFixed(1)}–${(100*p.gap_title_interval.high).toFixed(1)})`:'n/a';
    const sep=p.model_separation?`${Math.round(100*p.model_separation.shared_roster_share)}% shared ${p.model_separation.informative?'':'⚠'}`:'n/a';
    const decisive=`${p.decisive_title_clusters}/${p.drafts}`;
    return `<tr><td>${esc(p.assets)}</td><td>${esc(p.winner)}</td><td>${pct(p.winner_title_rate)}</td><td>${pct(p.winner_conditional_title_rate)}</td><td>${p.winner_advancement.toFixed(2)}</td><td>${pct(p.winner_qualification_rate)}</td><td>${esc(p.runner_up || '—')}</td><td>${gap}</td><td>${decisive}</td><td>${p.stable_across_models?'yes':'no'}</td><td>${sep}</td><td>${p.drafts}</td></tr>`;
  }).join('');
  const sampling=rec.sampling_advice?`<p class="hint">${esc(rec.sampling_advice)} ${esc(rec.draft_efficiency||'')} Manager personas failed validation, so this spread now comes from draft and season luck rather than opponent identity.</p>`:'';
  const headline=esc(rec.headline);
  return `<div class="recommendation-box"><p><span class="${tone}">RECOMMENDATION · ${esc(rec.status.toUpperCase())}</span> ${headline}</p>
  <p class="hint">Ranked on the primary model <strong>${esc(MODEL_LABELS[rec.basis] || rec.basis)}</strong> by <strong>unconditional championship probability</strong>, then stress-tested on the other selected models for agreement. Advancement, conditional title probability and qualification rate are supporting metrics. Models are never averaged: their relative realism is unvalidated, so agreement is required instead — but only when the models actually differ (shared-roster share below). A firm (strong) call also needs enough <em>decisive draft clusters</em>, so a lead resting on one or two simulated titles stays a lean.</p>${sampling}
  <div class="table-scroll"><table><thead><tr><th>Asset scenario</th><th>Best strategy</th><th>Title rate</th><th>Cond. title</th><th>Mean advancement</th><th>Top 8</th><th>Runner-up</th><th>Paired title gap (95%)</th><th>Decisive clusters</th><th>Agrees across models</th><th>Models differ</th><th>Drafts</th></tr></thead><tbody>${rows}</tbody></table></div>
  <ul class="hint">${rec.caveats.map(c=>'<li>'+esc(c)+'</li>').join('')}</ul></div>`;
}

function renderBench() {
  const cases=benchResult.cases.filter(c=>c.summary);
  $('#bench-recommendation').innerHTML=renderRecommendation(benchResult.recommendation);
  $('#bench-comparison').innerHTML=cases.length?`<p class="hint">Results are SIMULATED, not actual league outcomes. Rows are separate asset/opponent scenarios, not a weighted overall ranking. Intervals resample drafts, not independent seasons.</p><div class="table-scroll"><table><thead><tr><th>Your strategy / assets</th><th>Opponent model</th><th>Seasons</th><th>Projected rank</th><th>Sim regular rank</th><th>Top 8</th><th>Semifinal</th><th>Final</th><th>Titles</th><th>Title interval</th></tr></thead><tbody>${cases.map(c=>{const t=c.summary.Oscar;return `<tr><td>${esc(c.strategy.name)}<br><span class="muted">${esc(c.asset_scenario)}</span></td><td>${esc(MODEL_LABELS[c.opponent_mode])}</td><td>${c.n_seasons}</td><td>${t.projected_rank.toFixed(1)}</td><td>${t.simulated_regular_rank.mean.toFixed(1)}</td><td>${pct(t.qualification_rate)}</td><td>${pct(t.semifinal_rate)}</td><td>${pct(t.final_rate)}</td><td>${pct(t.title_rate)}</td><td>${pct(c.own_title_interval.low)}–${pct(c.own_title_interval.high)}</td></tr>`;}).join('')}</tbody></table></div><details><summary>Assumptions, limitations and provenance</summary><ul class="hint">${benchResult.notes.map(n=>'<li>'+esc(n)+'</li>').join('')}${Object.entries(benchResult.config.assumptions).map(([k,v])=>'<li><strong>'+esc(k)+':</strong> '+esc(v)+'</li>').join('')}</ul></details>`:'<p class="hint">No complete season yet. Failed or cancelled partial drafts are not counted as outcomes.</p>';
  $('#bench-paired').innerHTML=(benchResult.paired_comparisons || []).length?'<h3>Paired strategy differences</h3>'+benchResult.paired_comparisons.map(p=>`<p class="hint">${esc(p.strategy)} vs ${esc(p.reference)} · ${esc(p.opponent_mode)} · ${esc(p.assets)}: title-rate difference ${(100*p.paired_title_rate_difference).toFixed(1)} points; cluster interval ${(100*p.draft_cluster_95_interval[0]).toFixed(1)} to ${(100*p.draft_cluster_95_interval[1]).toFixed(1)}. <strong>${p.supported_improvement?'Positive within this model/scenario':'No demonstrated improvement'}</strong></p>`).join(''):'';
  const selected=$('#bench-case').value;
  $('#bench-case').innerHTML=cases.map(c=>`<option value="${c.id}" ${String(c.id)===selected?'selected':''}>${esc(c.strategy.name)} · ${esc(c.opponent_mode)} · ${esc(c.asset_scenario)}</option>`).join('');
  renderBenchDrafts();
}
function selectedBenchCase(){return benchResult?.cases.find(c=>String(c.id)===$('#bench-case').value);}
function renderBenchDrafts() {
  const c=selectedBenchCase();if(!c)return;const current=$('#bench-draft').value;
  $('#bench-draft').innerHTML=c.drafts.map(d=>`<option value="${d.index}" ${String(d.index)===current?'selected':''}>Draft ${d.index+1} · ${d.seasons.length} seasons</option>`).join('');
  renderBenchSeasons();
}
function renderBenchSeasons() {
  const c=selectedBenchCase(),d=c?.drafts.find(d=>String(d.index)===$('#bench-draft').value);if(!d)return;
  const current=$('#bench-season').value;
  $('#bench-season').innerHTML='<option value="mean">Mean of this draft’s seasons</option>'+d.seasons.map(s=>`<option value="${s.index}" ${String(s.index)===current?'selected':''}>Season ${s.index+1}</option>`).join('');
  renderBenchTeams();
}
function renderBenchTeams() {
  const c=selectedBenchCase(),d=c?.drafts.find(d=>String(d.index)===$('#bench-draft').value);if(!d)return;
  const season=d.seasons.find(s=>String(s.index)===$('#bench-season').value);
  const outcomes=season?[season]:d.seasons;
  const mean=(team,key)=>outcomes.length?outcomes.reduce((n,s)=>n+Number(s.teams[team][key]),0)/outcomes.length:NaN;
  const teams=metadata.teams.slice().sort((a,b)=>d.projected[a].rank-d.projected[b].rank);
  $('#bench-team-table').innerHTML=`<p class="hint">${season?'Realized simulated season '+(season.index+1):'Average across '+outcomes.length+' seasons for this fixed draft'}. Projected rank excludes streaming and realized health. ${c.distinct_own_rosters===1?'This case has only one distinct own drafted roster so far.':''}</p><div class="table-scroll"><table><tr><th>Manager</th><th>Projected rank</th><th>Sim regular rank</th><th>Sim finish</th><th>Qualified</th><th>Titles</th><th>Adds</th><th>Starts</th><th>Blocked</th><th>IL player-days</th><th>FAB spent</th></tr>${teams.map(t=>`<tr><td>${esc(t)}</td><td>${d.projected[t].rank}</td><td>${mean(t,'regular_rank').toFixed(1)}</td><td>${mean(t,'finish').toFixed(1)}</td><td>${pct(mean(t,'qualified'))}</td><td>${pct(mean(t,'champion'))}</td><td>${mean(t,'adds').toFixed(1)}</td><td>${mean(t,'starts').toFixed(1)}</td><td>${mean(t,'blocked_games').toFixed(1)}</td><td>${mean(t,'il_player_days').toFixed(1)}</td><td>${mean(t,'budget_spent').toFixed(1)}</td></tr>`).join('')}</table></div>`;
  $('#bench-rosters').innerHTML='<div class="roster-inspection">'+teams.map(t=>`<details ${t==='Oscar'?'open':''}><summary>${esc(t)} · projected #${d.projected[t].rank}</summary><p class="hint">${d.draft.punts[t].length?'Punt '+esc(d.draft.punts[t].join(' + ')):'Balanced'}<br>${d.draft.rosters[t].map(id=>esc(playerById(id)?.name || id)).join('<br>')}</p></details>`).join('')+'</div>';
  $('#bench-season-detail').innerHTML='';
  if(season)loadBenchDetail(c.id,d.index,season.index).catch(e=>$('#bench-season-detail').textContent=e.message);
}
async function loadBenchDetail(caseId,draftIndex,seasonIndex) {
  const id=$('#bench-runs').value;
  const detail=await api(`/api/benchmarks/${id}/detail?case=${caseId}&draft=${draftIndex}&season=${seasonIndex}`);
  if($('#bench-case').value!==String(caseId)||$('#bench-draft').value!==String(draftIndex)||$('#bench-season').value!==String(seasonIndex))return;
  $('#bench-season-detail').innerHTML=`<h3>Weekly results & transactions</h3><div class="table-scroll"><table><tr><th>Week</th><th>Your opponent / result</th><th>Your adds</th><th>Eligible managers</th></tr>${detail.weekly.map(w=>{const m=w.matchups.find(m=>m.a==='Oscar'||m.b==='Oscar');return `<tr><td>${w.week} · ${esc(w.start)}–${esc(w.end)}</td><td>${m?esc(m.a==='Oscar'?m.b:m.a)+' · '+(m.a==='Oscar'?m.a_wins:m.b_wins)+'–'+(m.a==='Oscar'?m.b_wins:m.a_wins)+'–'+m.ties:'No matchup'}</td><td>${w.adds.Oscar}</td><td>${w.eligible.length}</td></tr>`;}).join('')}</table></div><details><summary>Your acquisition/IL audit</summary><div class="hint">${detail.transactions.filter(t=>t.team==='Oscar').map(t=>`${esc(t.day)} · ${esc(t.type)} · ${esc(playerById(t.player_id)?.name || t.player_id)}${t.bid!==undefined?' · $'+t.bid:''}${t.reason?' · '+esc(t.reason):''}`).join('<br>')}</div></details><p class="hint">The exported report contains full provenance; per-season detail files in the local run folder retain all managers’ transactions and simulated injuries.</p>`;
}
$('#bench-refresh').onclick=()=>loadBenchRuns().catch(e=>notice(e.message,true));
$('#bench-runs').onchange=()=>{benchResult=null;pollBench();};
$('#bench-case').onchange=renderBenchDrafts;$('#bench-draft').onchange=renderBenchSeasons;$('#bench-season').onchange=renderBenchTeams;
$('#bench-cancel').onclick=async()=>{try{await api('/api/benchmarks/'+$('#bench-runs').value+'/cancel',{});notice('Cancellation requested; completed seasons will be retained.');await pollBench();}catch(e){notice(e.message,true);}};
$('#bench-resume').onclick=async()=>{try{await api('/api/benchmarks/'+$('#bench-runs').value+'/resume',{});notice('Resuming the immutable saved request.');await pollBench();}catch(e){notice(e.message,true);}};
$('#mock-complete').onclick=async()=>{
  if(busy)return;
  const scenarios=state.settings.draft_scenarios || [];
  if(scenarios.length>1){notice('Choose one explicit asset hypothesis or correct the mock board before automatic completion.',true);return;}
  if(!confirm(`Automatically record all remaining mock picks using the current punt build and strict ADP opponents? ${scenarios[0]?'Apply the explicitly saved UNVERIFIED asset scenario: '+scenarios[0].name+'. ':''}Live picks stay untouched.`))return;
  busy=true;
  try{const response=await api('/api/mock/complete',{revision:state.revision,scenario:scenarios[0] || null,opponent_mode:'adp_deterministic'});acceptPayload(response);renderState();notice(`Mock complete: ${response.simulated.length} automatic picks saved. Live draft unchanged. Use “Evaluate this draft” on the completion screen.`);}
  catch(e){notice(e.message,true);}
  finally{busy=false;renderSession();}
};
