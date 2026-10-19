"""Transparent draft-path proxy, not a calibrated championship probability model.

Market scenarios complete every team without duplicate players. Daily lineup selection
uses a maximum-weight independent subset of the player/slot matching graph. Opponent
future picks, ADP survival, and player availability are explicitly estimates.
"""
import itertools
import math
import statistics
import random
from datetime import date, timedelta
from functools import lru_cache
from .data import CATEGORIES
from .market import market_key

POSITIONS = ['PG', 'SG', 'G', 'SF', 'PF', 'F', 'C', 'UTIL', 'UTIL', 'UTIL']
DEFAULTS = {'streaming': True, 'playoff_priority': .85, 'risk': .5,
            'history_weight': .15, 'punt': [], 'week_weights': [1, 1, 1], 'future_keeper': .08}


def aggregate(lines):
    totals = [sum(line[i] for line in lines) for i in range(11)]
    return [totals[0] / totals[1] if totals[1] else 0,
            totals[2] / totals[3] if totals[3] else 0] + totals[4:]


def eligible(player, slot):
    pos = player['positions']
    return slot == 'UTIL' or slot in pos or (slot == 'G' and any(x in pos for x in ('PG', 'SG'))) or (slot == 'F' and any(x in pos for x in ('SF', 'PF')))


def lineup(players, quality):
    """Matroid greedy + augmenting paths: maximum-weight feasible set of starts."""
    assigned = {}

    def augment(player, visited):
        for i, slot in enumerate(POSITIONS):
            if i in visited or not eligible(player, slot):
                continue
            visited.add(i)
            if i not in assigned or augment(assigned[i], visited):
                assigned[i] = player
                return True
        return False

    for p in sorted(players, key=lambda x: (-quality(x), x['id'])):
        augment(p, set())
    return list(assigned.values())


def lineup_slots(players, quality):
    """Same greedy+aumenting matching as `lineup`, but returns {player_id: slot_name}
    so we can see which slot a player actually occupies (position vs UTIL vs bench)."""
    assigned = {}

    def augment(player, visited):
        for i, slot in enumerate(POSITIONS):
            if i in visited or not eligible(player, slot):
                continue
            visited.add(i)
            if i not in assigned or augment(assigned[i], visited):
                assigned[i] = player
                return True
        return False

    for p in sorted(players, key=lambda x: (-quality(x), x['id'])):
        augment(p, set())
    return {p['id']: POSITIONS[i] for i, p in assigned.items()}


def matchup(a, b, scales):
    """Independent normal category proxy; conservative heuristic dispersion floors."""
    probs = []
    for i, (x, y) in enumerate(zip(a, b)):
        sd = max(scales[i], .022 if i < 2 else max(abs(x), abs(y)) * .18, .5 if i >= 2 else 0)
        difference = (y - x) if i == 8 else (x - y)
        probs.append(.5 * (1 + math.erf(difference / (sd * math.sqrt(2)))))
    dist = [1.] + [0.] * 9
    for p in probs:
        dist = [dist[k] * (1 - p) + (dist[k - 1] * p if k else 0) for k in range(10)]
    return sum(dist[5:]), probs


def seed_scenarios(order, me):
    """Condition on qualifying; never remove the user from a scenario's field."""
    others = [t for t in order if t != me][:7]
    result = []
    for placement, rotation in ((0, 0), (3, 2), (5, 4)):
        field = others[rotation:] + others[:rotation]
        field.insert(placement, me)
        result.append(field)
    return result


def bracket_proxy(rosters, weekly, scales, me, weights, seed_orders=None):
    """Fixed brackets, three uncertain seeding scenarios; no reseeding.

    Averages over nearby seed permutations rather than pretending draft-day seeds
    are known. These probabilities inherit the uncalibrated category proxy.
    """
    pair_cache = {}

    def win_proxy(a, b, week):
        key = (a, b, week)
        if key not in pair_cache:
            win = matchup(weekly[a][week]['categories'], weekly[b][week]['categories'], scales)[0]
            pair_cache[key] = win
            pair_cache[b, a, week] = 1 - win
        return pair_cache[key]

    strength = {}
    for team in rosters:
        strength[team] = sum(win_proxy(team, other, w)
                             for other in rosters if other != team for w in range(3))
    order = sorted(rosters, key=lambda t: (-strength[t], t))
    # Freeze these fields across candidate comparisons. Re-sorting the bracket
    # separately for every pick can perversely reward a weaker team for dodging an
    # opponent (or omit the user from a field altogether).
    scenarios = seed_orders or seed_scenarios(order, me)
    results = []
    for seeds in scenarios:
        # Standard 1–8, 4–5 / 2–7, 3–6 fixed bracket.
        nodes = [{seeds[i]: 1.} for i in (0, 7, 3, 4, 1, 6, 2, 5)]
        for w in range(3):
            next_nodes = []
            for i in range(0, len(nodes), 2):
                left, right = nodes[i], nodes[i + 1]
                combined = {}
                for a, pa in left.items():
                    for b, pb in right.items():
                        win = win_proxy(a, b, w)
                        # User week emphasis is a preference, not altered NBA stats.
                        win = 1 / (1 + math.exp(-max(-15, min(15, math.log(max(.0001, win) / max(.0001, 1 - win)) * weights[w]))))
                        combined[a] = combined.get(a, 0) + pa * pb * win
                        combined[b] = combined.get(b, 0) + pa * pb * (1 - win)
                next_nodes.append(combined)
            nodes = next_nodes
        results.append(nodes[0].get(me, 0))
    # Contention/qualification safeguard penalizes falling below eighth, without
    # claiming to estimate regular-season qualification from sparse inputs.
    place = order.index(me) + 1
    return sum(results) / len(results), place


