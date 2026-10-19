"""Partial/final policy audit reports; no tuning or winner-selected evidence."""
import itertools
import json
import math
import random
import statistics as st
from pathlib import Path

from policy_audit_worker import atomic, seed, POLICIES, hashed


def quantile(xs,q):
    xs=sorted(xs)
    if not xs:return None
    x=(len(xs)-1)*q;i=int(x)
    return xs[i] if i==len(xs)-1 else xs[i]+(xs[i+1]-xs[i])*(x-i)


def distribution(xs):
    xs=list(xs)
    return {'n':len(xs),'mean':st.mean(xs) if xs else None,
            'p10':quantile(xs,.1),'median':quantile(xs,.5),'p90':quantile(xs,.9),'max':max(xs) if xs else None}


def paired(a,b,metric,family=18):
    common=sorted(set(a)&set(b))
    diffs=[st.mean(x[metric] for x in a[i]['outcomes'])-st.mean(x[metric] for x in b[i]['outcomes']) for i in common]
    if not diffs:return {'paths':0}
    n=len(diffs);mu=st.mean(diffs);iv=None
    if n>=3:
        rng=random.Random(seed('report',metric,common))
        boots=sorted(st.mean(rng.choices(diffs,k=n)) for _ in range(1500))
        iv=[boots[37],boots[1461]]
    width=4 if metric=='advancement' else 1
    radius=width*math.sqrt(2*math.log(2*family/.05)/n)
    return {'paths':n,'difference':mu,'pointwise_cluster_bootstrap_95':iv,
            'simultaneous_bounded_95':[max(-width,mu-radius),min(width,mu+radius)],
            'note':'Paired per-path means; repeated seasons do not increase independent n. No equivalence or noninferiority inferred.'}


def load_rows(run,lane):
    rows=[]
    for p in sorted((run/lane/'tasks').glob('*.json')):
        if p.name.endswith('.checkpoint.json'):continue
        full=json.loads(p.read_text())
        rows.append({'task':full['task'],'path':str(p.relative_to(run)),
            'diagnostics':{k:v for k,v in full['diagnostics'].items() if k!='analysis'},
            'outcomes':full['outcomes'],'roster':full['draft']['rosters']['Oscar'],
            'rosters':full['draft']['rosters'],
            'decisions':[{k:v for k,v in d.items() if k not in ('board','alternatives','available')} for d in full['decisions']]})
    return rows


def summarize(rows):
    if not rows:return {'paths':0}
    metric={m:distribution(st.mean(o[m] for o in r['outcomes']) for r in rows) for m in ('title','qualified','advancement')}
    quality={m:distribution(r['diagnostics'][m] for r in rows) for m in
             ('five_category_route_fraction','fifth_category_edge','usable_starts','blocked_games','risk1_route_fraction','risk1_usable_starts')}
    cats=list(rows[0]['diagnostics']['category_edges'])
    categories={c:distribution(r['diagnostics']['category_edges'][c] for r in rows) for c in cats}
    weak=st.mean(r['diagnostics']['five_category_route_fraction']<.33 for r in rows)
    return {'paths':len(rows),'seasons':sum(len(r['outcomes']) for r in rows),'outcomes':metric,
        'quality':quality,'categories':categories,'weak_route_frequency':weak,
        'no_title_despite_strong_projected_route':sum(r['diagnostics']['five_category_route_fraction']>=2/3 and not any(o['title'] for o in r['outcomes']) for r in rows),
        'note':'A no-title sample does not diagnose a bad roster. Weak-route cutoff is a pre-registered descriptive heuristic.'}


