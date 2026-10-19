#!/usr/bin/env python3
"""Focused paired head-to-head at pick #6 (KAT vs Mobley vs Sengün by default).

Reports PER-MODEL paired championship-rate differences (not one pooled number), using
common replicate seeds across candidates and DISTINCT season worlds per draft. Adds a
confirmation pass on FRESH season worlds to check stability. Candidates can be named
explicitly so the comparison is not driven by a noisy broad-run shortlist.

Read-only: never touches the live store or the held-out `evaluation` seed block.

    python3 scripts/run_pick6_h2h.py --drafts 4 --seasons 4
    python3 scripts/run_pick6_h2h.py --include "Karl-Anthony Towns,Evan Mobley,Alperen Sengün"
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
from app.data import Data
from app.decision import DecisionBenchmark, cluster_bootstrap
from app.engine import Engine
from app.market import market_key
from app.season_inputs import SeasonInputs
from app.store import Store

HYPOTHESIS = {'name': 'Confirmed ownership 2026-10-12 (106 Raul / 113 Samet / 123 Nick)',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
LIVE = {'name': 'live', 'policy': 'live', 'punts': [], 'streaming': 'aggressive'}
DEFAULT = ['Karl-Anthony Towns', 'Evan Mobley', 'Alperen Sengün']


def board_at_pick6(data, base, assumed_gone):
    st = copy.deepcopy(base)
    st['settings'] = dict(st.get('settings') or {})
    st['settings'].pop('draft_scenarios', None)
    slots = [s for s in st['slots'] if not s['keeper'] and not s['player_id']]
    pool = sorted([p for p in data.players.values() if not p['keeper'] and p['id'] not in st['drafted']], key=market_key)
    my_slot = next(s['slot'] for s in slots if s['current_team'] == data.config['team_name'])
    taken = [s for s in slots if s['slot'] < my_slot]
    gone = pool[:min(assumed_gone, len(taken))]
    for s, p in zip(taken, gone):
        s['player_id'] = p['id']; s['player_name'] = p['name']
    st['drafted'] = [s['player_id'] for s in st['slots'] if s['player_id']]
    st['current_slot'] = my_slot
    return st


def collect(bench, state, cands, models, drafts, seeds_fn, world_offset, seasons, tag):
    per = []
    for mi, m in enumerate(models):
        bench.opponent_mode = m
        for d in range(drafts):
            seed = seeds_fn(mi, d)
            out = bench.evaluate_candidates(state, cands, seed, seasons=seasons, world_offset=world_offset)
            per.append({'model': m, 'draft': d, 'seed': seed,
                        'titles': {c: out[c]['titles'] for c in cands},
                        'adv': {c: out[c]['advancements'] for c in cands},
                        'roster': {c: out[c]['roster'] for c in cands},
                        'punt': {c: out[c]['punt'] for c in cands}})
            print('[%s] %s draft %d done (%.1f min)' % (tag, m, d, (time.perf_counter() - START) / 60), flush=True)
    return per


def paired(per_model, a, b):
    by = {}
    for e in per_model:
        by.setdefault(e['draft'], []).extend([x - y for x, y in zip(e['titles'][a], e['titles'][b])])
    vals = [v for d in by.values() for v in d]
    return statistics.mean(vals), cluster_bootstrap(by, 7), len(by)


def per_model_view(per, cands, names):
    out = []
    for m in sorted({e['model'] for e in per}):
        rows = [e for e in per if e['model'] == m]
        rate = {c: statistics.mean(t for e in rows for t in e['titles'][c]) for c in cands}
        pairs = []
        for i in range(len(cands)):
            for j in range(i + 1, len(cands)):
                gap, iv, cl = paired(rows, cands[i], cands[j])
                pairs.append({'a': names[cands[i]], 'b': names[cands[j]], 'gap': gap, 'interval': iv, 'clusters': cl})
        out.append({'model': m, 'rate': {names[c]: rate[c] for c in cands}, 'pairs': pairs})
    return out


START = time.perf_counter()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--include', default=','.join(DEFAULT), help='comma-separated candidate names')
    ap.add_argument('--drafts', type=int, default=4)
    ap.add_argument('--seasons', type=int, default=4)
    ap.add_argument('--assumed-gone', type=int, default=5)
    ap.add_argument('--models', default='adp_stochastic,validated')
    ap.add_argument('--opponent', default='adp_stochastic')
    ap.add_argument('--salt', type=int, default=20261018)
    ap.add_argument('--offset', type=int, default=50_000)
    ap.add_argument('--confirm-offset', type=int, default=5_000_000, help='fresh-world offset for the confirmation pass')
    ap.add_argument('--out', default='local/pick6_h2h.json')
    ap.add_argument('--report', default='PICK6_H2H.md')
    args = ap.parse_args()

    data = Data(); engine = Engine(data); inputs = SeasonInputs(data)
    store = Store(':memory:', data)
    config, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1,
                                                    'seasons_per_draft': args.seasons,
                                                    'seed_block': 'production_lab', 'holdout': 1})
    state = board_at_pick6(data, states[0], args.assumed_gone)
    by = {p['name']: p for p in data.players.values()}
    names_wanted = [x.strip() for x in args.include.split(',') if x.strip()]
    missing = [n for n in names_wanted if n not in by]
    if missing:
        raise SystemExit('unknown candidate names: ' + ', '.join(missing))
    cands = [by[n]['id'] for n in names_wanted]
    names = {c: data.players[c]['name'] for c in cands}
    adp = {c: data.players[c]['market_adp'] for c in cands}
    models = args.models.split(',')
    bench = DecisionBenchmark(engine, inputs, config, LIVE, args.opponent, continuation=LIVE, candidates=len(cands))

    def seeds_fn(mi, d):
        # Same replicate seed for a given draft across opponent models, so models differ
        # only by their parameters, not by an independent random stream.
        return seeds.draft_seed(args.salt, 'production_lab', 1, d) + args.offset

    primary = collect(bench, state, cands, models, args.drafts, seeds_fn, 0, args.seasons, 'primary')
    confirm = collect(bench, state, cands, models, args.drafts, seeds_fn, args.confirm_offset, args.seasons, 'confirm')

    report = {'candidates': [{'name': names[c], 'adp': adp[c]} for c in cands],
              'models': models, 'drafts': args.drafts, 'seasons': args.seasons,
              'primary': per_model_view(primary, cands, names),
              'confirmation_fresh_worlds': per_model_view(confirm, cands, names),
              'punt_builds': {names[c]: sorted({','.join(e['punt'][c]) or 'balanced' for e in primary}) for c in cands},
              'note': 'Per-model paired differences vs common replicate seeds. Distinct worlds per draft; '
                      'confirmation pass uses fresh worlds. Uncertainty clustered by draft; few clusters.'}
    Path(args.out).write_text(json.dumps(report, indent=1))

    L = ['# Pick #6 head-to-head (per-model, paired)', '',
         'Candidates: ' + ', '.join('%s (ADP %.1f)' % (names[c], adp[c]) for c in cands),
         f'{args.drafts} drafts × {len(models)} models × {args.seasons} seasons per candidate; '
         'distinct season worlds per draft; confirmation pass on fresh worlds.', '',
         '## Championship rate by opponent model', '',
         '| Model | ' + ' | '.join(names[c] for c in cands) + ' |',
         '|---|' + '---:|' * len(cands)]
    for v in report['primary']:
        L.append('| %s | %s |' % (v['model'], ' | '.join('%.0f%%' % (100 * v['rate'][names[c]]) for c in cands)))
    for title, block in (('Paired differences — primary worlds', report['primary']),
                         ('Paired differences — confirmation (fresh worlds)', report['confirmation_fresh_worlds'])):
        L += ['', '## ' + title, '', '| Model | A − B | Δchamp | 95% draft-cluster interval |', '|---|---|---:|---|']
        for v in block:
            for p in v['pairs']:
                iv = p['interval']
                span = '—' if iv['low'] is None else '[%+.0f, %+.0f] pts' % (100 * iv['low'], 100 * iv['high'])
                L.append('| %s | %s − %s | %+.1f pts | %s |' % (v['model'], p['a'], p['b'], 100 * p['gap'], span))
    L += ['', '## Engine punt builds chosen (per candidate, across paired drafts)', '']
    for c in cands:
        L.append('- **%s**: %s' % (names[c], '; '.join(report['punt_builds'][names[c]])))
    L += ['', 'Read with care: few independent draft clusters; intervals are assumption-conditional, not calibrated odds. '
          'Overlapping intervals are not a ranking. A difference is only meaningful if the paired interval excludes zero '
          'AND the sign holds in the fresh-world confirmation pass.']
    Path(args.report).write_text('\n'.join(L) + '\n')
    print('wrote', args.out, 'and', args.report, 'in %.1f min' % ((time.perf_counter() - START) / 60))
    store.db.close()


if __name__ == '__main__':
    main()