class Engine:
    def __init__(self, data):
        self.data = data
        self.players = data.players
        reference = sorted(self.players.values(), key=lambda p: p['rank'])[:156]
        fg_attempt = sum(p['stats'][1] for p in reference)
        ft_attempt = sum(p['stats'][3] for p in reference)
        self.fg = sum(p['stats'][0] for p in reference) / fg_attempt
        self.ft = sum(p['stats'][2] for p in reference) / ft_attempt
        raw = [self.raw(p) for p in reference]
        self.means = [statistics.mean(r[i] for r in raw) for i in range(9)]
        self.devs = [max(.01, statistics.pstdev(r[i] for r in raw)) for i in range(9)]
        self.z = {pid: [(v - self.means[i]) / self.devs[i] for i, v in enumerate(self.raw(p))]
                  for pid, p in self.players.items()}
        self.days = {}
        for g in data.games:
            d = date.fromisoformat(g['date'])
            if date(2027, 3, 1) <= d <= date(2027, 3, 21):
                self.days.setdefault(g['date'], set()).update((g['home'], g['away']))
        from .draft_model import DraftModel
        self.draft_model = DraftModel(self)

    def raw(self, p):
        s = p['stats']
        return [s[0] - self.fg * s[1], s[2] - self.ft * s[3]] + s[4:10] + [-s[10]]

    def value(self, p, punts=(), risk=.5):
        return self.cached_value(p['id'], tuple(punts), risk)

    @lru_cache(maxsize=30000)
    def cached_value(self, pid, punts, risk):
        p = self.players.get(pid)
        if p is None:
            return -3
        z = self.z.get(pid, [0] * 9)
        active = [v for i, v in enumerate(z) if CATEGORIES[i] not in punts]
        # Availability discount changes the value of positive production, not the
        # sign of negative z-scores. A scarce role still has a replacement cost.
        return sum(active) / len(active) - risk * (1 - p['gp'] / 82) * 1.5

    def availability(self, p, risk):
        # GP is a season-wide proxy, not a March injury forecast. Controls show this.
        return 1 - (.5 + risk) * (1 - p['gp'] / 82)

    def market(self, available, scenario=0):
        ordered = sorted(available, key=market_key)
        ordinal = {p['id']: i for i, p in enumerate(ordered)}
        def score(p):
            # Yahoo ADP drives known players; missing ADP uses a smoothed rank-to-
            # ADP fallback. Perturb keeper-filtered ordinals only for lookahead.
            base = ordinal[p['id']]
            jitter = math.sin(int(p['id'].split(':')[-1]) * 1.7 + scenario * 2.3) * (5 if p['adp'] is not None else 15)
            return base + jitter
        return sorted(available, key=lambda p: (score(p), p['id']))

    def opponent_choices(self, state, model='fit', randomness=.35):
        """Mock-only pick distribution: mostly ADP, modest roster/history bias.

        These weights are a practice generator, not calibrated manager forecasts.
        We never act for the user, assign unknown owners, or overwrite filled picks.
        """
        return self.draft_model.preview(state, model, randomness)

    def legacy_opponent_choices(self, state, model='fit', randomness=.35):
        """Retained only as a documented pre-persona reference; never used live."""
        slot_number = state['current_slot']
        if slot_number is None:
            return {'slot': None, 'choices': [], 'blocked': 'Mock draft complete.'}
        slot = state['slots'][slot_number - 1]
        team = slot['current_team']
        if not team:
            return {'slot': slot_number, 'choices': [], 'blocked': 'Pick owner unresolved. Resolve this slot on the board to continue.'}
        if team == self.data.config['team_name']:
            return {'slot': slot_number, 'team': team, 'choices': [], 'blocked': 'Your turn. Choose your own player before simulating more opponents.'}
        rosters = self.rosters(state)
        roster = rosters[team]
        if len(roster) >= 13:
            return {'slot': slot_number, 'team': team, 'choices': [], 'blocked': 'Manager already has 13 players. Resolve ambiguous keeper forfeitures on the board.'}
        pool = sorted((p for p in self.players.values() if not p['keeper'] and p['id'] not in state['drafted']), key=market_key)
        if not pool:
            return {'slot': slot_number, 'team': team, 'choices': [], 'blocked': 'No projected players remain.'}
        history = self.data.history.get(team, [.5] * 9)
        history_weight = state['settings'].get('history_weight', DEFAULTS['history_weight'])
        projected = [p for p in roster if p['id'] in self.z]
        # Soft needs: balance weak categories without forcing a punt or ignoring a
        # keeper's strengths. Positional coverage matters more late in the draft.
        averages = [sum(self.z[p['id']][i] for p in projected) / max(1, len(projected)) for i in range(9)]
        weights = [1 + max(-.25, min(.35, -v * .2)) for v in averages]
        choices = []
        for i, p in enumerate(pool[:12]):
            market_score = -.85 * math.log1p(i)
            category_fit = sum(self.z[p['id']][j] * weights[j] for j in range(9)) / 9
            historical = sum((history[j] - .5) * self.z[p['id']][j] for j in range(9)) / 9
            position = self.need_bonus(roster, p) * (1 + len(roster) / 13)
            score = market_score + (.25 * category_fit + history_weight * historical + position if model == 'fit' else 0)
            reasons = [('Estimated ADP from Hashtag rank' if p['adp'] is None else 'Yahoo ADP') + f" {p['market_adp']:.1f}"]
            if model == 'fit':
                if position:
                    reasons.append('Fills missing center/forward coverage')
                needs = sorted(range(9), key=lambda j: weights[j] * self.z[p['id']][j], reverse=True)[:2]
                reasons.append('Category fit: ' + ', '.join(CATEGORIES[j] for j in needs))
                if team in self.data.history and history_weight:
                    reasons.append('Small historical category-preference adjustment')
            choices.append({'player_id': p['id'], 'name': p['name'], 'score': score, 'reasons': reasons})
        peak = max(c['score'] for c in choices)
        probabilities = [math.exp((c['score'] - peak) / randomness) for c in choices]
        total = sum(probabilities)
        for c, probability in zip(choices, probabilities):
            c['weight'] = probability / total
        choices.sort(key=lambda c: c['score'], reverse=True)
        return {'slot': slot_number, 'team': team, 'choices': choices,
                'model': model, 'blocked': None, 'note': 'Practice simulation weights, not calibrated pick probabilities.'}

    @staticmethod
    def sample_opponent(prediction, seed, revision):
        rng = random.Random(f'{seed}:{revision}:{prediction["slot"]}')
        return rng.choices(prediction['choices'], weights=[c['weight'] for c in prediction['choices']], k=1)[0]

    def strategy_summary(self, state, result):
        roster = self.rosters(state)[self.data.config['team_name']]
        projected = [p for p in roster if p['id'] in self.z]
        category_values = [sum(self.z[p['id']][i] for p in projected) / max(1, len(projected)) for i in range(9)]
        order = sorted(range(9), key=lambda i: category_values[i], reverse=True)
        locked = state['settings'].get('punt', [])
        leading = result.get('builds', [{}])[0] if result.get('builds') else {}
        return {'locked_punt': locked, 'suggested_punt': leading.get('punt', []),
                'strengths': [CATEGORIES[i] for i in order[:3]],
                'needs': [CATEGORIES[i] for i in reversed(order[-3:]) if CATEGORIES[i] not in locked],
                'roster_count': len(roster), 'category_values': category_values,
                'note': 'Current-roster per-game category impacts, relative to the reference player pool. Auto punt suggestions come from hypothetical completed draft paths, not a committed strategy.'}

    def position_fit(self, roster, candidate, punts, risk):
        """How a candidate fits our position slots and what he does to projected usable
        starts / blocked games. No arbitrary center cap; UTIL-only starts are flagged.
        Positions are provisional Yahoo eligibility (verify in the draft room)."""
        base_ids = tuple(sorted(x['id'] for x in roster if x['id'] in self.z))
        aug = [x for x in roster if x['id'] != candidate['id'] and x['id'] in self.z]
        aug.append(candidate)
        aug_ids = tuple(sorted(x['id'] for x in aug))
        quality = lambda q: self.value(q, tuple(punts), risk) + 3
        base_w = self.weekly_totals(base_ids, tuple(punts), risk)
        aug_w = self.weekly_totals(aug_ids, tuple(punts), risk)
        d_starts = sum(w['usable_starts'] for w in aug_w) - sum(w['usable_starts'] for w in base_w)
        d_blocked = sum(w['blocked_games'] for w in aug_w) - sum(w['blocked_games'] for w in base_w)
        slot = lineup_slots(aug, quality).get(candidate['id'])
        vals = [sum(self.z[x['id']][j] for x in aug) / max(1, len(aug)) for j in range(9)]
        order = sorted(range(9), key=lambda j: vals[j], reverse=True)
        pos = set(candidate['positions'])
        role = ('C-only big' if pos == {'C'} else 'multi-position big' if 'C' in pos
                else 'forward' if pos & {'SF', 'PF'} else 'guard' if pos & {'PG', 'SG'} else 'wing')
        return {'role': role, 'positions': list(candidate['positions']),
                'start_slot': slot or 'bench', 'util_dependent': slot == 'UTIL',
                'delta_starts': round(float(d_starts), 2), 'delta_blocked': round(float(d_blocked), 2),
                'after_strengths': [CATEGORIES[j] for j in order[:3]],
                'after_needs': [CATEGORIES[j] for j in reversed(order[-3:])]}

    def team_analysis(self, state, settings=None):
        """Recorded-roster analysis, INDEPENDENT of any recommendation/build.

        Computes every team's projected weekly totals (weeks 18-20), per-team roster
        completeness, and our win proxy vs each opponent with per-category edges. Works
        on a completed or incomplete board and never invents hypothetical completions.
        """
        settings = dict(DEFAULTS, **(settings or {}))
        me = self.data.config['team_name']
        rosters = self.rosters(state)
        weekly = {}
        completeness = {}
        for team, roster in rosters.items():
            ids = tuple(sorted(p['id'] for p in roster if p['id'] in self.z))
            punts = tuple(settings['punt']) if team == me else ()
            weeks = self.weekly_totals(ids, punts, settings['risk'])
            weekly[team] = [{'categories': list(w['categories']), 'totals': list(w['totals']),
                             'usable_starts': w['usable_starts'], 'blocked_games': w['blocked_games']} for w in weeks]
            projected = sum(1 for p in roster if p['id'] in self.z)
            completeness[team] = {'players': len(roster), 'projected': projected,
                                  'unprojected': len(roster) - projected,
                                  'complete': len(roster) == self.data.config['rounds']}
        scales = [max(.012 if i < 2 else 1,
                      statistics.pstdev(weekly[t][w]['categories'][i] for t in weekly for w in range(3)) * .65)
                  for i in range(9)]
        matchups = []
        for team in self.data.teams:
            if team == me:
                continue
            rows = []
            for w in range(3):
                my_cat = weekly[me][w]['categories']; opp_cat = weekly[team][w]['categories']
                win, edges = matchup(my_cat, opp_cat, scales)
                rows.append({'week': w, 'win_proxy': win, 'category_edges': edges,
                             'my_categories': my_cat, 'opp_categories': opp_cat,
                             'my_totals': weekly[me][w]['totals'], 'opp_totals': weekly[team][w]['totals']})
            matchups.append({'team': team, 'weeks': rows})
        return {'team': me, 'week_labels': ['Quarterfinal · wk18', 'Semifinal · wk19', 'Final · wk20'],
                'categories': CATEGORIES,
                'own': {'weeks': weekly[me], 'completeness': completeness[me], 'punts': list(settings['punt'])},
                'teams': {t: {'weeks': weekly[t], 'completeness': completeness[t]} for t in weekly},
                'matchups': matchups, 'recorded': True,
                'note': 'Recorded rosters only — no hypothetical completions. Uncalibrated win proxy; category correlations and exact ties are not modeled.'}

    def rosters(self, state):
        result = {t: [p for p in self.players.values() if p['keeper'] == t] for t in self.data.teams}
        custom = {p['id']: p for p in state['custom_players']}
        for s in state['slots']:
            if s['player_id'] and s['current_team'] in result:
                result[s['current_team']].append(self.players.get(s['player_id']) or custom[s['player_id']])
        return result

    def simulate(self, state, market, punts, settings, candidate=None, scenario=0, candidate_slot=None, trace=None, first_pick=None):
        rosters = self.rosters(state)
        me = self.data.config['team_name']
        next_slot = next((s['slot'] for s in state['slots'] if s['current_team'] == me and not s['keeper'] and not s['player_id']), None)
        target_slot = candidate_slot or next_slot
        immediate = candidate is not None and target_slot == next_slot
        # Immediate recommendations condition on this candidate reaching our next
        # turn. A WAIT branch must leave it available for opponents to take.
        pool = [p for p in market if (not immediate or p['id'] != candidate['id']) and (not first_pick or p['id'] != first_pick['id'])]
        selected = False
        from .draft_model import uncertainty_barrier
        barrier = uncertainty_barrier(state, self.data)
        rng = random.Random('paired-draft:' + str(scenario))
        for slot in state['slots']:
            uniform = rng.random()
            if slot['keeper'] or slot['player_id'] or not pool:
                continue
            if barrier and slot['slot'] >= barrier[0]:
                break
            team = slot['current_team']
            if team not in rosters:
                break
            if len(rosters[team]) >= 13:
                # Duplicate keeper costs unresolved: never build a 14-player team.
                continue
            if team == me and first_pick and slot['slot'] == next_slot:
                pick = first_pick
            elif team == me and candidate and slot['slot'] == target_slot and (immediate or candidate in pool):
                pick = candidate
                selected = True
                if not immediate:
                    pool.remove(pick)
            elif team == me:
                # Explicitly pass on the target at the first turn in a wait plan,
                # but don't protect it from any subsequent opponent selection.
                window = [p for p in pool if not (candidate and not immediate and slot['slot'] == next_slot and p['id'] == candidate['id'])][:12]
                pick = max(window, key=lambda p: self.value(p, punts, settings['risk']) + self.need_bonus(rosters[team], p))
                pool.remove(pick)
            else:
                config = state.get('simulation_config', {})
                pick = self.draft_model.paired_choose(pool, rosters[team], team, slot['slot'], int(slot['round']), settings, scenario,
                    config.get('model', 'fit'), variation=config.get('randomness', .35))
                pool.remove(pick)
            rosters[team].append(pick)
            if trace is not None:
                trace[pick['id']] = {'team': team, 'slot': slot['slot']}
        # Only resolved team-owned slots determine modeled selections.
        return rosters, pool, selected

    @staticmethod
    def need_bonus(roster, p):
        if 'C' in p['positions'] and not any('C' in x['positions'] for x in roster):
            return .35
        if any(pos in p['positions'] for pos in ('SF', 'PF')) and not any(any(pos in x['positions'] for pos in ('SF', 'PF')) for x in roster):
            return .2
        return 0

    @lru_cache(maxsize=12000)
    def weekly_totals(self, ids, punts, risk):
        players = [self.players[pid] for pid in ids if pid in self.players]
        weeks = []
        quality = lambda p: self.value(p, punts, risk) + 3
        for w in range(3):
            lines = []
            starts = 0.
            scheduled = 0
            selected_counts = {}
            if self.days:
                start = date(2027, 3, 1) + timedelta(days=w * 7)
                for offset in range(7):
                    teams = self.days.get((start + timedelta(days=offset)).isoformat(), set())
                    playing = [p for p in players if p['team'] in teams]
                    scheduled += len(playing)
                    for p in lineup(playing, quality):
                        a = self.availability(p, risk)
                        starts += a
                        lines.append([v * a for v in p['stats']])
                        selected_counts[p['id']] = selected_counts.get(p['id'], 0) + 1
            else:
                for p in players:
                    n = self.data.weekly.get(p['team'], [0] * 3)[w]
                    scheduled += n
                    a = n * self.availability(p, risk)
                    starts += a
                    lines.append([v * a for v in p['stats']])
                    selected_counts[p['id']] = n
            weeks.append({'categories': aggregate(lines), 'totals': [sum(line[i] for line in lines) for i in range(11)],
                          'usable_starts': starts, 'scheduled_games': scheduled,
                          'blocked_games': scheduled - sum(selected_counts.values()), 'selected_counts': selected_counts})
        return weeks

    def forecast(self, rosters, punts, settings, remaining, streaming):
        weekly = {}
        plans = {}
        for team, roster in rosters.items():
            team_punts = punts if team == self.data.config['team_name'] else ()
            ids = tuple(sorted(p['id'] for p in roster))
            baseline = self.weekly_totals(ids, tuple(team_punts), settings['risk'])
            weekly[team] = [dict(w, categories=list(w['categories']), totals=list(w['totals'])) for w in baseline]
            plans[team] = []
            if streaming and remaining and self.days:
                for w in range(3):
                    plan = self.stream(roster, remaining, w, team_punts, settings['risk'])
                    plans[team].append(plan)
                    totals = [max(0, x + delta) for x, delta in zip(baseline[w]['totals'], plan['delta'])]
                    weekly[team][w]['totals'] = totals
                    weekly[team][w]['categories'] = aggregate([totals])
                    weekly[team][w]['usable_starts'] += plan['net_starts']
            else:
                plans[team] = [{'adds': 0, 'net_starts': 0, 'delta': [0] * 11} for _ in range(3)]
        return weekly, plans

    def stream(self, roster, remaining, week, punts, risk):
        return self.cached_stream(tuple(sorted(p['id'] for p in roster if p['projected'])),
                                  tuple(sorted(p['id'] for p in remaining)), week, tuple(punts), risk)

    @lru_cache(maxsize=12000)
    def cached_stream(self, roster_ids, remaining_ids, week, punts, risk):
        """A replaceable-slot schedule ceiling discounted 50% for execution/competition.

        Remove a low-value roster player and select free agents from a broad, modest
        quality band for at most four same-day free-agent adds. No waiver targets are
        promised. Opponents get the same assumed capability.
        """
        projected = [self.players[pid] for pid in roster_ids]
        remaining = [self.players[pid] for pid in remaining_ids]
        if not projected:
            return {'adds': 0, 'net_starts': 0, 'delta': [0] * 11}
        drop = min(projected, key=lambda p: self.value(p, punts, risk))
        core = [p for p in projected if p['id'] != drop['id']]
        choices = sorted(remaining, key=lambda p: self.value(p, punts, risk), reverse=True)
        # Ignore the best handful: they are particularly unlikely to be immediately
        # available or uncontested months later. Bound pool quality conservatively.
        choices = choices[8:48] or choices
        original = self.weekly_totals(tuple(sorted(p['id'] for p in projected)), tuple(punts), risk)[week]
        start = date(2027, 3, 1) + timedelta(days=7 * week)
        selected = []
        current = drop
        adds = 0
        lines = []
        starts = 0
        quality = lambda p: self.value(p, punts, risk) + 3
        for offset in range(7):
            teams = self.days.get((start + timedelta(days=offset)).isoformat(), set())
            future_teams = self.days.get((start + timedelta(days=min(6, offset + 1))).isoformat(), set())
            if current['team'] not in teams and adds < 4:
                options = [p for p in choices if p['team'] in teams and p['id'] not in selected]
                if options:
                    option = max(options, key=lambda p: quality(p) + (1 if p['team'] in future_teams else 0))
                    trial = lineup([p for p in core if p['team'] in teams] + [option], quality)
                    if any(p['id'] == option['id'] for p in trial):
                        current = option
                        selected.append(option['id'])
                        adds += 1
            for p in lineup([p for p in core + [current] if p['team'] in teams], quality):
                a = self.availability(p, risk)
                starts += a
                lines.append([v * a for v in p['stats']])
        totals = [sum(line[i] for line in lines) for i in range(11)]
        delta = [x - y for x, y in zip(totals, original['totals'])]
        # Only award a plan that improves active category impact; preserve harmful
        # TO and ratio effects rather than independently clipping category deltas.
        after = aggregate([totals]); before = original['categories']
        impact = sum(((-1 if i == 8 else 1) * (after[i] - before[i]) / max(self.devs[i] * 35, .02 if i < 2 else 1)) for i in range(9) if CATEGORIES[i] not in punts)
        if impact <= 0:
            return {'adds': 0, 'net_starts': 0, 'delta': [0] * 11}
        return {'adds': adds, 'net_starts': (starts - original['usable_starts']) * .5,
                'delta': [v * .5 for v in delta]}

    def comparison_context(self, rosters, punts, settings):
        """Common dispersion and seeded fields for paired pick counterfactuals."""
        weekly, _ = self.forecast(rosters, punts, settings, [], False)
        scales = [max(.012 if i < 2 else 1, statistics.pstdev(weekly[t][w]['categories'][i] for t in weekly for w in range(3)) * .65) for i in range(9)]
        strength = {t: sum(matchup(weekly[t][w]['categories'], weekly[o][w]['categories'], scales)[0]
                          for o in weekly if o != t for w in range(3)) for t in weekly}
        order = sorted(strength, key=lambda t: (-strength[t], t))
        return {'scales': scales, 'seeds': seed_scenarios(order, self.data.config['team_name'])}

    def evaluate(self, rosters, punts, settings, remaining, context=None):
        me = self.data.config['team_name']
        baseline, _ = self.forecast(rosters, punts, settings, remaining, False)
        context = context or self.comparison_context(rosters, punts, settings)
        scales = context['scales']
        no_stream, place = bracket_proxy(rosters, baseline, scales, me, settings['week_weights'], context['seeds'])
        if settings['streaming']:
            streamed, plans = self.forecast(rosters, punts, settings, remaining, True)
            with_stream, _ = bracket_proxy(rosters, streamed, scales, me, settings['week_weights'], context['seeds'])
        else:
            streamed, plans, with_stream = baseline, {me: []}, no_stream
        matchup_rows = []
        for team in rosters:
            if team == me:
                continue
            matchup_rows.append({'team': team, 'weeks': [
                {'win_proxy': matchup(streamed[me][w]['categories'], streamed[team][w]['categories'], scales)[0],
                 'category_edges': matchup(streamed[me][w]['categories'], streamed[team][w]['categories'], scales)[1]}
                for w in range(3)]})
        # Regular-season safety is a soft contention penalty, not a fabricated
        # probability of qualifying. Full-season simulation is not implemented.
        safety = max(0, place - 6) * .006 * (1 - settings['playoff_priority'])
        # Include all opponents as a small uncertain-field safeguard. A manager
        # outside today's hypothetical top eight may become a contender after
        # receiving the elite player we passed on. No arbitrary 'denial bonus':
        # the actual changed roster enters the same matchup calculation.
        def field_score(weeks):
            total_weight = sum(settings['week_weights'])
            log_score = sum(settings['week_weights'][w] * math.log(max(.0001, statistics.mean(
                matchup(weeks[me][w]['categories'], weeks[t][w]['categories'], scales)[0] for t in weeks if t != me))) for w in range(3))
            return math.exp(3 * log_score / total_weight)
        baseline_index = .8 * no_stream + .2 * field_score(baseline)
        streaming_index = .8 * with_stream + .2 * field_score(streamed)
        return {'score': streaming_index - safety, 'baseline': baseline_index, 'streamed': streaming_index,
                'rank_proxy': place, 'weeks': streamed[me], 'baseline_weeks': baseline[me],
                'stream_plans': plans[me], 'matchups': matchup_rows,
                'roster': [p['id'] for p in rosters[me]]}

    def recommend(self, state):
        source_state = state
        valuation_scenario = None
        scenarios = state['settings'].get('draft_scenarios', [])
        if len(scenarios) == 1:
            from .draft_model import apply_scenario
            state = apply_scenario(state, scenarios[0], self.data)
            valuation_scenario = scenarios[0]['name']
        settings = dict(DEFAULTS, **state['settings'])
        me = self.data.config['team_name']
        available = [p for p in self.players.values() if not p['keeper'] and p['id'] not in state['drafted']]
        rosters = self.rosters(state)
        actual = self.weekly_totals(tuple(sorted(p['id'] for p in rosters[me])), tuple(settings['punt']), settings['risk'])
        my_slots = [s['slot'] for s in state['slots'] if s['current_team'] == me and not s['keeper'] and not s['player_id']]
        unresolved = [s['slot'] for s in state['slots'] if not s['current_team']]
        warnings = list(self.data.warnings)
        if unresolved:
            warnings.append('Unresolved ownership at slots ' + ', '.join(map(str, unresolved)) + '; forecasts stop before unresolved assets, rather than inventing selections.')
        counts = {t: sum(s['keeper'] and s['current_team'] == t for s in state['slots']) for t in self.data.teams}
        if any(v not in (2, 3) for v in counts.values()):
            warnings.append('Keeper forfeitures not fully reconciled. Opponent completions capped at 13; future timing is approximate.')
        if any(not p['projected'] for r in rosters.values() for p in r):
            warnings.append('Unlisted selections have no projected contribution; team forecasts are incomplete.')
        if not my_slots or not available:
            return {'recommendations': [], 'later_targets': [], 'builds': [], 'actual_weeks': actual, 'warnings': warnings,
                    'settings': settings, 'next_pick': None, 'my_slots': my_slots}
        survival_report = self.draft_model.survival(source_state)
        market = self.market(available)
        alternate_market = self.market(available, scenario=1)
        reference_rosters, _, _ = self.simulate(state, market, tuple(settings['punt']), settings)
        alternate_reference, _, _ = self.simulate(state, alternate_market, tuple(settings['punt']), settings, scenario=1)
        contexts = [self.comparison_context(reference_rosters, tuple(settings['punt']), settings),
                    self.comparison_context(alternate_reference, tuple(settings['punt']), settings)]
        outcome_cache = {}

        def evaluate_path(completed, punts, remaining, scenario):
            # Many failed wait plans or reordered selections lead to the same
            # final league. Reuse that world, not its pick-order trace. Scope the
            # cache to this immutable draft snapshot and common contexts.
            key = (tuple((t, tuple(sorted(p['id'] for p in completed[t]))) for t in sorted(completed)),
                   tuple(punts), tuple(sorted(p['id'] for p in remaining)), scenario)
            if key not in outcome_cache:
                outcome_cache[key] = self.evaluate(completed, punts, settings, remaining, contexts[scenario])
            return dict(outcome_cache[key])
        # Auto considers all balanced, one-, and two-punt builds. The final candidate
        # comparison uses the strongest few draft paths; UI names this approximation.
        strategies = [tuple(settings['punt'])] if settings['punt'] else [()] + [(c,) for c in CATEGORIES] + list(itertools.combinations(CATEGORIES, 2))
        screened = []
        for punts in strategies:
            completed, rest, _ = self.simulate(state, market, punts, settings)
            # Screening uses projected roster category impact; full daily/bracket
            # comparison follows for top paths plus balanced as a control.
            totals = [sum(self.z[p['id']][i] for p in completed[me] if p['id'] in self.z) for i in range(9)]
            edges = sorted(totals, reverse=True)
            screen = sum(edges[:6]) - max(0, -edges[4]) * 2
            screened.append((screen, punts, completed, rest))
        screened.sort(key=lambda x: x[0], reverse=True)
        finalists = screened[:3]
        if not settings['punt'] and not any(not x[1] for x in finalists):
            finalists[-1] = next(x for x in screened if not x[1])
        builds = []
        alternate_bases = {}
        base_cache = {}

        def base_build(punts):
            if punts not in base_cache:
                completed, rest, _ = self.simulate(state, market, punts, settings)
                primary = evaluate_path(completed, punts, rest, 0)
                other, other_rest, _ = self.simulate(state, alternate_market, punts, settings, scenario=1)
                secondary = evaluate_path(other, punts, other_rest, 1)
                base_cache[punts] = {'punt': list(punts), **primary}
                alternate_bases[punts] = secondary['score']
            return base_cache[punts]

        for _, punts, completed, rest in finalists:
            builds.append(base_build(punts))
        builds.sort(key=lambda b: b['score'], reverse=True)
        candidates = {}
        for build in builds:
            for p in sorted(available, key=lambda p: self.value(p, build['punt'], settings['risk']), reverse=True)[:14]:
                candidates[p['id']] = p
        for p in market[:12]:
            candidates[p['id']] = p
        rows = []
        for p in candidates.values():
            best = None
            variants = [tuple(b['punt']) for b in builds]
            if not settings['punt']:
                weakest = sorted(range(9), key=lambda i: self.z[p['id']][i])
                negative = [CATEGORIES[i] for i in weakest if self.z[p['id']][i] < 0]
                # Candidate-specific builds matter: Giannis must be evaluated in
                # FT%-punt paths even if those weren't the baseline's finalists.
                if negative:
                    variants.append(tuple(negative[:1]))
                if len(negative) > 1:
                    variants.append(tuple(negative[:2]))
            variants = list(dict.fromkeys(tuple(c for c in CATEGORIES if c in v) for v in variants))
            for punts in variants:
                trace = {}
                completed, rest, selected = self.simulate(state, market, punts, settings, candidate=p, trace=trace)
                if not selected:
                    continue
                result = evaluate_path(completed, punts, rest, 0)
                # Late-round future value is only a small, explicitly heuristic
                # youth/role signal; no fabricated next-season projection.
                keeper_hint = settings['future_keeper'] * .002 * max(0, int(state['slots'][my_slots[0] - 1]['round']) - 8) * max(0, self.value(p, punts, settings['risk']))
                result['score'] += keeper_hint
                if best is None or result['score'] > best['score']:
                    best = dict(result, punt=list(punts), allocation=trace)
            if best is None:
                continue
            # Recheck every shortlisted candidate in a second uncertain market
            # order. Prefer average performance with a small fragility penalty,
            # rather than rewarding one favorable hypothetical completion.
            alt_rosters, alt_rest, _ = self.simulate(state, alternate_market, tuple(best['punt']), settings, candidate=p, scenario=1)
            alternate = evaluate_path(alt_rosters, tuple(best['punt']), alt_rest, 1)
            scenario_scores = [best['score'], alternate['score']]
            best['score'] = sum(scenario_scores) / 2 - .15 * abs(scenario_scores[0] - scenario_scores[1])
            best['baseline'] = (best['baseline'] + alternate['baseline']) / 2
            best['streamed'] = (best['streamed'] + alternate['streamed']) / 2
            scenario_estimates = [{'name': s['name'], **s['estimates'][p['id']]} for s in survival_report['scenarios']]
            # A single scenario can have a point estimate; distinct asset scenarios
            # never get arbitrary weights or a silently averaged percentage.
            survival = scenario_estimates[0].get('next', {}).get('probability') if len(scenario_estimates) == 1 else None
            later = scenario_estimates[0].get('later', {}).get('probability') if len(scenario_estimates) == 1 else None
            baseline_build = base_build(tuple(best['punt']))
            baseline_alt = alternate_bases[tuple(best['punt'])]
            baseline_score = (baseline_build['score'] + baseline_alt) / 2 - .15 * abs(baseline_build['score'] - baseline_alt)
            reasons = []
            strong = sorted(range(9), key=lambda i: self.z[p['id']][i], reverse=True)
            reasons.append('Strongest per-game impacts: ' + ', '.join(CATEGORIES[i] for i in strong[:3]))
            reasons.append('Balanced path' if not best['punt'] else 'Best tested path punts ' + ', '.join(best['punt']))
            weeks = self.data.weekly[p['team']]
            reasons.append('Scheduled playoff games: ' + '/'.join(map(str, weeks)))
            if p['adp'] is None:
                reasons.append('No ADP: future availability uses uncertain source-rank fallback')
            else:
                reasons.append('Yahoo ADP reference ' + str(p['adp']) + '; not directly comparable to keeper draft slot')
            passed_players = [{'player_id': q['id'], 'name': q['name'], **best['allocation'][q['id']]}
                              for q in sorted(available, key=market_key)[:4]
                              if q['id'] != p['id'] and q['id'] in best['allocation']]
            rows.append({'player': p, 'value': self.value(p, best['punt'], settings['risk']),
                         'fit': self.position_fit(rosters[me], p, best['punt'], settings['risk']),
                         'equal_value': self.value(p, (), 0), 'punt': best['punt'],
                         'score': best['score'], 'baseline_score': best['baseline'], 'streamed_score': best['streamed'],
                         'score_range': [min(scenario_scores), max(scenario_scores)],
                         'wait_comparison': None, 'passed_market_players': passed_players,
                         'marginal': best['score'] - baseline_score,
                         'streaming_sensitive': abs(best['streamed'] - best['baseline']) > .02,
                         'availability_at_next': survival, 'availability_later': later, 'survival_scenarios': scenario_estimates,
                         'scheduled_games': weeks, 'reasons': reasons,
                         'category_z': self.z[p['id']], 'completed_roster': best['roster'],
                         'weeks': best['weeks'], 'matchups': best['matchups'],
                         'keeper_next_round': max(1, int(state['slots'][my_slots[0] - 1]['round']) - 1)})
        rows.sort(key=lambda r: r['score'], reverse=True)
        if len(my_slots) > 1:
            # Do not let a weak greedy 'alternative now' make every wait plan look
            # bad. Compare several of the strongest evaluated premium actions.
            premium_ids = {p['id'] for p in sorted(available, key=market_key)[:10]}
            premium = [r for r in rows if r['player']['id'] in premium_ids]
            for row in rows:
                alternatives = [r['player'] for r in premium if r['player']['id'] != row['player']['id']][:3]
                wait = None
                for first_pick in alternatives:
                    wait_results, wait_selected = [], []
                    for scenario, order in enumerate((market, alternate_market)):
                        other, rest, selected_later = self.simulate(state, order, tuple(row['punt']), settings,
                            candidate=row['player'], candidate_slot=my_slots[1], first_pick=first_pick)
                        outcome = evaluate_path(other, tuple(row['punt']), rest, scenario)
                        wait_results.append(outcome['score'])
                        wait_selected.append(selected_later)
                    wait_score = sum(wait_results) / 2 - .15 * abs(wait_results[0] - wait_results[1])
                    option = {'score': wait_score, 'advantage': wait_score - row['score'],
                              'target_slot': my_slots[1], 'survived_scenarios': sum(wait_selected), 'scenarios': 2,
                              'alternative_now': first_pick['id'],
                              'preferred': sum(wait_selected) >= 1 and wait_score >= row['score'] - .005}
                    # Prefer the best plan that actually obtains this player later;
                    # otherwise retain the strongest fallback-only comparison.
                    if wait is None or (option['preferred'], option['score']) > (wait['preferred'], wait['score']):
                        wait = option
                row['wait_comparison'] = wait
                if wait:
                    probabilities = [s.get('later', {}).get('probability') for s in row['survival_scenarios']]
                    # Waiting is only promoted when it survives the playoff-value
                    # comparison AND simulation-based availability is adequate in
                    # every explicitly named asset scenario. Scarcity cannot turn
                    # a weak-fit player into a recommendation by itself.
                    wait['survival_supported'] = all(p is not None and p >= .5 for p in probabilities)
                    wait['preferred'] = wait['preferred'] and wait['survival_supported']
                if wait:
                    row['reasons'].append(('Prefer targeting later' if wait['preferred'] else 'Pick-now path remains preferred') +
                                          f": take {self.players[wait['alternative_now']]['name']} now and target this player at #{wait['target_slot']}; obtained it in {wait['survived_scenarios']}/2 drafts.")
        immediate = [r for r in rows if not r['wait_comparison'] or not r['wait_comparison']['preferred']]
        later_targets = [r for r in rows if r['wait_comparison'] and r['wait_comparison']['preferred']]
        if not immediate and later_targets:
            policy = max(later_targets, key=lambda r: r['wait_comparison']['score'])
            first = next(r for r in rows if r['player']['id'] == policy['wait_comparison']['alternative_now'])
            immediate = [first]
            later_targets = [r for r in later_targets if r is not first]
            first['reasons'].append('First action in the strongest tested wait plan; no clear standalone pick-now winner.')
        # Two-point model-resolution guard: tiny differences in these uncalibrated
        # indices do not establish that a large market reach is justified. Within
        # each near-equal band, prefer market scarcity rather than false precision.
        ranked = []
        while immediate:
            anchor = immediate[0]['score']
            group = [r for r in immediate if anchor - r['score'] <= .02]
            def scarcity(row):
                probs = [s.get('later', {}).get('probability') for s in row['survival_scenarios']]
                return (min(probs) if probs and all(p is not None for p in probs) else .5, market_key(row['player']))
            group.sort(key=scarcity)
            for r in group:
                r['market_tiebreak'] = len(group) > 1
                ranked.append(r)
            immediate = [r for r in immediate if r not in group]
        immediate = ranked
        if immediate:
            leading = base_build(tuple(immediate[0]['punt']))
            builds = [leading] + [b for b in builds if b['punt'] != leading['punt']]
        from .draft_model import uncertainty_barrier
        barrier = uncertainty_barrier(state, self.data)
        return {'recommendations': immediate[:15], 'later_targets': later_targets[:10], 'builds': builds, 'actual_weeks': actual,
                'candidate_audit': {r['player']['id']: {'name': r['player']['name'], 'wait_comparison': r['wait_comparison'],
                    'survival_scenarios': r['survival_scenarios']} for r in rows},
                'valuation_incomplete': bool(barrier), 'valuation_barrier': {'slot': barrier[0], 'reason': barrier[1]} if barrier else None,
                'valuation_scenario': valuation_scenario,
                'my_slots': my_slots, 'next_pick': my_slots[0], 'warnings': warnings,
                'settings': settings, 'strategies_screened': len(strategies), 'candidates_tested': len(candidates), 'market_scenarios': 2,
                'survival': survival_report,
                'model_notes': [
                    'Comparative bracket proxy, NOT calibrated championship odds. Independent category normal approximations; category covariance and exact tie rules not modeled.',
                    'Three hypothetical seeded fields frozen across candidates within each market scenario, conditional on qualifying. Category dispersion is frozen too; no reward for candidate-specific reseeding.',
                    'Path indices blend 80% fixed-field bracket proxy and 20% all-opponent matchup proxy to account for uncertainty about which teams qualify. Passing an elite changes the receiving opponent roster; no arbitrary denial bonus is added.',
                    'Draft paths use keeper-filtered ADP/rank order and small preference windows, not actual future picks. Shortlist screening is approximate.',
                    'Each candidate is checked in two hypothetical market orders. Scores average them with a small fragility penalty; displayed ranges are scenario spread, not confidence intervals.',
                    'Every candidate is also compared with taking another player now and targeting it at the next owned pick. The wait branch does not reserve it against opponents; preferred wait plans are shown separately, not as draft-now recommendations.',
                    'Wait plans compare up to three evaluated premium alternatives now, not a single greedy substitute. Within two index points, market scarcity breaks ties; this is an explicit model-resolution safeguard, not a statistical confidence interval.',
                    'Candidate-specific one- and two-punt paths are tested in addition to baseline strategy finalists. These and greedy future selections remain approximations, not an exhaustive draft search.',
                    'GP/82 is a season availability proxy, not a March forecast. No speculative player-specific rest or injury facts.',
                    'Daily matching selects starts by build value, then discounts appearances. Unexpected absences and replacements are not fully optimized.',
                    'Streaming rotates one replaceable slot, at most four adds, discounted 50%. All opponents receive the same capability; competition is approximated, not simulated.',
                    'Future keeper adjustment is a small late-round production tie-breaker, not a next-year upside forecast. Round-1 and drop/re-add mechanics require verification.',
                    'Player survival uses Monte Carlo conditional-choice simulations, not the former logistic survival heuristic. Persona effects are validation-gated; user overrides are separate assumptions.',
                    'Only two paired league paths are used for the expensive playoff-value comparison. Hundreds of survival samples do not calibrate the playoff index. Unresolved assets truncate those league paths; their rosters are partial, not claimed complete.',
                ]}
