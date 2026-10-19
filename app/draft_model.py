"""Shared, stochastic opponent choices and seeded draft-survival simulations."""
import copy
import hashlib
import json
import math
import random
from collections import Counter
from functools import lru_cache
from .market import market_key
from .history import phase


def board_integrity_issues(state, data):
    """WHOLE-BOARD integrity problems, independent of the current pick.

    Invalid keeper assignments behind `current_slot` (old saved boards) must still be
    reported, so this is not filtered by slot.
    """
    issues = []
    by_name = {k['player']: k for k in data.keepers}
    for s in state['slots']:
        if not s['keeper']:
            continue
        keeper = by_name.get(s['keeper_player'])
        if keeper is None:
            issues.append((s['slot'], f"Unknown keeper on #{s['slot']}: {s['keeper_player']}"))
        elif keeper['team'] != s['current_team'] or int(keeper['forfeited_round']) != int(s['round']):
            issues.append((s['slot'], f"Incompatible keeper on #{s['slot']}: {s['keeper_player']} belongs to "
                                      f"{keeper['team']} R{keeper['forfeited_round']}, but the slot owner is "
                                      f"{s['current_team']} R{s['round']}"))
    assigned = {s['keeper_player'] for s in state['slots'] if s['keeper']}
    for keeper in data.keepers:
        if keeper['player'] not in assigned:
            earliest = (int(keeper['forfeited_round']) - 1) * 12 + 1
            issues.append((earliest, f"Unassigned keeper asset: {keeper['team']} / {keeper['player']} (source R{keeper['forfeited_round']})"))
    counts = Counter(s['current_team'] for s in state['slots'])
    for team in data.teams:
        if counts[team] != data.config['rounds']:
            issues.append((state['current_slot'] or 157, f'Asset count for {team} is {counts[team]}, not 13; reconcile ownership/forfeiture mechanics rather than skipping extra picks'))
    return issues


def uncertainty_barrier(state, data):
    # Future unresolved-owner issues block only at/after the current pick and take
    # precedence (most actionable message), then WHOLE-BOARD integrity always blocks.
    future = [(s['slot'], 'Unresolved owner at #' + str(s['slot'])) for s in state['slots']
              if not s['keeper'] and not s['player_id'] and not s['current_team']]
    future = [x for x in future if state['current_slot'] is None or x[0] >= state['current_slot']]
    if future:
        return min(future)
    integrity = board_integrity_issues(state, data)
    return min(integrity) if integrity else None


def apply_scenario(state, scenario, data):
    """Explicit, named hypothetical asset corrections; never edits the live store."""
    if not isinstance(scenario, dict) or not isinstance(scenario.get('name'), str) or not scenario['name'].strip():
        raise ValueError('Every draft scenario needs a name.')
    if set(scenario) - {'name', 'owners', 'keeper_slots', 'clear_keeper_slots'}:
        raise ValueError('Unknown scenario field')
    result = copy.deepcopy(state)
    for key in ('owners', 'keeper_slots'):
        if not isinstance(scenario.get(key, {}), dict):
            raise ValueError('Scenario owners/keeper_slots must be pick-ID maps.')
    clears = scenario.get('clear_keeper_slots', [])
    if not isinstance(clears, list):
        raise ValueError('clear_keeper_slots must be a list of pick IDs.')
    def slot(number):
        try:
            n = int(number)
        except (TypeError, ValueError):
            raise ValueError('Invalid scenario pick ID')
        if not 1 <= n <= 156 or result['slots'][n - 1]['player_id']:
            raise ValueError('Scenario cannot change an invalid/already selected pick.')
        return result['slots'][n - 1]
    for n in clears:
        slot(n).update(keeper=False, keeper_player='', player_name='')
    for n, owner in scenario.get('owners', {}).items():
        if owner not in data.teams:
            raise ValueError('Scenario owner must be a known manager.')
        slot(n)['current_team'] = owner
    for n, name in scenario.get('keeper_slots', {}).items():
        s = slot(n)
        keeper = next((k for k in data.keepers if k['player'] == name), None)
        if not keeper or keeper['team'] != s['current_team']:
            raise ValueError('Scenario keeper must belong to the specified pick owner.')
        s.update(keeper=True, keeper_player=name, player_name=name)
    names = [s['keeper_player'] for s in result['slots'] if s['keeper']]
    if len(set(names)) != len(names):
        raise ValueError('Scenario assigns a keeper to multiple assets.')
    for s in result['slots']:
        if s['keeper'] and not any(k['player'] == s['keeper_player'] and k['team'] == s['current_team'] for k in data.keepers):
            raise ValueError('Scenario changes the owner of an incompatible keeper asset.')
    result['current_slot'] = next((s['slot'] for s in result['slots'] if not s['keeper'] and not s['player_id']), None)
    return result


