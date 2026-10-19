#!/usr/bin/env python3
"""Pick #6 decision lab — reuses the production engine end to end.

For each realistic #6 candidate: force it as our pick, complete the rest of the draft
with the production `live` engine, and score paired championship outcomes on shared
season worlds. Broad pass first, then a deeper pass on the strongest candidates.

Additive only: never writes to the live store, never touches the held-out evaluation
seed block (uses the `production_lab` namespace).

    python3 scripts/run_pick6_lab.py --broad-drafts 2 --deep-top 6 --deep-drafts 3 --deep-models 2
"""
import argparse
import copy
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import seeds
from app.data import CATEGORIES, Data
from app.decision import DecisionBenchmark, cluster_bootstrap
from app.engine import Engine
from app.market import market_key
from app.season_draft import SeasonDraft
from app.store import Store
from app.season_inputs import SeasonInputs

HYPOTHESIS = {'name': 'Confirmed ownership 2026-10-12 (106 Raul / 113 Samet / 123 Nick)',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
LIVE = {'name': 'live', 'policy': 'live', 'punts': [], 'streaming': 'aggressive'}


def board_at_pick6(data, base, assumed_gone):
    st = copy.deepcopy(base)
    st['settings'] = dict(st.get('settings') or {})
    st['settings'].pop('draft_scenarios', None)
    slots = [s for s in st['slots'] if not s['keeper'] and not s['player_id']]
    pool = sorted([p for p in data.players.values() if not p['keeper'] and p['id'] not in st['drafted']], key=market_key)
    me = data.config['team_name']
    my_slot = next(s['slot'] for s in slots if s['current_team'] == me)
    taken = [s for s in slots if s['slot'] < my_slot]
    gone = pool[:min(assumed_gone, len(taken))]
    for s, p in zip(taken, gone):
        s['player_id'] = p['id']; s['player_name'] = p['name']
    st['drafted'] = [s['player_id'] for s in st['slots'] if s['player_id']]
    st['current_slot'] = my_slot
    # Filter against the UPDATED drafted set so assumed-gone elites are not offered as
    # forceable candidates (forcing an unavailable player now raises by design).
    remaining = sorted([p for p in data.players.values() if not p['keeper'] and p['id'] not in st['drafted']], key=market_key)
    return st, gone, remaining


def category_report(engine, roster):
    z = [sum(engine.z[p][j] for p in roster if p in engine.z) for j in range(9)]
    order = sorted(range(9), key=lambda j: z[j], reverse=True)
    return {'z_per_category': {CATEGORIES[j]: round(z[j], 1) for j in range(9)},
            'strengths': [CATEGORIES[j] for j in order[:3]],
            'weaknesses': [CATEGORIES[j] for j in order[-3:]]}


def evaluate(bench, state, candidates, drafts, seasons, models, salt, block, holdout, offset=0):
    """PER-MODEL, per-draft evaluation with DISTINCT season worlds per draft.

    Returns one block per opponent model: per-candidate championship/advancement rates
    and PAIRED differences vs the reference candidate (the first), clustered by draft.
    No cross-model pooling: models are reported separately.
    """
    ref = candidates[0]
    per_model = []
    for mi, model in enumerate(models):
        bench.opponent_mode = model
        entries = []
        for d in range(drafts):
            seed = seeds.draft_seed(salt, block, holdout, d) + offset   # same replicate seed across models
            entries.append({'draft': d, 'out': bench.evaluate_candidates(state, candidates, seed, seasons=seasons)})
        rate = {c: statistics.mean(t for e in entries for t in e['out'][c]['titles']) for c in candidates}
        adv = {c: statistics.mean(a for e in entries for a in e['out'][c]['advancements']) for c in candidates}
        pairs = []
        for c in candidates[1:]:
            by = {e['draft']: [x - y for x, y in zip(e['out'][ref]['titles'], e['out'][c]['titles'])] for e in entries}
            pairs.append({'ref': ref, 'cand': c, 'gap': statistics.mean(v for b in by.values() for v in b),
                          'interval': cluster_bootstrap(by, 7)})
        per_model.append({'model': model, 'rate': rate, 'adv': adv, 'pairs': pairs,
                          'roster': {c: entries[0]['out'][c]['roster'] for c in candidates},
                          'punt': {c: entries[0]['out'][c]['punt'] for c in candidates}})
    return per_model


def pooled_rate(per_model):
    """Mean championship rate across models (for shortlist ranking only)."""
    ids = list(per_model[0]['rate'])
    return {c: statistics.mean(m['rate'][c] for m in per_model) for c in ids}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--broad', type=int, default=12)
    ap.add_argument('--include', default='', help='comma-separated candidate names forced into the deep set (e.g. KAT, Sengün)')
    ap.add_argument('--contingency', type=int, default=5)
    ap.add_argument('--assumed-gone', type=int, default=5)
    ap.add_argument('--broad-drafts', type=int, default=2)
    ap.add_argument('--broad-seasons', type=int, default=2)
    ap.add_argument('--deep-top', type=int, default=6)
    ap.add_argument('--deep-drafts', type=int, default=3)
    ap.add_argument('--deep-seasons', type=int, default=4)
    ap.add_argument('--models', default='adp_stochastic,validated')
    ap.add_argument('--opponent', default='adp_stochastic')
    ap.add_argument('--season-seed-salt', type=int, default=20261018)
    ap.add_argument('--out', default='local/pick6_lab.json')
    ap.add_argument('--report', default='PICK6_SHORTLIST.md')
    args = ap.parse_args()

    t0 = time.perf_counter()
    data = Data(); engine = Engine(data); inputs = SeasonInputs(data)
    store = Store(':memory:', data)
    config, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1,
                                                    'seasons_per_draft': args.deep_seasons,
                                                    'seed_block': 'production_lab', 'holdout': 1})
    base = states[0]
    state, gone, pool = board_at_pick6(data, base, args.assumed_gone)
    keepers = [p['id'] for p in data.players.values() if p['keeper'] == data.config['team_name']]

    by_name = {p['name']: p for p in data.players.values()}
    rec = engine.recommend(state)
    engine_top = [r['player']['id'] for r in (rec.get('recommendations') or [])][:args.broad]
    contingency = [p['id'] for p in pool[:args.contingency]]
    requested = list(dict.fromkeys(engine_top + contingency))
    include = []
    for n in [x.strip() for x in args.include.split(',') if x.strip()]:
        if n not in by_name:raise SystemExit('unknown --include name: '+n)
        include.append(by_name[n]['id']);requested.append(by_name[n]['id'])
    pool_ids = {p['id'] for p in pool}
    candidates = [c for c in dict.fromkeys(requested) if c in pool_ids]
    unavailable = [c for c in dict.fromkeys(requested) if c not in pool_ids]
    print('pool %d | candidates %d | excluded (assumed gone): %s' % (
        len(pool), len(candidates), [data.players[c]['name'] for c in unavailable]))

    bench = DecisionBenchmark(engine, inputs, config, LIVE, args.opponent, continuation=LIVE, candidates=2)
    broad = evaluate(bench, state, candidates, args.broad_drafts, args.broad_seasons, [args.opponent],
                     args.season_seed_salt, 'production_lab', 1, offset=0)
    ranked = sorted(candidates, key=lambda c: pooled_rate(broad)[c], reverse=True)
    deep_ids = list(dict.fromkeys(ranked[:args.deep_top] + include))   # explicit candidates always included
    print('broad done in %.1f min; deep on %s' % ((time.perf_counter() - t0) / 60, [data.players[c]['name'] for c in deep_ids]))
    models = args.models.split(',')
    deep = evaluate(bench, state, deep_ids, args.deep_drafts, args.deep_seasons, models,
                    args.season_seed_salt, 'production_lab', 1, offset=50_000)

    order = sorted(deep_ids, key=lambda c: pooled_rate(deep)[c], reverse=True)
    report = {'assumed_gone': [data.players[p['id']]['name'] for p in gone],
              'keepers': [data.players[p]['name'] for p in keepers],
              'excluded_unavailable': [data.players[c]['name'] for c in unavailable],
              'generated_at': time.strftime('%Y-%m-%d %H:%M'), 'seed_block': 'production_lab', 'holdout': 1,
              'models': models, 'deep': [], 'paired': [], 'broad': {data.players[c]['name']: pooled_rate(broad)[c] for c in candidates}}
    for block in deep:
        report['deep'].append({'model': block['model'], 'rows': [{
            'name': data.players[c]['name'], 'adp': data.players[c]['market_adp'],
            'title_rate': block['rate'][c], 'advancement': block['adv'][c], 'punt': block['punt'][c],
            'category': category_report(engine, block['roster'][c]),
            'roster': [data.players[p]['name'] for p in block['roster'][c]]} for c in order]})
        if block['pairs']:
            report['paired'].append({'model': block['model'], 'ref': data.players[block['pairs'][0]['ref']]['name'],
                'rows': [{'cand': data.players[p['cand']]['name'], 'gap': p['gap'], 'interval': p['interval']} for p in block['pairs']]})
    report['contingency_manual'] = [data.players[p['id']]['name'] for p in gone]

    lines = ['# Pick #6 shortlist (per-model; decision support, NOT calibrated odds)', '',
             'Assumed taken before #6: ' + ', '.join(report['assumed_gone']) + '.',
             'Own keepers: ' + ', '.join(report['keepers']) + '.',
             'Seeds: `production_lab` (held-out block untouched). Generated ' + report['generated_at'] + '.',
             'Assumed-gone elites are excluded from forced evaluation (see contingency note).', '']
    for block in deep:
        lines += ['## Opponent model: ' + block['model'], '',
                  '| Candidate | ADP | Champ % | Advancement | Punt |', '|---|---:|---:|---:|---|']
        for c in order:
            lines.append('| %s | %.1f | %.0f%% | %.2f | %s |' % (data.players[c]['name'], data.players[c]['market_adp'],
                         100 * block['rate'][c], block['adv'][c], ','.join(block['punt'][c]) or 'balanced'))
        if block['pairs']:
            lines += ['', 'Paired differences vs %s (clustered by draft):' % data.players[block['pairs'][0]['ref']]['name'], '']
            for p in block['pairs']:
                iv = p['interval']
                span = '—' if iv['low'] is None else '[%+.0f, %+.0f] pts' % (100 * iv['low'], 100 * iv['high'])
                lines.append('- %s − %s: %+.1f pts %s' % (data.players[p['ref']]['name'], data.players[p['cand']]['name'], 100 * p['gap'], span))
        lines.append('')
    lines += ['', '## Category detail (single continuation — illustrative, not the player)', '']
    for c in order:
        rep = category_report(engine, deep[0]['roster'][c])
        lines.append('- **%s**: strengths %s; weak %s.' % (data.players[c]['name'], ', '.join(rep['strengths']), ', '.join(rep['weaknesses'])))
    lines += ['', '## Contingency (unexpected elite fall)',
              '- If one of ' + ', '.join(report['contingency_manual']) + ' is on the board at #6, evaluate it directly before picking.',
              '', 'Read with care: few draft clusters; intervals are assumption-conditional, not odds. Overlapping intervals are not a ranking.']
    Path(args.report).write_text('\n'.join(lines) + '\n')
    Path(args.out).write_text(json.dumps(report, indent=1))
    print('wrote', args.out, 'and', args.report, 'in %.1f min' % ((time.perf_counter() - t0) / 60))
    store.db.close()


if __name__ == '__main__':
    main()
