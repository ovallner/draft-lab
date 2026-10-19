#!/usr/bin/env python3
"""Investigate survival-probability calibration.

Distinguishes INTERNAL calibration (observations under the engine's OWN opponent
model, default `fit`) from ROBUSTNESS under alternative opponent environments
(e.g. `adp_stochastic`), and reports a reliability diagram, per-bin counts,
calibration error by draft phase, and the engine's own Monte-Carlo interval width so
we can tell a probability-calculation error from Monte-Carlo sampling from
opponent-model mismatch. Read-only.

    python3 scripts/survival_calibration.py --drafts 3 --candidates 4 --runs 12
"""
import argparse
import copy
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import Data
from app.engine import Engine
from app.season_inputs import SeasonInputs
from app.season_draft import SeasonDraft
from app.store import Store

HYPOTHESIS = {'name': 'Confirmed ownership 2026-10-12 (106 Raul / 113 Samet / 123 Nick)',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
FIT = {'name': 'fit', 'policy': 'fit', 'punts': [], 'streaming': 'aggressive', 'playoff_weight': .8, 'risk': .5}
EDGES = (0, .2, .4, .6, .8, 1.01)


def phase(r):
    return 'early' if r <= 5 else 'middle' if r <= 10 else 'late'


def build_states(data, base, drafter, drafts):
    corpus = []
    for seed in range(drafts):
        draft = drafter.complete(base, FIT, 'adp_stochastic', 7100 + seed)
        trace = {t['slot']: t['player_id'] for t in draft['trace']}
        for s in base['slots']:
            if s['keeper'] or s['current_team'] != data.config['team_name']:
                continue
            k = s['slot']
            st = copy.deepcopy(base)
            st['settings'] = dict(st.get('settings') or {})
            st['settings'].pop('draft_scenarios', None)
            for slot in st['slots']:
                if slot['slot'] < k and not slot['keeper'] and slot['slot'] in trace:
                    pid = trace[slot['slot']]
                    slot['player_id'] = pid; slot['player_name'] = data.players[pid]['name']
            st['drafted'] = [slot['player_id'] for slot in st['slots'] if slot['player_id']]
            st['current_slot'] = k
            corpus.append({'round': int(s['round']), 'phase': phase(int(s['round'])),
                           'state': st, 'draft_id': seed})
    return corpus


def observed(engine, state, candidate_ids, opponent_mode, seed, runs):
    me = engine.data.config['team_name']
    my = [s['slot'] for s in state['slots']
          if s['current_team'] == me and not s['keeper'] and not s['player_id']]
    if len(my) < 2:
        return None
    current, nxt = my[0], my[1]
    drafter = SeasonDraft(engine)
    out = {}
    for c in candidate_ids:
        filler = next(pid for pid in candidate_ids if pid != c)
        survived = 0
        for r in range(runs):
            d = drafter.complete(state, FIT, opponent_mode, seed + 700000 + r, first_pick=filler)
            taken = {t['player_id'] for t in d['trace'] if current < t['slot'] < nxt}
            if c not in taken:
                survived += 1
        out[c] = survived / runs
    return out


def bins(items):
    rows = []
    for lo, hi in zip(EDGES, EDGES[1:]):
        group = [it for it in items if lo <= it['predicted'] < hi]
        if group:
            rows.append({'range': [lo, hi], 'n': len(group),
                         'predicted': statistics.mean(it['predicted'] for it in group),
                         'observed': statistics.mean(it['observed'] for it in group)})
    return rows


def ece(items):
    n = len(items)
    if not n:
        return None
    total = 0.
    for row in bins(items):
        total += (row['n'] / n) * abs(row['observed'] - row['predicted'])
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drafts', type=int, default=3)
    ap.add_argument('--candidates', type=int, default=4)
    ap.add_argument('--runs', type=int, default=12)
    ap.add_argument('--modes', default='fit,adp_stochastic,validated')
    ap.add_argument('--out', default='local/survival_calibration.json')
    args = ap.parse_args()

    t0 = time.perf_counter()
    data = Data(); engine = Engine(data); inputs = SeasonInputs(data)
    store = Store(':memory:', data)
    config, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1, 'seasons_per_draft': 1})
    base = states[0]
    corpus = build_states(data, base, SeasonDraft(engine), args.drafts)
    modes = args.modes.split(',')

    items = []          # each: predicted, observed per mode, mc half-width, phase
    for i, entry in enumerate(corpus):
        state = entry['state']
        res = engine.recommend(state)
        rows = (res.get('recommendations') or [])[:args.candidates]
        if len(rows) < 2:
            continue
        ids = [r['player']['id'] for r in rows]
        predicted = {r['player']['id']: r['availability_later'] for r in rows}
        estimates = res.get('survival', {}).get('scenarios', [{}])[0].get('estimates', {})
        mc = {}
        for pid in ids:
            iv = (estimates.get(pid) or {}).get('later', {}).get('mc_95_interval')
            mc[pid] = None if not iv else (iv[1] - iv[0]) / 2
        obs = {}
        for m in modes:
            obs[m] = observed(engine, state, ids, m, 90000 + i, args.runs)
        for pid in ids:
            item = {'phase': entry['phase'], 'round': entry['round'], 'predicted': predicted[pid],
                    'mc_half_width': mc[pid]}
            for m in modes:
                item['observed_' + m] = (obs[m] or {}).get(pid)
            items.append(item)

    report = {'states': len(corpus), 'items': len(items), 'modes': modes, 'runs': args.runs}
    for m in modes:
        rows = [it for it in items if it.get('observed_' + m) is not None and it['predicted'] is not None]
        report['mode_' + m] = {
            'n': len(rows),
            'bias': statistics.mean(it['observed_' + m] - it['predicted'] for it in rows),
            'mae': statistics.mean(abs(it['observed_' + m] - it['predicted']) for it in rows),
            'ece': ece([{'predicted': it['predicted'], 'observed': it['observed_' + m]} for it in rows]),
            'reliability': bins([{'predicted': it['predicted'], 'observed': it['observed_' + m]} for it in rows]),
            'by_phase': {ph: {'n': len(q), 'bias': statistics.mean(it['observed_' + m] - it['predicted'] for it in q),
                              'ece': ece([{'predicted': it['predicted'], 'observed': it['observed_' + m]} for it in q])}
                         for ph in ('early', 'middle', 'late')
                         for q in [[it for it in rows if it['phase'] == ph]] if q},
        }
    mcw = [it['mc_half_width'] for it in items if it.get('mc_half_width')]
    report['mean_mc_half_width'] = statistics.mean(mcw) if mcw else None

    # Diagnosis.
    internal = report.get('mode_fit', {})
    adp = report.get('mode_adp_stochastic', {})
    half = report['mean_mc_half_width']
    diag = []
    if internal:
        diag.append('internal (fit) bias %.3f vs mean MC half-width %.3f' % (internal['bias'], half or 0))
        if half and abs(internal['bias']) <= half + 0.02 and internal['ece'] < 0.08:
            diag.append('-> internally coherent: no evidence of a probability-calculation error')
        elif half and abs(internal['bias']) > half + 0.05:
            diag.append('-> internal bias exceeds MC noise: suspect the our-picks proxy or a calculation issue')
    if internal and adp:
        diag.append('opponent-model mismatch (fit -> adp_stochastic) adds %.3f bias'
                    % (adp['bias'] - internal['bias']))
    report['diagnosis'] = diag

    print('states %d | items %d | runs %d | modes %s' % (len(corpus), len(items), args.runs, modes))
    for m in modes:
        r = report['mode_' + m]
        print('%-16s n=%3d bias=%+.3f mae=%.3f ece=%.3f' % (m, r['n'], r['bias'], r['mae'], r['ece']))
        print('   by phase:', {k: (v['n'], round(v['bias'], 3), round(v['ece'], 3)) for k, v in r['by_phase'].items()})
        for b in r['reliability']:
            print('   predicted %-10s n=%2d -> observed %.2f' % (str(b['range']), b['n'], b['observed']))
    print('mean MC half-width: %.3f' % (report['mean_mc_half_width'] or 0))
    print('diagnosis:')
    for d in report['diagnosis']:
        print('  -', d)
    print('elapsed %.1f min' % ((time.perf_counter() - t0) / 60))
    Path(args.out).write_text(json.dumps(report, indent=1))
    print('wrote', args.out)
    store.db.close()


if __name__ == '__main__':
    main()
