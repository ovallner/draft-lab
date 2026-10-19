#!/usr/bin/env python3
"""Decision-level study: does the engine's pick beat credible alternatives?

Builds a stratified corpus from BOTH `fit` and `live` draft trajectories (plus
targeted stress flags), then for each state evaluates the engine's top pick and
several credible alternatives via paired completions (a common continuation policy)
and paired season simulations. Reports regret, material-suboptimal frequency,
stability, survival calibration and clustered uncertainty. Read-only.

    python3 scripts/run_decision_benchmark.py --fit-drafts 4 --live-drafts 2 \
        --candidates 4 --seasons 4 --continuation fit
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
from app.decision import DecisionBenchmark
from app.engine import Engine
from app.season_inputs import SeasonInputs
from app.season_draft import SeasonDraft
from app.store import Store

HYPOTHESIS = {'name': 'Decision study hypothesis (NOT confirmed)',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
FIT = {'name': 'fit', 'policy': 'fit', 'punts': [], 'streaming': 'aggressive', 'playoff_weight': .8, 'risk': .5}
LIVE = {'name': 'live', 'policy': 'live', 'punts': [], 'streaming': 'aggressive'}


def phase(round_number):
    return 'early' if round_number <= 5 else 'middle' if round_number <= 10 else 'late'


def partial_states(base, trace, data):
    """Every partial board at one of our owned slots, with stress flags."""
    me = data.config['team_name']
    out = []
    for s in base['slots']:
        if s['keeper'] or s['current_team'] != me:
            continue
        k = s['slot']
        st = copy.deepcopy(base)
        st['settings'] = dict(st.get('settings') or {})
        st['settings'].pop('draft_scenarios', None)
        for slot in st['slots']:
            if slot['slot'] < k and not slot['keeper'] and slot['slot'] in trace:
                pid = trace[slot['slot']]
                slot['player_id'] = pid
                slot['player_name'] = data.players[pid]['name']
        st['drafted'] = [slot['player_id'] for slot in st['slots'] if slot['player_id']]
        st['current_slot'] = k
        owned = [slot['player_id'] for slot in st['slots'] if slot['current_team'] == me and slot['player_id']]
        owned += [p['id'] for p in data.players.values() if p['keeper'] == me]
        flags = []
        if int(s['round']) >= 11:
            flags.append('deep_round')
        if not any('C' in data.players[pid]['positions'] for pid in owned):
            flags.append('no_center')
        avail = [p for p in data.players.values() if not p['keeper'] and p['id'] not in st['drafted']]
        if any(p['rank'] <= 12 for p in avail) and int(s['round']) >= 3:
            flags.append('unexpected_availability')
        out.append({'round': int(s['round']), 'slot': k, 'phase': phase(int(s['round'])),
                    'flags': flags, 'state': st})
    return out


def build_corpus(data, inputs, base, drafter, fit_drafts, live_drafts, opponent):
    corpus = []
    di = 0
    for seed in range(fit_drafts):
        draft = drafter.complete(base, FIT, opponent, 7000 + seed)
        trace = {t['slot']: t['player_id'] for t in draft['trace']}
        for e in partial_states(base, trace, data):
            e.update(draft_id='fit-%d' % seed, draft_index=di, source='fit'); di += 1
            corpus.append(e)
    for seed in range(live_drafts):
        draft = drafter.complete(base, LIVE, opponent, 8000 + seed)
        trace = {t['slot']: t['player_id'] for t in draft['trace']}
        for e in partial_states(base, trace, data):
            e.update(draft_id='live-%d' % seed, draft_index=di, source='live'); di += 1
            corpus.append(e)
    return corpus


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fit-drafts', type=int, default=4)
    ap.add_argument('--live-drafts', type=int, default=2)
    ap.add_argument('--candidates', type=int, default=4)
    ap.add_argument('--seasons', type=int, default=4)
    ap.add_argument('--continuation', default='fit')
    ap.add_argument('--opponent', default='adp_stochastic')
    ap.add_argument('--cap', type=int, default=0, help='limit corpus size (0 = all)')
    ap.add_argument('--out', default='local/decision_study.json')
    args = ap.parse_args()

    t0 = time.perf_counter()
    data = Data(); engine = Engine(data); inputs = SeasonInputs(data)
    store = Store(':memory:', data)
    config, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1,
                                                    'seasons_per_draft': args.seasons,
                                                    'seed_block': 'exploration', 'holdout': 1})
    config['seasons_per_draft'] = args.seasons
    base = states[0]
    drafter = SeasonDraft(engine)
    corpus = build_corpus(data, inputs, base, drafter, args.fit_drafts, args.live_drafts, args.opponent)
    if args.cap and args.cap < len(corpus):
        # Spread the cap across source drafts so several clusters remain.
        step = max(1, len(corpus) // args.cap)
        corpus = [corpus[i] for i in range(0, len(corpus), step)][:args.cap]
    t_build = time.perf_counter() - t0
    continuation = FIT if args.continuation == 'fit' else LIVE
    bench = DecisionBenchmark(engine, inputs, config, continuation, args.opponent,
                              continuation=continuation, candidates=args.candidates)
    t1 = time.perf_counter()
    report = bench.run(corpus, config['seed'])
    t_run = time.perf_counter() - t1

    print('corpus: %d states (%d fit, %d live) over %d source drafts'
          % (len(corpus), sum(1 for e in corpus if e['source'] == 'fit'),
             sum(1 for e in corpus if e['source'] == 'live'), len({e['draft_id'] for e in corpus})))
    print('phases:', {p: sum(1 for e in corpus if e['phase'] == p) for p in ('early', 'middle', 'late')})
    print('flags:', {f: sum(1 for e in corpus if f in e['flags']) for f in sorted({f for e in corpus for f in e['flags']})})
    print('states evaluated:', report['states'], 'clusters:', report['clusters'])
    print('mean regret vs best-tested (UPWARD-BIASED upper bound): %.4f  interval %s'
          % (report['mean_regret'], report['regret_interval']))
    print('mean chosen minus mean(alternatives) [paired, not max-selected]: %.4f  interval %s'
          % (report['mean_chosen_vs_mean_others'], report['chosen_vs_mean_others_interval']))
    print('mean chosen minus #2 [paired]: %.4f  interval %s'
          % (report['mean_chosen_vs_second'], report['chosen_vs_second_interval']))
    print('frequency any alternative better: %.3f | materially better (>=%.2f): %.3f | chosen behind average: %.3f'
          % (report['frequency_any_alternative_better'], report['materiality'],
             report['frequency_materially_better'], report['frequency_chosen_behind_average']))
    print('by phase:', {k: (v['n'], round(v['mean_regret'], 3), round(v['materially_better'], 3))
                        for k, v in report['by_phase'].items()})
    if report.get('by_flag'):
        print('by flag:', {k: (v['n'], round(v['mean_regret'], 3), round(v['materially_better'], 3))
                           for k, v in report['by_flag'].items()})
    if report.get('survival_calibration'):
        sc = report['survival_calibration']
        print('survival calibration: n=%d mean_bias=%.3f mean_abs_error=%.3f'
              % (sc['n'], sc['mean_bias'], sc['mean_abs_error']))
        for b in sc['bins']:
            print('   predicted %s n=%d -> observed %.2f' % (b['range'], b['n'], b['observed']))
    print('compute: build %.1fs, evaluation %.1fs' % (t_build, t_run))
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print('wrote', out)
    store.db.close()


if __name__ == '__main__':
    main()