def wilson(successes, n):
    if not n:
        return None
    p = successes / n; z = 1.96
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0, center - half), min(1, center + half)]


class DraftModel:
    def __init__(self, engine):
        self.engine = engine
        self.data = engine.data
        self.history = self.data.history_package
        self.default_mode = 'persona' if self.history and self.history['validation']['persona_enabled_by_default'] else 'baseline'
        self.rank_cache = {}
        self.features = {}
        for p in self.data.players.values():
            bio = p.get('bio', {}); age = bio.get('age')
            young = max(-1.5, min(1.5, (26 - age) / 8)) if age is not None else 0
            rookie = float(bio['rookie']) if bio.get('rookie') is not None else 0
            pos = p['positions']
            flags = (any(x in pos for x in ('PG', 'SG')), any(x in pos for x in ('SF', 'PF')), 'C' in pos)
            z = self.engine.z[p['id']]
            self.features[p['id']] = (young, rookie, *flags, max(-2., min(2., sum(z) / 9)), tuple(max(-2., min(2., v)) for v in z))

    @lru_cache(maxsize=256)
    def fixed_factors(self, coefficients, round_number, fit, targets):
        targets = dict(targets)
        result = {}
        for pid, f in self.features.items():
            score = sum(b * x for b, x in zip(coefficients, f[:5])) + targets.get(pid, 0)
            if fit:
                score += .12 * f[5] + .015 * max(0, f[0]) * max(0, round_number - 8)
            result[pid] = math.exp(max(-3., min(3., score)))
        return result

    @lru_cache(maxsize=160)
    def roster_factors(self, needs, no_center, no_forward):
        return {pid: math.exp(.035 * sum(f[6][j] for j in needs) + .12 * (no_center and f[4]) + .08 * (no_forward and f[3]))
                for pid, f in self.features.items()}

    def mode(self, settings, requested='fit'):
        if requested == 'adp':
            return 'baseline'
        choice = settings.get('draft_model', 'auto')
        return self.default_mode if choice == 'auto' else choice

    def parameters(self, manager, round_number, settings, requested='fit', rng=None):
        mode = self.mode(settings, requested)
        if self.history:
            model = self.history['model']
            if mode == 'persona':
                fitted = model['managers'][manager]['phases'][phase(round_number)]
                means, sds = fitted['coefficients'], fitted['sd']
            else:
                fitted = model['baseline_phases'][phase(round_number)]
                means, sds = fitted['coefficients'], fitted['sd']
        else:
            means, sds = [1.4, 0, 0, 0, 0, 0], [.2, 0, 0, 0, 0, 0]
        values = list(means)
        if rng:
            # Sample profile uncertainty once per manager/phase/trial. This is a
            # ridge/Laplace approximation, not a claim of posterior calibration.
            values = [rng.gauss(m, min(.3, sd)) if j == 0 or mode == 'persona' else m for j, (m, sd) in enumerate(zip(means, sds))]
        values[0] = max(.35, min(4., values[0]))
        overrides = settings.get('manager_overrides', {}).get(manager, {})
        for j, key in enumerate(('adherence', 'young', 'rookie', 'guard', 'forward', 'center')):
            if key in overrides:
                values[j] = overrides[key]
        return values

    def weights(self, pool, roster, manager, round_number, settings, requested='fit', parameters=None, variation=.35):
        ordered = sorted(pool, key=market_key)
        coefficients = parameters or self.parameters(manager, round_number, settings, requested)
        alpha = round(max(.35, min(4., coefficients[0] * (.35 / max(.1, variation)) ** .2)), 2)
        if alpha not in self.rank_cache:
            self.rank_cache[alpha] = [(i + 1) ** -alpha for i in range(len(self.data.players) + 1)]
        ranks = self.rank_cache[alpha]
        # These are prospective assumptions, not fitted 2025 value coefficients.
        fit = requested != 'adp'
        projected = [p for p in roster if p['id'] in self.engine.z]
        category = [sum(self.engine.z[p['id']][i] for p in projected) / max(1, len(projected)) for i in range(9)]
        needs = sorted(range(9), key=lambda i: category[i])[:2]
        no_center = not any('C' in p['positions'] for p in roster)
        no_forward = not any(any(pos in p['positions'] for pos in ('SF', 'PF')) for p in roster)
        targets = settings.get('manager_overrides', {}).get(manager, {}).get('targets', {})
        fixed = self.fixed_factors(tuple(round(c, 4) for c in coefficients[1:]), min(round_number, 9) if round_number <= 9 else round_number, fit, tuple(sorted(targets.items())))
        dynamic = self.roster_factors(tuple(sorted(needs)), no_center, no_forward) if fit else None
        weights = [ranks[i] * fixed[p['id']] * (dynamic[p['id']] if dynamic else 1) for i, p in enumerate(ordered)]
        total = sum(weights)
        return ordered, [w / total for w in weights]

    def choose(self, pool, roster, manager, round_number, settings, uniform, requested='fit', parameters=None, variation=.35):
        ordered, weights = self.weights(pool, roster, manager, round_number, settings, requested, parameters, variation)
        cumulative = 0
        for p, w in zip(ordered, weights):
            cumulative += w
            if uniform <= cumulative:
                return p
        return ordered[-1]

    @lru_cache(maxsize=1250)
    def paired_noise(self, scenario, slot):
        rng = random.Random(f'paired-choice:{scenario}:{slot}')
        return {pid: -math.log(-math.log(max(1e-12, rng.random()))) for pid in sorted(self.data.players)}

    def paired_choose(self, pool, roster, manager, slot, round_number, settings, scenario, requested='fit', variation=.35):
        # Gumbel-max draws from the SAME categorical model as Monte Carlo, with
        # player-indexed common noise. Removing one candidate cannot shift every
        # other player's inverse-CDF interval and manufacture a different league.
        ordered, weights = self.weights(pool, roster, manager, round_number, settings, requested, variation=variation)
        noise = self.paired_noise(scenario, slot)
        return max(zip(ordered, weights), key=lambda pw: math.log(max(1e-15, pw[1])) + noise[pw[0]['id']])[0]

    def preview(self, state, requested='fit', variation=.35):
        number = state['current_slot']
        if number is None:
            return {'slot': None, 'choices': [], 'blocked': 'Mock draft complete.'}
        s = state['slots'][number - 1]; manager = s['current_team']
        barrier = uncertainty_barrier(state, self.data)
        if barrier and number >= barrier[0]:
            return {'slot': number, 'choices': [], 'blocked': barrier[1] + '. Correct exact assets on the board; no silent owner/keeper guess.'}
        if manager == self.data.config['team_name']:
            return {'slot': number, 'team': manager, 'choices': [], 'blocked': 'Your turn. Choose your own player before simulating more opponents.'}
        roster = self.engine.rosters(state)[manager]
        if len(roster) >= 13:
            return {'slot': number, 'team': manager, 'choices': [], 'blocked': 'Manager already has 13 players. Reconcile keeper assets.'}
        pool = [p for p in self.data.players.values() if not p['keeper'] and p['id'] not in state['drafted']]
        ordered, weights = self.weights(pool, roster, manager, int(s['round']), state['settings'], requested, variation=variation)
        choices = []
        for p, w in zip(ordered, weights):
            reasons = [('Estimated ADP' if p['adp'] is None else 'Yahoo ADP') + f" {p['market_adp']:.1f}",
                       'Learned model: ' + self.mode(state['settings'], requested)]
            if requested != 'adp':
                reasons.append('Small explicit prospective value/category/position assumptions; not learned from 2025 projections')
            if state['settings'].get('manager_overrides', {}).get(manager):
                reasons.append('Subjective manager overrides active')
            choices.append({'player_id': p['id'], 'name': p['name'], 'weight': w, 'score': math.log(max(w, 1e-12)), 'reasons': reasons})
        choices.sort(key=lambda c: c['weight'], reverse=True)
        return {'slot': number, 'team': manager, 'choices': choices, 'blocked': None,
                'model': self.mode(state['settings'], requested), 'note': 'Shared conditional-choice model. Predictive improvement and snapshot limitations are shown in Manager personas.'}

    def _trial(self, state, seed, horizons, avoid_user=None, to_end=False):
        rng = random.Random(seed)
        rosters = self.engine.rosters(state)
        candidates = [p for p in self.data.players.values() if not p['keeper'] and p['id'] not in state['drafted']]
        candidates.sort(key=lambda p: p['id'])
        pool = sorted((dict(p, market_adp=p['market_adp'] * math.exp(rng.gauss(0, .25))) if p['adp'] is None else p for p in candidates), key=market_key)
        barrier = uncertainty_barrier(state, self.data)
        snapshots, own, trace = {}, [], []
        parameters = {}
        config = state.get('simulation_config', {})
        requested, variation = config.get('model', 'fit'), config.get('randomness', .35)
        for s in state['slots']:
            uniform = rng.random()  # Common random draw per pick, even on a rerun.
            if s['player_id'] or s['keeper']:
                continue
            if barrier and s['slot'] >= barrier[0]:
                break
            if s['slot'] in horizons:
                snapshots[s['slot']] = {p['id'] for p in pool}
                if not to_end and s['slot'] == max(horizons):
                    break
            manager = s['current_team']
            if not pool or len(rosters[manager]) >= 13:
                break
            if manager == self.data.config['team_name']:
                window = [p for p in pool if p['id'] != avoid_user][:12]
                if not window:
                    break
                pick = max(window, key=lambda p: self.engine.value(p, state['settings'].get('punt', []), state['settings'].get('risk', .5)) + self.engine.need_bonus(rosters[manager], p))
                own.append((pick['id'], s['slot']))
            else:
                key = (manager, phase(int(s['round'])))
                if key not in parameters:
                    # Separate seed for parameter draws: branch differences cannot
                    # change another manager's sampled profile by consuming RNG.
                    param_rng = random.Random(f'{seed}:{manager}:{key[1]}')
                    parameters[key] = self.parameters(manager, int(s['round']), state['settings'], requested, param_rng)
                pick = self.choose(pool, rosters[manager], manager, int(s['round']), state['settings'], uniform,
                                   requested, parameters[key], variation)
            pool.remove(pick); rosters[manager].append(pick)
            trace.append({'slot': s['slot'], 'team': manager, 'player_id': pick['id']})
        return snapshots, own, trace

    def survival(self, state, trials=None):
        trials = trials or state['settings'].get('mc_trials', 300)
        scenarios = state['settings'].get('draft_scenarios', []) or [{'name': 'Confirmed assets only'}]
        available = [p['id'] for p in self.data.players.values() if not p['keeper'] and p['id'] not in state['drafted']]
        outputs = []
        seed = int(hashlib.sha256(json.dumps({'slots': state['slots'], 'settings': state['settings'],
                    'model': self.history['model'] if self.history else None, 'config': state.get('simulation_config')}, sort_keys=True).encode()).hexdigest()[:16], 16)
        for scenario in scenarios:
            hypothetical = apply_scenario(state, scenario, self.data)
            horizon = [s['slot'] for s in hypothetical['slots'] if s['current_team'] == self.data.config['team_name'] and not s['keeper'] and not s['player_id']][:2]
            barrier = uncertainty_barrier(hypothetical, self.data)
            safe = [h for h in horizon if not barrier or h < barrier[0]]
            counts = {h: Counter() for h in safe}
            later_denominators = Counter()
            for iteration in range(trials if safe else 0):
                trial_seed = seed + iteration
                snapshots, own, _ = self._trial(hypothetical, trial_seed, safe)
                first = snapshots.get(safe[0], set())
                for h, present in snapshots.items():
                    if h == safe[0]:
                        counts[h].update(present)
                    else:
                        counts[h].update(present & first)
                if len(safe) > 1:
                    later_denominators.update(first)
                    # For targets our proxy policy picked, rerun excluding that
                    # target from OUR selections only. Never reserve it against
                    # an opponent. All other targets share the original trial.
                    for pid, picked_slot in own:
                        if picked_slot < safe[1] and pid in first:
                            branch, _, _ = self._trial(hypothetical, trial_seed, safe, avoid_user=pid)
                            if pid in branch.get(safe[1], set()):
                                counts[safe[1]][pid] += 1
            estimates = {}
            for pid in available:
                entry = {}
                for j, h in enumerate(horizon):
                    n = trials if j == 0 else later_denominators[pid]
                    value = None if h not in safe or not n else counts[h][pid] / n
                    entry['next' if j == 0 else 'later'] = {'slot': h, 'probability': value,
                        'successes': counts[h][pid] if h in safe else None, 'n': n if h in safe else 0,
                        'mc_95_interval': wilson(counts[h][pid], n) if h in safe and n else None,
                        'censored': h not in safe, 'conditional': j == 1}
                estimates[pid] = entry
            # Full remaining-draft samples only when every asset is reconciled.
            paths = []
            if barrier is None and horizon:
                for i in range(min(16, trials)):
                    _, _, trace = self._trial(hypothetical, seed + 100000 + i, horizon, to_end=True)
                    paths.append(trace)
            outputs.append({'name': scenario['name'], 'barrier': {'slot': barrier[0], 'reason': barrier[1]} if barrier else None,
                            'horizons': horizon, 'trials': trials if safe else 0, 'estimates': estimates,
                            'full_remaining_paths': paths, 'full_paths_n': len(paths),
                            'asset_overrides': scenario})
        return {'model': self.mode(state['settings'], state.get('simulation_config', {}).get('model', 'fit')),
                'seed': seed, 'scenarios': outputs, 'averaged_scenarios': False,
                'notes': ['Percentages are empirical simulation frequencies, not logistic ADP heuristics.',
                          'Later survival conditions on reaching your upcoming turn and excludes the target from your own proxy choices only.',
                          'Wilson intervals describe Monte Carlo sampling noise, not real-world calibration or all model uncertainty.',
                          'Ridge parameter uncertainty is sampled; ADP measurement-date and eligibility gaps remain systematic limitations.',
                          'Missing current ADP uses a rank-derived estimate with assumed 0.25 log-scale perturbations per trial; those are not observed Yahoo values.',
                          'Named asset scenarios are not assigned probabilities or averaged. Missing asset assignments censor later horizons.',
                          'Your unrecorded future selections use a projection/position proxy, not assumed knowledge of your real choices.']}
