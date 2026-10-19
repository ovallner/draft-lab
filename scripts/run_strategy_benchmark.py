#!/usr/bin/env python3
"""Run a paired strategy benchmark headless and print the recommendation.

Uses a separated seed block (exploration vs held-out evaluation) and keeps the
production `live` policy as the authoritative arm. Read-only w.r.t. the live store.

    python3 scripts/run_strategy_benchmark.py --drafts 100 --seasons 2 \
        --opponents adp_stochastic --block evaluation --holdout 1
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.benchmark import BenchmarkRunner, atomic_json
from app.data import Data
from app.season_inputs import DEFAULT_STRATEGIES
from app.store import Store

HYPOTHESIS = {'name': 'Confirmed ownership 2026-10-12 (106 Raul / 113 Samet / 123 Nick)',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drafts', type=int, default=100)
    ap.add_argument('--seasons', type=int, default=2)
    ap.add_argument('--opponents', default='adp_stochastic')
    ap.add_argument('--block', default='evaluation')
    ap.add_argument('--holdout', type=int, default=1)
    ap.add_argument('--seed', type=int, default=20261018)
    ap.add_argument('--live', default='on', choices=('on', 'off'))
    ap.add_argument('--out', default='local/draft_benchmarks')
    args = ap.parse_args()

    data = Data(); store = Store(':memory:', data)
    strategies = [s for s in DEFAULT_STRATEGIES if s['policy'] != 'live' or args.live == 'on']
    config = {'asset_scenarios': [HYPOTHESIS], 'drafts': args.drafts, 'seasons_per_draft': args.seasons,
              'opponent_modes': args.opponents.split(','), 'seed': args.seed,
              'seed_block': args.block, 'holdout': args.holdout, 'strategies': strategies}
    run_id = uuid.uuid4().hex
    path = Path(args.out) / run_id; path.mkdir(parents=True, exist_ok=True)
    atomic_json(path / 'request.json', {'state': store.state(), 'config': config,
                                        'source_session': {'id': 'cli', 'name': 'CLI ' + args.block}})
    print('run', run_id, '| drafts', args.drafts, '| seasons', args.seasons,
          '| opponents', args.opponents, '| block', args.block, 'holdout', args.holdout)
    t = time.perf_counter()
    result = BenchmarkRunner(path, data).run()
    elapsed = time.perf_counter() - t
    print('elapsed %.1f min' % (elapsed / 60))
    for case in result['cases']:
        s = case['summary']['Oscar']
        print('  %-16s %-26s title %.3f  cond %.3f  adv %.2f  qual %.3f  proj %.1f'
              % (case['opponent_mode'], case['strategy']['name'], s['title_rate'],
                 s.get('conditional_title_rate', 0), s['mean_advancement'],
                 s['qualification_rate'], s['projected_rank']))
    rec = result.get('recommendation', {})
    print('STATUS', rec.get('status'), '|', rec.get('headline'))
    print(json.dumps(path / 'results.json'))
    store.db.close()


if __name__ == '__main__':
    main()