def publish(run,lane):
    rows=load_rows(run,lane);manifest=json.loads((run/'manifest.json').read_text())
    status_path=run/lane/'status.json';status=json.loads(status_path.read_text()) if status_path.exists() else {'state':'pending'}
    book=json.loads((run/'source/FIRST_THREE_PICKS_PLAYBOOK.json').read_text());names={p:v['name'] for p,v in book['players'].items()}
    grouped={};pairs={};examples=[];failures=[]
    for stage,model in sorted({(r['task']['stage'],r['task']['model']) for r in rows}):
        rr=[r for r in rows if (r['task']['stage'],r['task']['model'])==(stage,model)]
        by={p:{r['task']['index']:r for r in rr if r['task']['policy']==p} for p in POLICIES}
        common=set.intersection(*(set(v) for v in by.values()))
        # Complete four-policy source paths only; retain incomplete task results on
        # disk but don't manufacture balanced evidence from a partly finished path.
        balanced={p:[by[p][i] for i in sorted(common)] for p in POLICIES}
        key=stage+'/'+model
        grouped[key]={p:summarize(rs) for p,rs in balanced.items()}
        pairs[key]=[{'a':a,'b':b,'metrics':{m:paired({i:by[a][i] for i in common},{i:by[b][i] for i in common},m) for m in ('title','qualified','advancement')}}
                    for a,b in itertools.combinations(POLICIES,2)]
        for policy,rs in balanced.items():
            ordered=sorted(rs,key=lambda r:(r['diagnostics']['five_category_route_fraction'],r['diagnostics']['fifth_category_edge']))
            if ordered:
                for label,index in [('weak',0),('typical',len(ordered)//2),('strong',len(ordered)-1)]:
                    r=ordered[index];d=r['diagnostics']
                    examples.append({'stage':stage,'model':model,'policy':policy,'label':label,
                        'source_index':r['task']['index'],'source_file':r['path'],
                        'roster':[names[p] for p in r['roster']], 'diagnostics':d,
                        'season_outcomes':r['outcomes'],
                        'explanation':'Selected by projected five-category route fraction and fifth-strongest category edge, NOT championship losses. Full board, alternatives, scores, roster before/after and assumptions are in source_file.'})
    latency={}
    for phase,picks in [('early',[6,43,54]),('middle',[67,78,91]),('late',[102,115,126,150])]:
        ds=[d for r in rows if r['task']['policy']=='production' for d in r['decisions'] if d['slot'] in picks and d['recommended']]
        latency[phase]={**distribution(d['seconds'] for d in ds),'over_35':sum(d['seconds']>35 for d in ds),'over_45':sum(d['seconds']>45 for d in ds)}
    failure_map={}
    for r in rows:
        if r['task']['policy']!='production':continue
        reasons=[];d=r['diagnostics'];decisions=r['decisions']
        if d['five_category_route_fraction']<.33:reasons.append('weak_projected_five_category_route')
        if d['blocked_games']>12:reasons.append('high_position_congestion')
        if d['five_category_route_fraction']-d['risk1_route_fraction']>.25:reasons.append('availability_discount_sensitive')
        if any(x['seconds']>35 for x in decisions):reasons.append('recommendation_latency_over_35s')
        if any(x['market_rank_remaining']>20 and (x['survival_if_passed_estimate'] or 0)>=.6 for x in decisions):reasons.append('large_reach_with_model_plausible_wait')
        # Label switches are descriptive only, not counted as a failure.
        switches=sum(a['evaluated_punts']!=b['evaluated_punts'] for a,b in zip(decisions,decisions[1:]))
        for reason in reasons:
            failure_map.setdefault((r['task']['stage'],r['task']['model'],reason),[]).append(
                {'source_index':r['task']['index'],'trace':r['path'],'temporary_build_switches':switches})
    failures=[{'stage':s,'model':m,'signal':f,'paths':len(rs),'examples':rs[:3],
               'interpretation':'Reproducible diagnostic signal for review, not automatic proof of a defect.'}
              for (s,m,f),rs in sorted(failure_map.items(),key=lambda x:-len(x[1]))]
    ops=json.loads((run/'operational.json').read_text()) if (run/'operational.json').exists() else {'passed':False,'pending':True}
    primary=[grouped.get('primary/'+m,{}) for m in manifest['config']['primary_models']]
    enough=all(g.get('production',{}).get('paths',0)>=20 for g in primary)
    bad=all(g.get('production',{}).get('weak_route_frequency',0)>.5 for g in primary) and enough
    tails_ok=enough and all(g['production']['weak_route_frequency']<=.25 and
        g['production']['quality']['five_category_route_fraction']['median']>=g['fit']['quality']['five_category_route_fraction']['median']-.1 for g in primary)
    competitive=enough and all(
        g['production']['outcomes']['title']['mean']>=g['fit']['outcomes']['title']['mean']-.10 and
        g['production']['outcomes']['qualified']['mean']>=g['fit']['outcomes']['qualified']['mean']-.10 and
        g['production']['outcomes']['advancement']['mean']>=g['fit']['outcomes']['advancement']['mean']-.35
        for g in primary)
    lat_ok=all(not v['over_35'] for v in latency.values())
    if status['state']=='failed' or bad:
        verdict='3. Not yet dependable enough'
    elif status['state']=='complete' and lane=='main' and ops.get('passed') and tails_ok and competitive and lat_ok:
        verdict='1. Ready to use as my default decision-maker'
    else:verdict='2. Useful, but requires specific fixes or guardrails'
    if lane=='pilot' or status['state'] not in ('complete','failed'):
        verdict='Pending — evaluation incomplete; no draft-policy reliability verdict yet'
    production_decisions=[d for r in rows if r['task']['policy']=='production' for d in r['decisions']]
    report={'format':'full-policy-audit-v1','lane':lane,'status':status['state'],'assessment':verdict,
        'manifest_hash':hashed(manifest),'source_hashes':manifest['hashes'],
        'comparisons':pairs,'per_model_policy_summary':grouped,'latency':latency,
        'backend_featured_divergences':sum(d['backend_first']!=d['selected'] for d in production_decisions),
        'operational':ops,'examples':examples,'failure_signals':failures,
        'assessment_basis':{'minimum_coverage_met':enough,'projected_downside_and_fit_comparison_pass':tails_ok,
            'observed_competitive_performance_guardrail_pass':competitive,'latency_guardrail_pass':lat_ok,
            'competitive_guardrails':{'title_frequency_deficit_vs_fit':.10,'qualification_frequency_deficit_vs_fit':.10,'advancement_deficit_vs_fit':.35},
            'note':'Coverage floor is a practical gate, not statistical proof. Classification uses pre-registered roster/operational heuristics and practical season-performance deficits versus fit in each primary model. Passing these observational guardrails does NOT establish equivalence/noninferiority; all paired intervals remain visible. Model uncertainty remains.'},
        'limitations':['Two primary opponent models share the fitted pooled baseline; agreement is not independent validation.',
            'Synthetic injury/performance/waiver assumptions do not provide calibrated championship odds.',
            'Projection GP, NBA teams, daily schedule and provisional Yahoo eligibility are frozen; update checks remain necessary before draft day.',
            'Sensitivity/adverse cases are separate, never pooled into primary evidence.',
            'Changing a punt label alone is not a failure; roster construction and downside are evaluated independently.',
            'Playbook #6 prose was not a fully specified automatic policy; the exact provisional chain used by D is frozen in the manifest.']}
    atomic(run/lane/'RESULTS.json',report)
    lines=['# Can I follow the tool for every pick?', '',f'**{verdict}**',f'Status: {status["state"]}; lane: {lane}.', '',
        '## What this comparison means',
        'A follows the live UI’s first featured recommendation for every owned pick. B takes best available market ADP. C is the shared ADP + category-fit/position-coverage baseline. D follows the frozen provisional #6/#43/#54 rules, then A. All use identical season-management assumptions and paired source paths/worlds.',
        'Actual picks: #6, #43, #54, #67, #78, #91, #102, #115, #126, #150. Keepers: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George.', '',
        '## Per-model results (never pooled)',
        '| Stage/model | Policy | Independent paths | Title frequency | Playoff frequency | Advancement | Weak-route frequency |',
        '|---|---|---:|---:|---:|---:|---:|']
    for group,ps in grouped.items():
        for p,s in ps.items():
            if s['paths']:
                o=s['outcomes'];lines.append(f"| {group} | {p} | {s['paths']} | {o['title']['mean']:.1%} | {o['qualified']['mean']:.1%} | {o['advancement']['mean']:.2f} | {s['weak_route_frequency']:.1%} |")
    lines+=['','Frequencies are model-conditional, not calibrated championship probabilities. A complete path contains all four policies; policy repetitions and season worlds do not add independent draft situations.', '',
        '## Paired differences: production minus each alternative',
        '| Stage/model | Alternative | Paired paths | Δ title | Pointwise 95% draft-cluster interval |',
        '|---|---|---:|---:|---|']
    for group,comparisons in pairs.items():
        for p in comparisons:
            if p['a']!='production':continue
            m=p['metrics']['title']
            if not m['paths']:continue
            iv=m['pointwise_cluster_bootstrap_95'];span='too few paths' if iv is None else f'[{100*iv[0]:+.1f}, {100*iv[1]:+.1f}] pp'
            lines.append(f"| {group} | {p['b']} | {m['paths']} | {100*m['difference']:+.1f} pp | {span} |")
    lines+=['','Pointwise bootstrap intervals are descriptive and unstable with few paths. JSON includes conservative simultaneous bounded intervals, qualification and advancement comparisons. No-significant-difference is not equivalence/noninferiority.', '',
        '## Latency and draft-night operation','```json',json.dumps(latency,indent=2),'```',
        'Backend versus displayed-featured differences: '+str(report['backend_featured_divergences'])+'.',
        'Use only a fresh result for the current session/revision and the Record button naming the current pick. If stale near the clock limit, use the entry panel’s first available market-ADP player after verifying the current owner. No season simulation is needed on draft day.', '',
        '## Recurring signals / targeted follow-up']
    if failures:
        for f in failures[:6]:lines.append(f"- {f['stage']}/{f['model']}: {f['signal']} on {f['paths']} paths. Trace: `{f['examples'][0]['trace']}`. Review alternatives/market wait and completed-roster context before changing the engine.")
    else:lines.append('- No registered diagnostic signals observed in completed production paths so far; this is not proof no failure exists.')
    lines+=['','Do not retune on this evaluation. If a consequential failure is reproduced, apply a targeted fix in a new snapshot and validate on a new seed namespace. Additional drafting-policy optimization is not a prerequisite for using a sound, operationally reliable default.', '',
        '## Representative drafts',
        'See `EXAMPLES.md`: strong, typical and weak examples selected by projected roster construction, never only by unlucky championship losses.', '',
        '## Limits',*['- '+s for s in report['limitations']], '',
        'Complete provenance: `../manifest.json`; frozen original playbook under `../source/`. Full decision traces and atomic checkpoints are under `tasks/`; structured results in `RESULTS.json`.']
    (run/lane/'CAN_I_FOLLOW_THE_TOOL.md').write_text('\n'.join(lines)+'\n')
    ex=['# Representative completed drafts','', 'Selected independently of championship outcomes. Category edges are projected, not simulated frequencies.']
    for e in examples:
        d=e['diagnostics'];strong=[c for c,v in d['category_edges'].items() if v>.65];weak=[c for c,v in d['category_edges'].items() if v<.35]
        ex += ['',f"## {e['stage']}/{e['model']} · {e['policy']} · {e['label']} · path {e['source_index']}",
            ', '.join(e['roster']),f"Five-category route fraction {d['five_category_route_fraction']:.2f}; fifth-category edge {d['fifth_category_edge']:.2f}; usable starts {d['usable_starts']:.1f}; blocked {d['blocked_games']:.1f}.",
            'Strengths: '+(', '.join(strong) or 'none over 65%')+'. Weaknesses: '+(', '.join(weak) or 'none below 35%')+'.',
            e['explanation'],f"Trace: `{e['source_file']}`."]
    (run/lane/'EXAMPLES.md').write_text('\n'.join(ex)+'\n')
    return report
