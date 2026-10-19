"""Checkpoint/final publications for the isolated first-three-pick experiment."""
import itertools
import json
import math
import random
import statistics as st
from collections import Counter
from pathlib import Path

from overnight_core import atomic, context, digest, MAIN, MODELS, seed


def mean(xs):
    xs = list(xs)
    return st.mean(xs) if xs else None


def paired(rows, a, b, multiplicity=1):
    aa = {(r['task']['phase'], r['task']['index']): r for r in rows if key(r) == a}
    bb = {(r['task']['phase'], r['task']['index']): r for r in rows if key(r) == b}
    common = sorted(set(aa) & set(bb)); diffs = []
    for k in common:
        av = {x['seed']: x['title'] for x in aa[k]['outcomes']}
        bv = {x['seed']: x['title'] for x in bb[k]['outcomes']}
        worlds = sorted(set(av) & set(bv))
        if worlds:
            diffs.append(mean(av[s]-bv[s] for s in worlds))
    n = len(diffs)
    if not n:
        return {'paths': 0, 'difference': None}
    mu = mean(diffs); interval = None
    if n >= 3:
        rng = random.Random(seed('report-bootstrap', a, b))
        boot = sorted(mean(rng.choices(diffs, k=n)) for _ in range(2000))
        interval = [boot[49], boot[1949]]
    # Independent source paths; bounded paired differences in [-1,1]. Remains
    # nondegenerate for zero observed championships and controls the reported family.
    radius = math.sqrt(2 * math.log(2 * max(1, multiplicity) / .05) / n)
    simultaneous = [max(-1, mu-radius), min(1, mu+radius)]
    equivalent = simultaneous[0] >= -.05 and simultaneous[1] <= .05
    return {'paths': n, 'difference': mu, 'pointwise_cluster_bootstrap_95': interval,
            'simultaneous_bounded_95': simultaneous, 'family_comparisons': multiplicity,
            'equivalent_within_5_points': equivalent,
            'interpretation': 'equivalence established' if equivalent else 'unresolved' if simultaneous[0] <= 0 <= simultaneous[1] else 'direction separated under model'}


def key(r):
    t = r['task']
    return t['first'] + '/' + (t.get('policy') or {}).get('id', 'production')


def summarize(rows):
    if not rows:
        return {'paths': 0, 'seasons': 0}
    di = [r['diagnostics'] for r in rows]
    cats = list(di[0]['category_edges'])
    pick_counts = {}
    for r in rows:
        for t in r['draft']['trace']:
            if t['team'] == 'Oscar':
                pick_counts.setdefault(str(t['slot']), Counter())[t['player_id']] += 1
    return {'paths': len(rows), 'seasons': sum(len(r['outcomes']) for r in rows),
            'championship_frequency': mean(mean(x['title'] for x in r['outcomes']) for r in rows),
            'qualification_frequency': mean(mean(x['qualified'] for x in r['outcomes']) for r in rows),
            'advancement': mean(mean(x['advancement'] for x in r['outcomes']) for r in rows),
            'category_edges': {c: mean(d['category_edges'][c] for d in di) for c in cats},
            'weakness_frequency': {c: mean(c in d['weaknesses'] for d in di) for c in cats},
            'strength_frequency': {c: mean(c in d['strengths'] for d in di) for c in cats},
            'usable_starts_mean': mean(d['usable_starts'] for d in di),
            'blocked_games_mean': mean(d['blocked_games'] for d in di),
            'c_only_count_mean': mean(len(d['c_only']) for d in di),
            'temporary_build_counts': dict(Counter(','.join(d['temporary_last_engine_build']) or 'no evaluated punt' for d in di)),
            'pick_counts': {s: dict(c.most_common()) for s, c in pick_counts.items()}}


def survival(rows, pid):
    passed = [r for r in rows if len(r['decisions']) == 2 and pid in r['decisions'][0]['available']
              and r['decisions'][0]['selected'] != pid]
    # A path can have multiple policies; don't turn policies into independent paths.
    by = {}
    for r in passed:
        t = r['task']; k = (t['phase'], t['index'])
        by.setdefault(k, []).append(int(pid in r['decisions'][1]['available']))
    return {'paths_where_passed': len(by), 'survival_fraction': mean(mean(v) for v in by.values()),
            'note': 'Conditional on being available and passed at #43; differing policies within a path averaged, paths counted once.'}


