#!/usr/bin/env python3
"""Time and check the production engine across representative draft states.

Read-only: never touches the live store. Builds partial boards by completing cheap
drafts with a transparent `fit` pick, then calls the AUTHORITATIVE, unpruned
engine.recommend() on each partial board (early/middle/late, keeper-heavy).

Reports per-phase timing, candidate/build counts, determinism, and shared-logic
agreement (the `live` policy must equal a direct recommend call on the same board).
If/when a pruned implementation exists, pass --compare-pruning to measure top-1
agreement and utility deltas; that path is intentionally not wired yet.

    python3 scripts/benchmark_fidelity.py --states 100 --seeds 12
"""
import argparse
import copy
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

HYPOTHESIS = {'name': 'Fidelity hypothesis (NOT confirmed)',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
FIT = {'name': 'fit', 'policy': 'fit', 'punts': [], 'streaming': 'aggressive', 'playoff_weight': .8, 'risk': .5}


def phase(round_number):
    return 'early' if round_number <= 5 else 'middle' if round_number <= 10 else 'late'


def build_states(data, states, seeds, mc_trials=None):
    engine = Engine(data)
    drafter = SeasonDraft(engine)
    base = states[0]
    my = [s for s in base['slots'] if s['current_team'] == data.config['team_name'] and not s['keeper']]
    columns = []
    for seed in range(seeds):
        draft = drafter.complete(base, FIT, 'adp_stochastic', 1000 + seed)
        trace = {t['slot']: t['player_id'] for t in draft['trace']}
        for s in my:
            k = s['slot']
            st = copy.deepcopy(base)
            st['settings'] = dict(st.get('settings') or {})
            st['settings'].pop('draft_scenarios', None)  # scenario is already baked into the state
            if mc_trials:
                st['settings']['mc_trials'] = mc_trials
            for slot in st['slots']:
                if slot['slot'] < k and not slot['keeper'] and slot['slot'] in trace:
                    pid = trace[slot['slot']]
                    slot['player_id'] = pid
                    slot['player_name'] = data.players[pid]['name']
            st['drafted'] = [slot['player_id'] for slot in st['slots'] if slot['player_id']]
            st['current_slot'] = k
            columns.append((int(s['round']), k, st))
    return columns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--states', type=int, default=100)
    ap.add_argument('--seeds', type=int, default=12)
    ap.add_argument('--mc-trials', type=int, default=None)
    args = ap.parse_args()

    data = Data()
    engine = Engine(data)
    inputs = SeasonInputs(data)
    store = Store(':memory:', data)
    config, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1,
                                                    'seasons_per_draft': 1})
    columns = build_states(data, states, args.seeds, args.mc_trials)
    picked = columns[:args.states]

    results = []
    for round_number, slot, st in picked:
        t = time.perf_counter()
        res = engine.recommend(st)
        elapsed = time.perf_counter() - t
        top = res['recommendations'][0] if res['recommendations'] else None
        results.append({'round': round_number, 'slot': slot, 'phase': phase(round_number),
                        'elapsed': elapsed, 'builds': res.get('strategies_screened'),
                        'candidates': res.get('candidates_tested'),
                        'top': top['player']['name'] if top else None,
                        'punt': top['punt'] if top else None,
                        'n_recs': len(res['recommendations'])})

    print('states evaluated: %d (from %d independent drafts)' % (len(results), args.seeds))
    for ph in ('early', 'middle', 'late'):
        rows = [r for r in results if r['phase'] == ph]
        if not rows:
            continue
        times = [r['elapsed'] for r in rows]
        print('  %-7s n=%3d  recommend(): min %.2fs  median %.2fs  max %.2fs  | builds~%.0f candidates~%.0f'
              % (ph, len(rows), min(times), statistics.median(times), max(times),
                 statistics.mean(r['builds'] or 0 for r in rows), statistics.mean(r['candidates'] or 0 for r in rows)))
    alltimes = [r['elapsed'] for r in results]
    print('overall: median %.2fs  mean %.2fs  total %.1f min' % (
        statistics.median(alltimes), statistics.mean(alltimes), sum(alltimes) / 60))
    proj = statistics.mean(alltimes) * 10  # ~10 owned live picks per draft
    print('projected live-arm draft cost: ~%.1f min/draft (10 owned picks)' % (proj / 60))

    # Shared-logic + determinism spot checks (a few states).
    drafter = SeasonDraft(engine)
    checks = 0
    for round_number, slot, st in picked[:3]:
        first = engine.recommend(st)['recommendations'][0]['player']['id']
        again = engine.recommend(st)['recommendations'][0]['player']['id']
        live = drafter.pick_live(st)[0]['id']
        assert first == again, 'recommend is not deterministic on state %s' % slot
        assert first == live, 'live policy diverged from recommend at slot %s' % slot
        checks += 1
    print('shared-logic + determinism checks passed on %d states' % checks)
    store.db.close()


if __name__ == '__main__':
    main()
