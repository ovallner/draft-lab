#!/usr/bin/env python3
"""Apply the Yahoo completed-board reconciliation to the Live board (append-only).

Fail-closed: verifies the expected pre-correction state before appending anything.
Dry run by default; pass --apply to write events. Source CSV keeper/slot assumptions
are corrected separately (keepers.csv status, draft_slots.csv slot 103/123/128).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import Data
from app.engine import Engine
from app.store import Store

CLEAR = [104, 105, 106, 118]
PICKS = [  # (slot, team, player_id, player_name)
    (103, 'Austin', 'ht:9447', 'CJ McCollum'),
    (104, 'Nick', 'ht:38942', 'Keegan Murray'),
    (105, 'Jipples', 'ht:120377', 'Yaxel Lendeborg'),
    (106, 'Raul', 'ht:10149', 'Brandon Ingram'),
    (118, 'Raul', 'ht:31068', 'Neemias Queta'),
]
KEEPER_SWAP = [(123, 'Ace Bailey'), (128, 'Jabari Smith Jr.')]


def slot_player(state, data, n):
    s = state['slots'][n - 1]
    if s['player_id']:
        return data.players[s['player_id']]['name']
    return s['keeper_player'] if s['keeper'] else ''


def verify_expected(state, data):
    expected = {103: '', 104: 'CJ McCollum', 105: 'Keegan Murray', 106: 'Yaxel Lendeborg',
                118: 'Brandon Ingram'}
    problems = []
    for n, name in expected.items():
        got = slot_player(state, data, n)
        if got != name:
            problems.append(f'#{n}: expected {name!r}, found {got!r}')
    for n, name in KEEPER_SWAP:
        s = state['slots'][n - 1]
        got = s['keeper_player'] if s['keeper'] else ''
        want = 'Jabari Smith Jr.' if name == 'Ace Bailey' else 'Ace Bailey'
        if got != want:
            problems.append(f'#{n}: expected keeper {want!r}, found {got!r}')
    if problems:
        raise SystemExit('Pre-state mismatch; refusing to apply:\n  ' + '\n  '.join(problems))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    data = Data(); engine = Engine(data); store = Store('local/draft.sqlite3', data)
    state = store.state()
    verify_expected(state, data)
    plan = [('clear_pick', {'slot': n}) for n in CLEAR]
    plan += [('pick', {'slot': slot, 'team': team, 'player_id': pid, 'player_name': name})
             for slot, team, pid, name in PICKS]
    for slot, name in KEEPER_SWAP:
        plan.append(('slot_override', {'slot': slot, 'changes': {'keeper': False, 'keeper_player': '', 'player_name': ''}}))
    for slot, name in KEEPER_SWAP:
        plan.append(('slot_override', {'slot': slot, 'changes': {'keeper': True, 'keeper_player': name, 'player_name': name}}))
    print(f'Planned {len(plan)} append-only events:')
    for kind, payload in plan:
        print(' ', kind, payload)
    if not args.apply:
        print('dry run only; pass --apply to write')
        store.db.close(); return
    for kind, payload in plan:
        current = store.state()
        store.append(kind, payload, current['revision'])
    final = store.state()
    rosters = engine.rosters(final)
    all_ids = [p['id'] for r in rosters.values() for p in r]
    print('\nApplied. revision', final['revision'], '| current_slot', final['current_slot'])
    print('assets/team', sorted({len(r) for r in rosters.values()}), '| unique', len(set(all_ids)))
    store.db.close()


if __name__ == '__main__':
    main()
