#!/usr/bin/env python3
"""Draft-night guidance data: #43/#54 targets after forcing KAT / Mobley / Sengün at #6.

For each candidate: force it at #6, complete the rest with the production `live` engine
(adaptive punts), then report our actual picks, the projected category totals and opponent
edges for the completed roster, and the FULL #43 and #54 recommendation lists (score, punt,
availability) — including where Ausar Thompson ranks and the score gap. Read-only.

    python3 scripts/run_pick6_plans.py
"""
import copy
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import seeds
from app.data import CATEGORIES, Data
from app.engine import Engine
from app.market import market_key
from app.season_draft import SeasonDraft
from app.season_inputs import SeasonInputs
from app.store import Store

HYPOTHESIS = {'name': 'Confirmed ownership 2026-10-12',
              'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
LIVE = {'name': 'live', 'policy': 'live', 'punts': [], 'streaming': 'aggressive'}
NAMES = ['Karl-Anthony Towns', 'Evan Mobley', 'Alperen Sengün']


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


def state_upto(data, base, trace, upto, current):
    st = copy.deepcopy(base)
    st['settings'] = dict(st.get('settings') or {})
    st['settings'].pop('draft_scenarios', None)
    for slot in st['slots']:
        if slot['slot'] < upto and not slot['keeper'] and slot['slot'] in trace:
            pid = trace[slot['slot']]
            slot['player_id'] = pid; slot['player_name'] = data.players[pid]['name']
    st['drafted'] = [s['player_id'] for s in st['slots'] if s['player_id']]
    st['current_slot'] = current
    return st


def recs(engine, state, n=15):
    r = engine.recommend(state)
    rows = []
    for x in (r.get('recommendations') or [])[:n]:
        rows.append({'name': x['player']['name'], 'score': x['score'], 'punt': list(x.get('punt') or []),
                     'adp': x['player'].get('market_adp'), 'at_next': x.get('availability_at_next')})
    return rows


def ausar_rank(rows):
    for i, x in enumerate(rows):
        if x['name'] == 'Ausar Thompson':
            gap = (rows[0]['score'] - x['score']) if rows else None
            return i + 1, gap
    return None, None


def main():
    t0 = time.perf_counter()
    data = Data(); engine = Engine(data); inputs = SeasonInputs(data); store = Store(':memory:', data)
    config, states = inputs.prepare(store.state(), {'asset_scenarios': [HYPOTHESIS], 'drafts': 1,
                                                    'seasons_per_draft': 1, 'seed_block': 'production_lab', 'holdout': 1})
    base6 = board_at_pick6(data, states[0], 5)
    by = {p['name']: p for p in data.players.values()}
    drafter = SeasonDraft(engine)
    seed = seeds.draft_seed(20261018, 'production_lab', 1, 0) + 50_000
    out = []
    for name in NAMES:
        cid = by[name]['id']
        draft = drafter.complete(base6, LIVE, 'adp_stochastic', seed, first_pick=cid)
        trace = {t['slot']: t['player_id'] for t in draft['trace']}
        my = sorted((t for t in draft['trace'] if t['team'] == data.config['team_name']), key=lambda t: t['slot'])
        picks = [(t['slot'], data.players[t['player_id']]['name']) for t in my]
        full = state_upto(data, base6, trace, 999, None)
        analysis = engine.team_analysis(full, full['settings'])
        w18 = analysis['own']['weeks'][0]['categories']
        edges = [statistics.mean(m['weeks'][0]['category_edges'][j] for m in analysis['matchups']) for j in range(9)]
        weak_cats = [CATEGORIES[j] for j in sorted(range(9), key=lambda j: edges[j])[:3]]
        mean_win = statistics.mean(m['weeks'][0]['win_proxy'] for m in analysis['matchups'])
        roster = draft['rosters'][data.config['team_name']]
        z = [round(sum(engine.z[p][j] for p in roster if p in engine.z), 1) for j in range(9)]
        order = sorted(range(9), key=lambda j: z[j], reverse=True)
        r43 = recs(engine, state_upto(data, base6, trace, 43, 43))
        r54 = recs(engine, state_upto(data, base6, trace, 54, 54))
        ar43, gap43 = ausar_rank(r43); ar54, gap54 = ausar_rank(r54)
        ausar_id = by['Ausar Thompson']['id']
        st43 = state_upto(data, base6, trace, 43, 43)
        ausar_taken = next((t['slot'] for t in draft['trace'] if t['player_id'] == ausar_id), None)
        ausar_on_board_43 = ausar_id not in st43['drafted'] and by['Ausar Thompson']['keeper'] is None
        out.append({'candidate': name, 'our_picks': picks, 'punt_final': draft['punts'][data.config['team_name']],
                    'w18_categories': {CATEGORIES[j]: round(w18[j], 3 if j < 2 else 1) for j in range(9)},
                    'mean_win_proxy': round(mean_win, 3), 'weak_vs_opponents': weak_cats,
                    'roster_z': {CATEGORIES[j]: z[j] for j in range(9)},
                    'strengths': [CATEGORIES[j] for j in order[:3]], 'weak': [CATEGORIES[j] for j in order[-3:]],
                    'targets_43': r43, 'targets_54': r54, 'ausar_rank_43': ar43, 'ausar_gap_43': gap43,
                    'ausar_rank_54': ar54, 'ausar_gap_54': gap54,
                    'ausar_taken_slot': ausar_taken, 'ausar_on_board_43': ausar_on_board_43})
        print('== %s | final punt=%s | W18 win proxy %.2f' % (name, ','.join(out[-1]['punt_final']) or 'balanced', mean_win))
        print('   picks:', ' '.join('#%d %s' % (s, n) for s, n in picks))
        print('   W18 cats:', out[-1]['w18_categories'])
        print('   weak vs opponents:', ', '.join(weak_cats), '| roster z:', {k: z[i] for i, k in enumerate(CATEGORIES)})
        print('   #43:', ' | '.join('%d.%s(%s%s)' % (i + 1, x['name'], ','.join(x['punt']) or 'bal', '' if x['at_next'] is None else ' %.2f' % x['at_next']) for i, x in enumerate(r43)))
        print('   Ausar #43 rank %s gap %s | #54 rank %s gap %s | taken slot %s | on board at #43 %s' % (
            ar43, None if gap43 is None else round(gap43, 3), ar54, None if gap54 is None else round(gap54, 3),
            ausar_taken, ausar_on_board_43))
    Path('local/pick6_plans.json').write_text(json.dumps(out, indent=1))
    print('elapsed %.1f min' % ((time.perf_counter() - t0) / 60))
    store.db.close()


if __name__ == '__main__':
    main()
