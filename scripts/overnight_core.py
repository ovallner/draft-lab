"""Read-only first-three-pick experiment primitives; production engine stays unmodified."""
import copy
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import Data, CATEGORIES
from app.engine import Engine
from app.market import market_key
from app.season_draft import SeasonDraft
from app.season_inputs import SeasonInputs
from app.season_sim import SeasonSimulator
from app.season_world import SeasonWorld
from app.store import Store
from app.draft_model import uncertainty_barrier

LIVE = {'name': 'Production continuation', 'policy': 'live', 'punts': [], 'streaming': 'aggressive'}
MODELS = ['adp_stochastic', 'validated']
MAIN = ['Karl-Anthony Towns', 'Evan Mobley', 'Alperen Sengün']
EXTRA = ['Kevin Durant', 'Scottie Barnes', 'Tyrese Maxey', 'Lauri Markkanen']
NS = 'first-three-20261012-v1-independent-of-heldout'
CTX = None


def atomic(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    os.replace(tmp, path)


def seed(*parts):
    return int.from_bytes(hashlib.sha256(json.dumps([NS, *parts]).encode()).digest()[:16], 'big')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def context():
    global CTX
    if CTX is None:
        data = Data(); engine = Engine(data); inputs = SeasonInputs(data)
        store = Store(':memory:', data)
        config, states = inputs.prepare(store.state(), {
            'strategies': [copy.deepcopy(LIVE)], 'opponent_modes': MODELS,
            'seed_block': 'production_lab', 'holdout': 1,
            'seasons_per_draft': 3, 'start_mode': 'keepers'})
        base = states[0]; base['settings'].pop('draft_scenarios', None)
        assert uncertainty_barrier(base, data) is None
        slots = [s['slot'] for s in base['slots'] if s['current_team'] == 'Oscar' and not s['keeper']]
        assert slots == [6, 43, 54, 67, 78, 91, 102, 115, 126, 150], slots
        assert {p['name'] for p in engine.rosters(base)['Oscar']} == {
            'Shai Gilgeous-Alexander', 'Donovan Mitchell', 'Kyshawn George'}
        store.db.close()
        CTX = data, engine, inputs, config, base
    return CTX


class StopBoard(Exception):
    def __init__(self, state):
        self.state = copy.deepcopy(state)


class Unavailable(Exception):
    pass


def available(state, data):
    used = set(state['drafted'])
    return [p for p in data.players.values() if not p['keeper'] and p['id'] not in used]


def static_select(policy, slot, taken43, ids):
    """Pure observable-board policy: no future board, season, RNG or engine inputs."""
    allowed = set(ids)
    ranked = policy['rank43'] if slot == 43 else policy['rank54'].get(taken43, policy['default54'])
    for pid in list(ranked) + policy['fallback']:
        if pid in allowed:
            return pid
    return None


def pool_rows(engine, state, recommendation):
    """Union of unpruned production output, value, and different category directions."""
    data = engine.data; avail = available(state, data)
    roster = engine.rosters(state)['Oscar']
    rows = recommendation['recommendations']
    by = {r['player']['id']: r for r in rows}
    sources = {}
    def add(players, why):
        for p in players:
            sources.setdefault(p['id'], []).append(why)
    add([r['player'] for r in rows[:15]], 'production_top15')
    market = sorted(avail, key=market_key)
    add(sorted(market[:60], key=lambda p: engine.value(p, (), .5), reverse=True)[:5], 'category_neutral_value')
    add(market[:5], 'market_value')
    for label, cats in [('stocks', [6, 7]), ('shooting', [1, 2]), ('bigs', [0, 4, 7]), ('creation', [3, 5])]:
        add(sorted(market[:60], key=lambda p: sum(engine.z[p['id']][j] for j in cats), reverse=True)[:2], label)
    out = []
    for pid, why in sources.items():
        p = data.players[pid]; r = by.get(pid)
        out.append({'id': pid, 'name': p['name'], 'sources': why,
                    'engine_rank': next((i + 1 for i, x in enumerate(rows) if x['player']['id'] == pid), None),
                    'score': r['score'] if r else None,
                    'evaluated_punts': r['punt'] if r else None,
                    'survival_to54': r.get('availability_later') if r else None,
                    'value': engine.value(p, (), .5), 'adp': p['market_adp'],
                    'z': engine.z[pid], 'positions': p['positions'],
                    'fit': r['fit'] if r else engine.position_fit(roster, p, (), .5)})
    return out


class PolicyDraft(SeasonDraft):
    def __init__(self, engine, task, policy=None, stop=None):
        super().__init__(engine)
        self.task = task; self.policy = policy; self.stop = stop
        self.decisions = []; self.taken43 = None

    def pick_live(self, state):
        slot = state['current_slot']
        if slot == self.stop:
            raise StopBoard(state)
        avail = available(state, self.data); ids = {p['id'] for p in avail}
        if slot == 6:
            pid = self.task['first']
            if pid not in ids:
                raise Unavailable(pid)
            return self.data.players[pid], []
        if slot not in (43, 54):
            return super().pick_live(state)
        rows = None; rec = None
        if self.task.get('discover') or self.policy is None or self.policy.get('oracle'):
            rec = self.engine.recommend(state)
            if not rec.get('recommendations'):
                raise ValueError('Production recommendation missing on legal board')
            rows = pool_rows(self.engine, state, rec)
        if self.policy is not None and not self.policy.get('oracle'):
            pid = static_select(self.policy, slot, self.taken43, ids)
        elif self.task.get('discover'):
            # Vary #43 choices without knowing the eventual #54 board.
            rank = self.task.get('explore_rank', 0) if slot == 43 else 0
            if rank < 3:
                pid = rec['recommendations'][min(rank, len(rec['recommendations'])-1)]['player']['id']
            else:
                alternatives = sorted(rows, key=lambda r: sum(r['z'][j] for j in [0, 4, 7]), reverse=True)
                pid = alternatives[0]['id']
        else:
            pid = rec['recommendations'][0]['player']['id']
        if pid is None or pid not in ids:
            raise ValueError('Policy failed availability contract')
        chosen = next((r for r in (rec or {}).get('recommendations', []) if r['player']['id'] == pid), None)
        decision = {'slot': slot, 'selected': pid, 'available': sorted(ids),
                    'opponent_rosters': {t: [p['id'] for p in r] for t, r in self.engine.rosters(state).items() if t != 'Oscar'},
                    'our_roster_before': [p['id'] for p in self.engine.rosters(state)['Oscar']],
                    'fit': self.engine.position_fit(self.engine.rosters(state)['Oscar'], self.data.players[pid], (), .5),
                    'candidates': rows}
        if self.task.get('discover'):
            decision['state'] = copy.deepcopy(state)
        self.decisions.append(decision)
        if slot == 43:
            self.taken43 = pid
        return self.data.players[pid], list(chosen['punt']) if chosen else []


def prefix(model, index, phase='screen', first=None, stop=6, policy=None):
    data, engine, inputs, config, base = context()
    draft = PolicyDraft(engine, {'first': first}, policy, stop)
    try:
        draft.complete(base, LIVE, model, seed('draft', phase, index))
    except StopBoard as exc:
        return exc.state
    raise ValueError('Expected stop not reached')


def stress_state(task, policy):
    """Explicit adverse intervention: replace two recent opponent picks, releasing displaced IDs."""
    data, engine, _, _, _ = context()
    at = 43 if task['stress'] == 'remove43top2' else 54
    state = prefix(task['model'], task['index'], task['phase'], task['first'], at, policy)
    taken43 = state['slots'][42]['player_id'] if at == 54 else None
    order = policy['rank43'] if at == 43 else policy['rank54'].get(taken43, policy['default54'])
    targets = [p for p in order if p in {x['id'] for x in available(state, data)}][:2]
    eligible = [s for s in state['slots'] if s['slot'] < at and (at == 43 or s['slot'] > 43)
                and s['current_team'] != 'Oscar' and not s['keeper'] and s['player_id']]
    swaps = []
    for slot, pid in zip(reversed(eligible), targets):
        swaps.append({'slot': slot['slot'], 'removed': slot['player_id'], 'inserted': pid})
        slot.update(player_id=pid, player_name=data.players[pid]['name'])
    state['drafted'] = [s['player_id'] for s in state['slots'] if s['player_id']]
    assert len(state['drafted']) == len(set(state['drafted']))
    return state, swaps


def final_diagnostics(draft, base):
    data, engine, _, _, _ = context()
    st = copy.deepcopy(base)
    for t in draft['trace']:
        st['slots'][t['slot']-1].update(player_id=t['player_id'], player_name=data.players[t['player_id']]['name'])
    st['drafted'] = [s['player_id'] for s in st['slots'] if s['player_id']]
    st['current_slot'] = None; st['settings']['punt'] = []
    analysis = engine.team_analysis(st)
    edges = {c: statistics.mean(m['weeks'][w]['category_edges'][j] for m in analysis['matchups'] for w in range(3))
             for j, c in enumerate(CATEGORIES)}
    roster = [data.players[pid] for pid in draft['rosters']['Oscar']]
    return {'category_edges': edges, 'analysis': analysis,
            'strengths': [c for c, x in edges.items() if x > .65],
            'weaknesses': [c for c, x in edges.items() if x < .35],
            'close': [c for c, x in edges.items() if .35 <= x <= .65],
            'usable_starts': sum(w['usable_starts'] for w in analysis['own']['weeks']),
            'blocked_games': sum(w['blocked_games'] for w in analysis['own']['weeks']),
            'c_only': [p['id'] for p in roster if set(p['positions']) == {'C'}],
            'multi_position_bigs': [p['id'] for p in roster if 'C' in p['positions'] and len(p['positions']) > 1],
            'temporary_last_engine_build': draft['punts']['Oscar']}


def execute_task(task):
    data, engine, inputs, config, base = context()
    path = Path(task['out'])
    if path.exists():
        return json.loads(path.read_text())
    t0 = time.time(); policy = task.get('policy')
    result = {'task': task, 'state': 'running', 'started_epoch': t0,
              'draft_seed': seed('draft', task['phase'], task['index'])}
    checkpoint = path.with_suffix('.checkpoint.json')
    if checkpoint.exists():
        result = json.loads(checkpoint.read_text())
    if 'draft' not in result and 'discoveries' not in result:
        drafter = PolicyDraft(engine, task, policy, 67 if task.get('discover') else None)
        start_state = base
        try:
            if task.get('stress'):
                start_state, swaps = stress_state(task, policy)
                result['stress_interventions'] = swaps
                if start_state['current_slot'] == 54:
                    drafter.taken43 = start_state['slots'][42]['player_id']
            result['draft'] = drafter.complete(start_state, LIVE, task['model'], result['draft_seed'])
        except Unavailable:
            result.update(state='unavailable_at6', seconds=time.time()-t0)
            atomic(path, result); return result
        except StopBoard:
            result['discoveries'] = drafter.decisions
        result['decisions'] = drafter.decisions
        result['draft_seconds'] = time.time() - t0
        if 'draft' in result:
            result['diagnostics'] = final_diagnostics(result['draft'], start_state)
        atomic(checkpoint, result)
    if 'draft' in result:
        result.setdefault('outcomes', [])
        for i in range(len(result['outcomes']), task.get('seasons', 3)):
            world_seed = seed('world', task['phase'], task['index'], i)
            world = SeasonWorld(data, inputs, config['calendar'], world_seed, config)
            sim = SeasonSimulator(engine, inputs).run(result['draft'], world, config)
            own = sim['teams']['Oscar']
            result['outcomes'].append({'seed': world_seed, 'title': int(bool(own['champion'])),
                                      'qualified': int(bool(own['qualified'])),
                                      'advancement': sum(int(bool(own[k])) for k in ('qualified','semifinal','final','champion')),
                                      'team_outcomes': sim['teams']})
            atomic(checkpoint, result)
    result.update(state='complete', seconds=time.time()-t0, finished_epoch=time.time())
    atomic(path, result)
    return result


def pilot(run):
    data, engine, inputs, config, base = context()
    by = {p['name']: p for p in data.players.values()}
    # A natural pre-pick board; skip indices where KAT has already been taken.
    index = next(i for i in range(100) if by[MAIN[0]]['id'] in {p['id'] for p in available(prefix('adp_stochastic', i, 'pilot'), data)})
    task = {'phase': 'pilot', 'index': index, 'first': by[MAIN[0]]['id'], 'model': 'adp_stochastic',
            'seasons': 2, 'policy': {'oracle': True, 'id': 'production'}, 'out': str(run/'pilot.json')}
    result = execute_task(task)
    atomic(run/'pilot_timing.json', {'seconds': result['seconds'], 'draft_seconds': result.get('draft_seconds'),
                                    'seasons': 2, 'task': task})
    print(json.dumps({'pilot_seconds': result['seconds'], 'draft_seconds': result.get('draft_seconds')}, indent=2), flush=True)


if __name__ == '__main__':
    pilot(Path(sys.argv[1]).resolve())
