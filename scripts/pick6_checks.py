#!/usr/bin/env python3
"""Targeted verification for the Pick #6 review requests (read-only, no engine changes).

  3. FG%/FT% use aggregate makes/attempts; TO sign convention.
  4. Individual player contribution vs completed-roster strengths.
  6. Playoff usable games by week (w18/w19/w20), especially championship week.
  5. Ausar Thompson availability at #43/#54 from the keeper-adjusted pool.

    python3 scripts/pick6_checks.py
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import CATEGORIES, Data
from app.engine import Engine, aggregate
from app.market import market_key
from app.season_inputs import SeasonInputs
from app.season_world import compare_categories
from app.store import Store

HYPOTHESIS = {'name': 'Confirmed ownership 2026-10-12',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
CANDIDATES = ['Karl-Anthony Towns', 'Evan Mobley', 'Alperen Sengün']


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


def main():
    data = Data(); engine = Engine(data); inputs = SeasonInputs(data); store = Store(':memory:', data)
    by = {p['name']: p for p in data.players.values()}

    print('== 3. ratio + sign convention ==')
    a = [4, 10] + [0] * 9; b = [3, 6] + [0] * 9
    print('  FG% 4/10 (40%) vs 3/6 (50%):', compare_categories(a, b)[0], '(expect -1 → 50% wins)')
    a = [0, 0, 8, 10] + [0] * 7; b = [0, 0, 6, 10] + [0] * 7
    print('  FT% 8/10 vs 6/10:', compare_categories(a, b)[1], '(expect +1)')
    a = [0] * 10 + [5]; b = [0] * 10 + [3]
    print('  TO 5 vs 3:', compare_categories(a, b)[8], '(expect -1 → fewer TO wins)')
    print('  engine.raw TO for a 5-TO player:', engine.raw({'stats': [0] * 10 + [5], 'gp': 82})[-1], '(expect -5)')
    print('  aggregate FG% of 4/10:', round(aggregate([[4, 10] + [0] * 9])[0], 3), '(expect 0.4)')
    print('  zero-attempt tie:', compare_categories([0] * 11, [0] * 11)[:2], '(expect [0, 0])')

    print('\n== 4. individual contribution (own per-game z) ==')
    for n in CANDIDATES:
        z = engine.z[by[n]['id']]
        print('  %-22s' % n, {CATEGORIES[j]: round(z[j], 1) for j in range(9)})

    print('\n== 6. playoff games by week (w18, w19, w20) ==')
    for n in CANDIDATES + ['Ausar Thompson']:
        p = by[n]
        wk = data.weekly.get(p['team'], [0, 0, 0])
        print('  %-22s %-4s w18=%d w19=%d w20=%d (champ wk=%d)' % (n, p['team'], wk[0], wk[1], wk[2], wk[2]))

    print('\n== 5. Ausar Thompson availability at #43 / #54 (keeper-adjusted pool) ==')
    _, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1,
                                               'seasons_per_draft': 1, 'seed_block': 'production_lab', 'holdout': 1})
    st = board_at_pick6(data, states[0], 5)
    tid = by['Ausar Thompson']['id']
    r1 = engine.draft_model.survival(st, trials=400)
    c1 = r1['scenarios'][0]
    e1 = c1['estimates'].get(tid, {})
    print('  board at #6     horizon', c1['horizons'], 'barrier', c1['barrier'])
    print('    P(available at #43):', e1.get('later', {}).get('probability'), 'Wilson', e1.get('later', {}).get('mc_95_interval'), 'n', e1.get('later', {}).get('n'))
    # advance our own #6 pick to expose #43 and #54 horizons
    st2 = copy.deepcopy(st); s6 = st2['slots'][5]
    s6['player_id'] = by['Evan Mobley']['id']; s6['player_name'] = 'Evan Mobley'
    st2['drafted'] = [x['player_id'] for x in st2['slots'] if x['player_id']]
    st2['current_slot'] = next(x['slot'] for x in st2['slots'] if not x['keeper'] and not x['player_id'] and x['current_team'] == data.config['team_name'])
    r2 = engine.draft_model.survival(st2, trials=400)
    c2 = r2['scenarios'][0]; e2 = c2['estimates'].get(tid, {})
    print('  after our #6   horizon', c2['horizons'], 'barrier', c2['barrier'])
    print('    P(available at #43):', e2.get('next', {}).get('probability'), 'Wilson', e2.get('next', {}).get('mc_95_interval'))
    print('    P(available at #54):', e2.get('later', {}).get('probability'), 'Wilson', e2.get('later', {}).get('mc_95_interval'))
    print('  NOTE: engine survival is a model estimate and it modestly OVER-predicts survival (~-0.19 bias), so treat these as optimistic.')
    store.db.close()


if __name__ == '__main__':
    main()
