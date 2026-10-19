"""Decision-level benchmark: does the engine's pick beat credible alternatives?

For each sampled board state we take the engine's top recommendation and a set of
credible alternatives, then evaluate every candidate by a PAIRED remaining-draft
completion (a common continuation policy) followed by paired season simulations on
shared worlds. This isolates the *choice*, not the continuation policy.

Uncertainty is clustered by source draft: multiple states from one draft are not
independent. Read-only; never touches the live store.
"""
import math
import random
import statistics

from . import seeds
from .season_draft import SeasonDraft
from .season_world import SeasonWorld
from .season_sim import SeasonSimulator

# A candidate must beat the chosen pick by at least this many title-rate points to be
# called a materially better choice; below it we treat alternatives as noise-tied.
MATERIALITY = 0.10


def advancement(outcome):
    t = outcome['teams']['Oscar']
    return (int(bool(t['qualified'])) + int(bool(t['semifinal']))
            + int(bool(t['final'])) + int(bool(t['champion'])))


def cluster_bootstrap(values_by_draft, seed):
    keys = sorted(values_by_draft)
    if len(keys) < 3:
        return {'low': None, 'high': None, 'method': 'fewer than three draft clusters'}
    rng = random.Random(seed)
    boots = []
    for _ in range(1000):
        chosen = rng.choices(keys, k=len(keys))
        flat = [v for k in chosen for v in values_by_draft[k]]
        if flat:
            boots.append(statistics.mean(flat))
    if not boots:
        return {'low': None, 'high': None, 'method': 'no outcomes'}
    boots.sort()
    return {'low': boots[24], 'high': boots[974], 'method': 'draft-cluster bootstrap'}