def publish(run, status, selected=None):
    data, engine, inputs, config, base = context()
    names = {p['id']: p['name'] for p in data.players.values()}
    manifest = json.loads((run/'manifest.json').read_text()) if (run/'manifest.json').exists() else {}
    setting = json.loads((run/'run.json').read_text())
    policies = json.loads((run/'policies.json').read_text()) if (run/'policies.json').exists() else {}
    if selected is None:
        selected = json.loads((run/'frozen_finalists.json').read_text()) if (run/'frozen_finalists.json').exists() else {}
    rows = []
    for p in sorted((run/'results').glob('*.json')):
        if p.name.endswith('.checkpoint.json'):
            continue
        r = json.loads(p.read_text())
        if r.get('state') == 'complete' and 'outcomes' in r:
            rows.append(r)
    natural = [r for r in rows if not r['task'].get('stress')]
    stages = {}
    for phase in sorted({r['task']['phase'] for r in natural}):
        stages[phase] = {}
        for model in MODELS:
            rr = [r for r in natural if r['task']['phase'] == phase and r['task']['model'] == model]
            stages[phase][model] = {k: summarize([r for r in rr if key(r) == k]) for k in sorted({key(r) for r in rr})}
    comparisons = {}
    for model in MODELS:
        rr = [r for r in natural if r['task']['model'] == model and r['task']['phase'] == 'confirm']
        selected_keys = [pid+'/'+v['chosen'] for pid, v in selected.get('branches', {}).items()]
        family = max(1, len(list(itertools.combinations(selected_keys, 2))) + 2*len(selected_keys))
        pairs = []
        for a, b in itertools.combinations(selected_keys, 2):
            pairs.append({'a': a, 'b': b, **paired(rr, a, b, family)})
        for pid, v in selected.get('branches', {}).items():
            a = pid+'/'+v['chosen']
            for alt in ['simple', 'production']:
                if a != pid+'/'+alt:
                    pairs.append({'a': a, 'b': pid+'/'+alt, **paired(rr, a, pid+'/'+alt, family)})
        comparisons[model] = pairs
    branches = {}
    chosen6 = next((p['id'] for p in data.players.values() if p['name'] == MAIN[0]), None)
    for pid, allp in policies.items():
        selected_id = selected.get('branches', {}).get(pid, {}).get('chosen', 'conditional')
        policy = next((p for p in allp if p['id'] == selected_id), allp[0])
        evidence = {}
        for model in MODELS:
            rr = [r for r in natural if r['task']['model'] == model and r['task']['first'] == pid
                  and (r['task'].get('policy') or {}).get('id') == policy['id']]
            evidence[model] = {phase: summarize([r for r in rr if r['task']['phase'] == phase]) for phase in ['screen','deep','confirm']}
            evidence[model]['wait_survival'] = {p: survival(rr, p) for p in policy['rank43'][:5]}
        tested43 = Counter(); tested_pairs = Counter(); fallback_count = 0
        for r in natural:
            if r['task']['first'] != pid or (r['task'].get('policy') or {}).get('id') != policy['id']:
                continue
            ds = r['decisions']
            if len(ds) == 2:
                tested43[ds[0]['selected']] += 1
                tested_pairs[ds[0]['selected']+'|'+ds[1]['selected']] += 1
                fallback_count += not any(x in ds[0]['available'] for x in policy['rank43'])
        branches[pid] = {'name': names[pid], 'first_pick': 6, 'first_pick_condition': {'available_id': pid},
                         'deep_finalist': pid in selected.get('branches', {}),
                         'policy': policy, 'evidence': evidence,
                         'observable_rules': 'At #43 take first available rank43 ID. At #54 use rank54[actual #43 ID], else default54. Always filter keeper and taken IDs. If all ranked targets gone use fallback.',
                         'when_multiple_available': 'Use the first listed available player; differences within the shortlist remain unresolved unless confirmation intervals separate them.',
                         'when_top_two_gone': 'Continue from rank 3, then the precomputed fallback; never reserve a player against opponents.',
                         'coverage': {'selected43_counts': dict(tested43), 'selected_pair_counts': dict(tested_pairs),
                                      'fallback_invocations': fallback_count,
                                      'counts_note': 'Completions, not necessarily independent paths; independent counts reported by phase/model above.'},
                         'outside_coverage': {'certainty': 'lower', 'rule': 'first available precomputed fallback ID; static projection/position fit, not established season superiority'}}
    report = {'format': 'first-three-playbook-v1', 'status': status, 'provisional_first': chosen6,
              'first_choice_basis': 'KAT retained as provisional prior fit/value tie-breaker unless fresh paired evidence establishes a change; no uniquely optimal trio claimed.',
              'pick_numbers': [6,43,54], 'later_picks': [67,78,91,102,115,126,150],
              'source_hashes': manifest.get('hashes', {}), 'manifest_hash': digest(manifest),
              'keepers': [{k: p[k] for k in ('id','name','positions')} for p in engine.rosters(base)['Oscar']],
              'players': {pid: {'name': p['name'], 'positions': p['positions'], 'market_adp': p['market_adp'],
                               'playoff_games': data.weekly[p['team']]} for pid, p in data.players.items()},
              'branches': branches, 'stages': stages, 'confirmation_comparisons': comparisons,
              'stress_cases': [{'first': r['task']['first'], 'model': r['task']['model'], 'stress': r['task']['stress'],
                                'policy': r['task']['policy']['id'], 'interventions': r.get('stress_interventions'),
                                'summary': summarize([r])} for r in rows if r['task'].get('stress')],
              'assumptions': config['assumptions'],
              'uncertainty': 'Independent source-draft path is the cluster. Worlds paired across policies, distinct across paths. Bootstrap intervals pointwise; bounded simultaneous intervals protect reported comparison family. ±5 percentage-point equivalence requires entire simultaneous interval inside margin. No calibrated odds. Selection on screening/deep data is biased; confirmation is separate.',
              'limitations': ['Opponent models share a fitted pooled baseline; agreement is not independent validation.',
                              'Same-round keeper-cost rule remains unverified; source ownership reconciled.',
                              'Hashtag positions are provisional Yahoo eligibility; injury/role projections are a fixed snapshot.',
                              'Availability is conditional on modeled opponents and keepers, not calibrated live probabilities.',
                              'Small conditional subgroups and boards outside support require the lower-certainty fallback.',
                              'The full-board production policy is a diagnostic comparator, not draft-day simulation advice.']}
    availability_path = run/'first_screen.json'
    if availability_path.exists():
        report['first_pick_screen'] = json.loads(availability_path.read_text())
        report['contingency_branches'] = {}
        keepers = engine.rosters(base)['Oscar']
        for c in report['first_pick_screen'].get('contingencies', []):
            pid = c['id']; early = keepers + [data.players[pid]]
            pool = [p for p in data.players.values() if not p['keeper'] and p['id'] != pid]
            ranked = [p['id'] for p in sorted(pool, key=lambda p:engine.value(p,(),.5)+engine.need_bonus(early,p), reverse=True)]
            rank54 = {x:[p['id'] for p in sorted([p for p in pool if p['id'] != x],
                       key=lambda p:engine.value(p,(),.5)+engine.need_bonus(early+[data.players[x]],p), reverse=True)]
                       for x in ranked[:10]}
            report['contingency_branches'][pid] = {'name': c['name'], 'certainty':'lower; no joint season confirmation',
                'rank43':ranked, 'rank54':rank54, 'default54':ranked, 'fallback':ranked,
                'rule':'First available ID only. Static keeper/position-fit and value fallback, not estimated optimal policy.',
                'availability_at6':c['availability_at6']}
    overlap = {}
    for phase in ['screen','deep','confirm']:
        by = {(r['task']['model'],key(r),r['task']['index']):r for r in natural if r['task']['phase']==phase}
        comparisons_same = []
        for (model,k,i),r in by.items():
            other = by.get(('validated',k,i))
            if model == 'adp_stochastic' and other:
                comparisons_same.append(r['draft']['rosters'] == other['draft']['rosters'])
        overlap[phase] = {'paired_completions':len(comparisons_same), 'identical_roster_fraction':mean(comparisons_same)}
    report['opponent_model_overlap'] = overlap
    atomic(run/'FIRST_THREE_PICKS_PLAYBOOK.json', report)
    def label(ids, n=6):
        return ' → '.join(names.get(p,p) for p in ids[:n])
    lines = ['# First three picks — precomputed playbook', '', f'**Status: {status}.**', '',
             '## 1. Provisional #6 choice', '',
             '**Karl-Anthony Towns**, with **Evan Mobley** and **Alperen Şengün** as main alternatives. This is a provisional fit/value tie-breaker, not a uniquely optimal pick or established championship advantage.',
             'Your keepers: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George.',
             'Your next picks after #54: **#67, #78, #91, #102, #115, #126, #150**.', '',
             '## 2. #43 / #54 decision trees', '',
             'Read every arrow as **first player still available**. Never assume a #54 target survives. If multiple targets remain, take the earlier name; if the top two disappear, start at the third. Do not force a punt from a recommendation label.', '']
    if not branches:
        lines += ['Candidate discovery is running. No new conditional rules published yet.']
    for pid, b in branches.items():
        p = b['policy']; prefix_label = 'Main/deep branch' if b['deep_finalist'] else 'Screened / lower-certainty branch'
        lines += [f"### {b['name']} at #6 — {prefix_label}", '', f"**#43:** {label(p['rank43'])}.", '']
        shown = p['rank43'][:5]
        for taken in shown:
            r54 = p['rank54'].get(taken, p['default54'])
            lines.append(f"- If #43 is **{names[taken]}**: #54 **{label(r54, 5)}**.")
        lines += [f"- Other #43 choice: #54 **{label(p['default54'], 6)}**.",
                  f"- Listed targets exhausted: lower-certainty fallback **{label(p['fallback'], 8)}** (skip already taken/keepers).", '']
        e = b['evidence']['adp_stochastic']; phase = next((x for x in ['confirm','deep','screen'] if e[x]['paths']), None)
        if phase:
            d = e[phase]
            strong = [c for c, v in d['strength_frequency'].items() if v >= .6]
            weak = [c for c, v in d['weakness_frequency'].items() if v >= .6]
            close = [c for c, v in d['category_edges'].items() if .35 <= v <= .65]
            lines += [f"Completed-roster direction ({phase}, ADP model, {d['paths']} paths): recurring strengths **{', '.join(strong) or 'not consistent enough to name'}**; recurring weaknesses **{', '.join(weak) or 'not consistent enough to name'}**. Close projected categories: {', '.join(close) or 'none by 35–65% heuristic'}.",
                      f"Playoff starts: {d['usable_starts_mean']:.1f} mean usable; {d['blocked_games_mean']:.1f} blocked games. C-only players: {d['c_only_count_mean']:.1f} mean; multi-position bigs retain F/PF/C flexibility. Extra bigs may depend on UTIL; there is no center cap.",
                      f"Later picks should revisit {', '.join(weak+close[:2]) or 'the weakest remaining categories'} while preserving daily starts. Weaknesses are diagnostic, not a command to repair every weak category or abandon a strong five-category route."]
            for s in ['67','78']:
                counts = d['pick_counts'].get(s, {})
                if counts:
                    lines.append(f"Observed later #{s} completions (not promised availability): " + ', '.join(f'{names[x]} ({n})' for x,n in list(counts.items())[:4]) + '.')
        lines.append('')
    contingencies = report.get('first_pick_screen', {}).get('contingencies', [])
    if contingencies:
        lines += ['### Unexpected elite fallers — separate contingency', '',
                  'These are not ordinary #43/#54 targets and were not allocated equal deep-search time. A faller changes the roster; do not claim the main-branch evidence applies unchanged. The ordering below is a lower-certainty neutral-value contingency, not a season-confirmed ranking. Full availability-filtered #43/#54 fallback lists for each faller are in the JSON.']
        for c in sorted(contingencies, key=lambda c:c['value'], reverse=True):
            a = c['availability_at6']['adp_stochastic']
            lines.append(f"- {c['name']}: modeled availability at #6 {a['available']}/{a['paths']} natural first-five paths; this is not calibrated live availability.")
        lines.append('')
    lines += ['## 3. Supported versus unresolved', '',
              'Supported mechanically: legal 13-player completions, actual pick ownership, daily position eligibility and congestion, availability-filtered rules, and unchanged production continuation after #54.',
              'Statistical superiority and practical equivalence remain unresolved unless the simultaneous paired interval establishes them. A zero-spanning interval is **not equivalence**. The apparent screening winner is selection-biased.', '',
              '## 4. Fresh confirmation and coverage', '',
              '| Model | A − B | Paired paths | Δ championship | Pointwise 95% cluster interval |',
              '|---|---|---:|---:|---|']
    for model, pairs in comparisons.items():
        for p in pairs:
            if not p['paths']:
                continue
            iv = p.get('pointwise_cluster_bootstrap_95')
            fmt = lambda k: names.get(k.split('/')[0], k) + ' / ' + k.split('/')[1]
            span = 'insufficient paths' if iv is None else f'[{100*iv[0]:+.1f}, {100*iv[1]:+.1f}] pp'
            lines.append(f"| {model} | {fmt(p['a'])} − {fmt(p['b'])} | {p['paths']} | {100*p['difference']:+.1f} pp | {span} |")
    lines += ['', 'These are model-conditional diagnostic frequencies, not calibrated championship odds. See JSON/report for conservative simultaneous intervals, per-model counts, and the cost of simple rules versus full-board production decisions. New confirmation indices generate both new draft completions and new season worlds.',
              'Naturally sampled availability and deliberately adverse boards are stored separately. Conditional branches with few or no visits are less certain. Agreement between similar opponent models is weak evidence of robustness.', '',
              '## 5. Most valuable remaining analysis', '',
              'More fresh independent paths for under-visited #43/#54 branches and the simple-policy versus full-board comparison; updated injury/role information and verified Yahoo eligibility before draft day. Do not spend the next budget merely replaying injuries on the same drafted rosters.', '',
              'Full ranked lists, player IDs, availability tests, completed-roster diagnostics, hashes and evidence counts: `FIRST_THREE_PICKS_PLAYBOOK.json`.']
    (run/'FIRST_THREE_PICKS_PLAYBOOK.md').write_text('\n'.join(lines)+'\n')
    method = ['# First-three-pick methodology and results', '', f'Status: {status}', '',
              '## Frozen experiment', json.dumps({k:v for k,v in manifest.items() if k!='hashes'}, indent=2), '',
              '## Design',
              '1. Screen the current eligible pool using unpruned production recommendations, supplied ADP, neutral category value, and keeper-aware natural first-five draws. Elite fallers are separate contingencies.',
              '2. Discover #43/#54 pools from production top-15, category-neutral value, market value, and stocks/shooting/big/creation directions on varied legal paths. Vary #43 before observing #54.',
              '3. Compile deterministic availability-only policies from ADP-primary discovery. Compare simple, conditional, wait, direction and full-board production policies. No averaging models to select a winner.',
              '4. Use paired draft randomness and shared season seeds. Each source index has distinct draft and season seeds. Conditional first-pick comparisons use only overlapping available-first-pick paths. Unavailable candidates are skipped, never protected from opponents.',
              '5. Retain the three requested branches plus strategically distinct exploratory alternatives. Freeze chosen rules before confirmation. Confirm on a disjoint seed phase including new drafts, with a simple policy and full-board comparator where time permits.',
              '6. Stress tests replace two opponent selections on an otherwise legal partial board. Displaced players return to the pool. These deliberately constructed cases are never counted as natural availability.', '',
              '## Season management / objective',
              'Championship is primary; qualification and advancement are diagnostics. Oscar uses aggressive streaming; opponents use the same fixed observed-activity assumptions for every compared draft policy. Daily lineups use projection-based position-constrained selection and the production continuation build; no future health/box-score access. Four acquisitions/period, three IL slots, placement eligibility, default FAB/waivers. Final diagnostic category comparisons use recorded completed rosters with no imposed punt; temporary last evaluated build is retained separately.',
              json.dumps(config['assumptions'], indent=2), '',
              '## Uncertainty / multiplicity', report['uncertainty'],
              'The bounded simultaneous interval uses Hoeffding on per-path paired differences in [-1,1], with a Bonferroni family size. It is deliberately conservative, finite-sample, and nondegenerate when no championships occur. Bootstrap intervals are descriptive pointwise intervals and can be unstable with few paths. Neither quantifies model misspecification. Availability-conditioning limits cross-first-pick comparability.', '',
              '## Actual counts and stage results', '```json', json.dumps(stages, indent=1), '```', '',
              '## Confirmation paired differences', '```json', json.dumps(comparisons, indent=1), '```', '',
              '## Stress cases (never pooled with sampled boards)', '```json', json.dumps(report['stress_cases'], indent=1), '```', '',
              '## Limitations', *['- '+s for s in report['limitations']], '',
              '## Reproduction', f'Frozen source and all checkpoints: `{run}`. See `progress.json`, `progress.log`, `allocation.json`, `frozen_finalists.json`, `manifest.json`, and one resumable record per task in `results/`. Resume with the exact frozen scripts; a hash mismatch refuses to run.']
    (run/'FIRST_THREE_PICKS_RESULTS.md').write_text('\n'.join(method)+'\n')
    dest = Path(setting['publication_root'])
    for name in ['FIRST_THREE_PICKS_PLAYBOOK.md','FIRST_THREE_PICKS_PLAYBOOK.json','FIRST_THREE_PICKS_RESULTS.md']:
        src = run/name
        temp = dest/(name+'.tmp'); temp.write_bytes(src.read_bytes()); temp.replace(dest/name)
    return report