class DecisionBenchmark:
    def __init__(self, engine, inputs, config, strategy, opponent_mode, continuation, candidates=4):
        self.engine = engine
        self.inputs = inputs
        self.data = engine.data
        self.config = config
        self.strategy = strategy
        self.opponent_mode = opponent_mode
        self.continuation = continuation
        self.k = candidates
        self.drafter = SeasonDraft(engine)
        self.simulator = SeasonSimulator(engine, inputs)

    def candidate_picks(self, state):
        rec = self.engine.recommend(state)
        rows = rec.get('recommendations') or []
        return [{'id': r['player']['id'], 'name': r['player']['name'], 'engine_score': r['score'],
                 'punt': list(r.get('punt') or []), 'availability_at_next': r.get('availability_at_next'),
                 'availability_later': r.get('availability_later')}
                for r in rows[:self.k]]

    def _complete(self, state, seed, first_pick):
        return self.drafter.complete(state, self.continuation, self.opponent_mode, seed,
                                     self.config.get('manager_policies'), first_pick=first_pick)

    def evaluate_state(self, entry, seed, picks=None, seasons=None):
        """Paired completion + shared-world seasons for each candidate."""
        state = entry['state']
        picks = picks or self.candidate_picks(state)
        if len(picks) < 2:
            return None
        seasons = seasons or self.config['seasons_per_draft']
        # A completion is deterministic given (board, seed, forced pick) and does NOT
        # depend on the season world, so complete ONCE per candidate and reuse it across
        # every season world (seasons are shared/paired across candidates).
        drafts = {p['id']: self._complete(state, seed, p['id']) for p in picks}
        titles = {p['id']: [] for p in picks}
        advs = {p['id']: [] for p in picks}
        for si in range(seasons):
            world = SeasonWorld(self.data, self.inputs, self.config['calendar'],
                                seeds.world_seed(self.config['seed'], self.config['seed_block'],
                                                 self.config['holdout'], entry['draft_index'], si + 9000),
                                self.config)
            for p in picks:
                out = self.simulator.run(drafts[p['id']], world, self.config)
                titles[p['id']].append(float(bool(out['teams']['Oscar']['champion'])))
                advs[p['id']].append(advancement(out))
        chosen = picks[0]['id']
        ranked = sorted(picks, key=lambda p: (statistics.mean(titles[p['id']]), statistics.mean(advs[p['id']])), reverse=True)
        best = ranked[0]['id']
        chosen_title = statistics.mean(titles[chosen])
        regret = statistics.mean(titles[best]) - chosen_title
        others = [p['id'] for p in picks[1:]]
        others_mean = statistics.mean(statistics.mean(titles[pid]) for pid in others) if others else 0.
        chosen_vs_mean = chosen_title - others_mean
        chosen_vs_second = (chosen_title - statistics.mean(titles[others[0]])) if others else 0.
        return {'draft_id': entry['draft_id'], 'draft_index': entry['draft_index'],
                'phase': entry['phase'], 'round': entry['round'], 'flags': entry.get('flags', []),
                'chosen': chosen, 'best': best, 'regret': regret,
                'chosen_vs_mean_others': chosen_vs_mean, 'chosen_vs_second': chosen_vs_second,
                'advancement_regret': statistics.mean(advs[best]) - statistics.mean(advs[chosen]),
                'mean_title': chosen_title,
                'candidates': [{'id': p['id'], 'name': p['name'], 'title': statistics.mean(titles[p['id']]),
                                'advancement': statistics.mean(advs[p['id']]),
                                'engine_score': p['engine_score'], 'punt': p['punt']} for p in picks]}

    def evaluate_candidates(self, state, candidate_ids, seed, seasons=None, world_offset=0):
        """Evaluate a FIXED candidate set at our current slot.

        Forces each candidate as our pick, completes the rest with `continuation`
        (production `live` by default), and simulates season worlds once per candidate.
        Season worlds are keyed by `seed`, so DIFFERENT drafts draw DIFFERENT worlds
        while all candidates within one call share them (paired). Pass a nonzero
        `world_offset` to draw FRESH confirmation worlds for the same seed.
        """
        seasons = seasons or self.config['seasons_per_draft']
        ids = list(dict.fromkeys(candidate_ids))
        drafts = {c: self._complete(state, seed, c) for c in ids}
        titles = {c: [] for c in ids}
        advs = {c: [] for c in ids}
        for si in range(seasons):
            world = SeasonWorld(self.data, self.inputs, self.config['calendar'],
                                seeds.world_seed(self.config['seed'], self.config['seed_block'],
                                                 self.config['holdout'], seed + world_offset, si), self.config)
            for c in ids:
                out = self.simulator.run(drafts[c], world, self.config)
                titles[c].append(float(bool(out['teams']['Oscar']['champion'])))
                advs[c].append(advancement(out))
        return {c: {'title_rate': statistics.mean(titles[c]), 'advancement': statistics.mean(advs[c]),
                    'titles': titles[c], 'advancements': advs[c],
                    'roster': drafts[c]['rosters']['Oscar'], 'punt': drafts[c]['punts']['Oscar'],
                    'name': self.data.players[c]['name'], 'adp': self.data.players[c]['market_adp']}
                for c in ids}

    def survival_check(self, entry, seed, picks=None, runs=10, opponent_mode=None):
        """Independent calibration of the engine's availability estimate.

        For each candidate we PASS at our current slot (force a different engine
        option) and observe whether opponents leave the candidate until our NEXT
        owned pick. The prediction compared is `availability_later` (survival to the
        next owned pick); `availability_at_next` in the engine means "at your current
        pick". Uses actual paired completions — a different code path from the
        engine's own survival Monte Carlo — so it is a genuine check. Pass
        `opponent_mode` to compare the engine's own model against alternatives.
        """
        state = entry['state']
        mode = opponent_mode or self.opponent_mode
        picks = picks or self.candidate_picks(state)
        if len(picks) < 2:
            return None
        my = [s['slot'] for s in state['slots']
              if s['current_team'] == self.data.config['team_name'] and not s['keeper'] and not s['player_id']]
        if len(my) < 2:
            return None
        current, nxt = my[0], my[1]
        items = []
        for c in picks:
            filler = next(p for p in picks if p['id'] != c['id'])   # we take someone else -> pass on c
            survived = 0
            for r in range(runs):
                draft = self.drafter.complete(state, self.continuation, mode,
                                              seed + 500000 + r, first_pick=filler['id'])
                taken = {t['player_id'] for t in draft['trace'] if current < t['slot'] < nxt}
                if c['id'] not in taken:
                    survived += 1
            items.append({'id': c['id'], 'name': c['name'], 'predicted': c['availability_later'],
                          'observed': survived / runs, 'filler': filler['id']})
        return {'round': entry['round'], 'phase': entry['phase'], 'opponent_mode': mode, 'items': items}

    def run(self, corpus, seed):
        results = []
        reports = []
        calibration = []
        for i, entry in enumerate(corpus):
            seed_i = seeds.draft_seed(self.config['seed'], self.config['seed_block'],
                                      self.config['holdout'], entry['draft_index']) + 31000 + i
            picks = self.candidate_picks(entry['state'])      # one recommend() call per state
            row = self.evaluate_state(entry, seed_i, picks=picks)
            if row:
                results.append(row)
            if i % 4 == 0:
                cal = self.survival_check(entry, seed_i, picks=picks)
                if cal:
                    calibration.append(cal)
        by_draft = {}
        for r in results:
            by_draft.setdefault(r['draft_id'], []).append(r['regret'])
        by_mean = {}
        by_second = {}
        for r in results:
            by_mean.setdefault(r['draft_id'], []).append(r['chosen_vs_mean_others'])
            by_second.setdefault(r['draft_id'], []).append(r['chosen_vs_second'])
        material = [r for r in results if r['regret'] >= MATERIALITY]
        any_better = [r for r in results if r['regret'] > 0]
        behind = [r for r in results if r['chosen_vs_mean_others'] < 0]
        report = {
            'states': len(results),
            'clusters': len(by_draft),
            'mean_regret': statistics.mean(r['regret'] for r in results) if results else None,
            'mean_chosen_vs_mean_others': statistics.mean(r['chosen_vs_mean_others'] for r in results) if results else None,
            'chosen_vs_mean_others_interval': cluster_bootstrap(by_mean, seed),
            'mean_chosen_vs_second': statistics.mean(r['chosen_vs_second'] for r in results) if results else None,
            'chosen_vs_second_interval': cluster_bootstrap(by_second, seed),
            'mean_advancement_regret': statistics.mean(r['advancement_regret'] for r in results) if results else None,
            'regret_interval': cluster_bootstrap(by_draft, seed),
            'regret_note': 'mean_regret selects the best of the tested alternatives, so it is an upward-biased upper bound; mean_chosen_vs_mean_others is the unbiased read.',
            'frequency_any_alternative_better': len(any_better) / len(results) if results else None,
            'frequency_materially_better': len(material) / len(results) if results else None,
            'frequency_chosen_behind_average': len(behind) / len(results) if results else None,
            'materiality': MATERIALITY,
            'by_phase': {ph: {'n': len(rows), 'mean_regret': statistics.mean(r['regret'] for r in rows),
                              'materially_better': sum(1 for r in rows if r['regret'] >= MATERIALITY) / len(rows)}
                         for ph in ('early', 'middle', 'late')
                         for rows in [[r for r in results if r['phase'] == ph]] if rows},
            'by_flag': {},
        }
        flags = sorted({f for r in results for f in r['flags']})
        for f in flags:
            rows = [r for r in results if f in r['flags']]
            report['by_flag'][f] = {'n': len(rows), 'mean_regret': statistics.mean(r['regret'] for r in rows),
                                    'materially_better': sum(1 for r in rows if r['regret'] >= MATERIALITY) / len(rows)}
        # Survival calibration: bias (observed - predicted) across sampled items.
        items = [it for c in calibration for it in c['items'] if it['predicted'] is not None]
        if items:
            report['survival_calibration'] = {
                'n': len(items),
                'mean_bias': statistics.mean(it['observed'] - it['predicted'] for it in items),
                'mean_abs_error': statistics.mean(abs(it['observed'] - it['predicted']) for it in items),
                'bins': _calibration_bins(items)}
        report['results'] = results
        report['calibration'] = calibration
        return report


def _calibration_bins(items, edges=(0, .2, .4, .6, .8, 1.01)):
    bins = []
    for lo, hi in zip(edges, edges[1:]):
        rows = [it for it in items if lo <= it['predicted'] < hi]
        if rows:
            bins.append({'range': [lo, hi], 'n': len(rows),
                         'predicted': statistics.mean(it['predicted'] for it in rows),
                         'observed': statistics.mean(it['observed'] for it in rows)})
    return bins
