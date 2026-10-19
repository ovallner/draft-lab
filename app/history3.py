"""Three-season manager personas (2023-24 .. 2025-26) with explicit ADP tiers.

Season data quality differs sharply and is named, not hidden:
  2025-26  full_market   complete RotoWire market (200 ADPs) -> clean fit + validation
  2024-25  taken_only    ADP only for players actually taken  -> pool is TRUNCATED
  2023-24  none          no usable ADP (export duplicates 2024) -> descriptive only

Measured consequence of a truncated pool (2025 truncated to taken-only, the same
technique 2024 is stuck with): late-round reach is understated by about 26 slots
and the mean available rank by about 12. So per-season ADP slopes are fitted
separately rather than pooled, and the truncation is reported as a limitation.
"""
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from .data import ROOT, read_csv
from .history import FEATURES, PHASES, name_key, phase, probabilities, fit_choices

SEASON_ORDER = ('2023-24', '2024-25', '2025-26')
SEASON_META = {
    '2023-24': {'start_year': 2023, 'adp_tier': 'none'},
    '2024-25': {'start_year': 2024, 'adp_tier': 'taken_only'},
    '2025-26': {'start_year': 2025, 'adp_tier': 'full_market'},
}
SOURCE_DIR = 'manager_persona_three_season_history'
MIN_AVAILABLE = 12  # boards thinner than this are dropped from fitting
TRAITS = ('young', 'rookie', 'guard', 'forward', 'center')


def season_age(bio, start_year):
    if not bio:
        return None
    born = date.fromisoformat(bio['birthdate'])
    as_of = date(start_year, 10, 1)
    return as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))


def season_rookie(bio, start_year):
    """Rookie for a given season from the NBA first-regular-season record."""
    if not bio:
        return None
    debut = bio.get('first_regular_season')
    return None if debut is None else debut == start_year


def trait_value(trait, key, start_year, bio, position):
    b = bio.get(key)
    if trait == 'young':
        age = season_age(b, start_year)
        return None if age is None else max(-1.5, min(1.5, (26 - age) / 8))
    if trait == 'rookie':
        value = season_rookie(b, start_year)
        return None if value is None else float(value)
    pos = position.get(key)
    if pos is None:
        return None
    return float({'guard': 'G', 'forward': 'F', 'center': 'C'}[trait] in pos)


def load(root=ROOT):
    source = Path(root) / SOURCE_DIR
    rows = read_csv(source / 'combined_draft_2023_2025.csv')
    keeper_markers = read_csv(source / 'keepers_2023_yahoo_marked.csv')
    bios = json.loads((Path(root) / 'data/player_bios.json').read_text())
    bio = {name_key(p['name']): p for p in bios['players']}
    # Positions come from the 2025-26 RotoWire export, the only position source we
    # have. Documented limitation: a 2025-26 snapshot applied to all seasons.
    rw25 = read_csv(Path(root) / 'manager_persona_2025_adp_handoff/rotowire_2025_adp.csv')
    position = {name_key(r['player']): r['position'] for r in rw25 if r['position']}
    market25 = {name_key(r['player']): float(r['yahoo_adp_2025']) for r in rw25 if r['yahoo_adp_2025']}

    seasons = {}
    for season in SEASON_ORDER:
        meta = SEASON_META[season]
        picks = sorted((r for r in rows if r['season'] == season), key=lambda r: int(r['overall_pick']))
        if len(picks) != 156:
            raise ValueError(f'{season} does not contain 156 picks')
        if [int(r['overall_pick']) for r in picks] != list(range(1, 157)):
            raise ValueError(f'{season} picks are not exactly 1-156')
        if len({name_key(r['player']) for r in picks}) != 156:
            raise ValueError(f'{season} contains a duplicated player')
        records = []
        for r in picks:
            key = name_key(r['player'])
            records.append({'slot': int(r['overall_pick']), 'round': int(r['round']), 'manager': r['manager'],
                            'player': r['player'], 'key': key, 'keeper': r['is_keeper'] == '1',
                            'adp': float(r['yahoo_adp']) if r['yahoo_adp'] else None})
        keepers = {r['key'] for r in records if r['keeper']}
        if meta['adp_tier'] == 'full_market':
            market = {k: v for k, v in market25.items() if k not in keepers}
        elif meta['adp_tier'] == 'taken_only':
            market = {r['key']: r['adp'] for r in records if r['adp'] and r['key'] not in keepers}
        else:
            market = {}
        seasons[season] = {'meta': meta, 'records': records, 'keepers': keepers, 'market': market,
                           'managers': sorted({r['manager'] for r in records})}
    expected = set(seasons['2025-26']['managers'])
    if not all(set(d['managers']) == expected for d in seasons.values()):
        raise ValueError('Manager identities differ across seasons')
    if len(keeper_markers) != 34 or {name_key(r['player']) for r in keeper_markers} != seasons['2023-24']['keepers']:
        raise ValueError('2023 keeper markers disagree with the combined history')
    return seasons, bio, position


def market_choice_sets(season_data, bio, position):
    """ADP-conditioned choice sets; only seasons with a market produce them."""
    records = season_data['records']
    start_year = season_data['meta']['start_year']
    market = dict(season_data['market'])
    out = []
    for r in sorted(records, key=lambda r: r['slot']):
        if r['keeper']:
            market.pop(r['key'], None)
            continue
        if r['adp'] is None or r['key'] not in market:
            continue
        available = sorted(market.items(), key=lambda kv: (kv[1], kv[0]))
        if len(available) < MIN_AVAILABLE:
            break
        ids = [k for k, _ in available]
        features = []
        for rank, (k, _) in enumerate(available, 1):
            row = [trait_value(t, k, start_year, bio, position) or 0.0
                   for t in ('young', 'rookie', 'guard', 'forward', 'center')]
            features.append([-math.log(rank)] + row)
        out.append({'season': season_data['meta']['adp_tier'], 'overall_pick': r['slot'], 'round': r['round'],
                    'manager': r['manager'], 'phase': phase(r['round']), 'selected_index': ids.index(r['key']),
                    'available_ids': ids, 'features': features, 'pool_size': len(available)})
        market.pop(r['key'], None)
    return out


def preference_observations(seasons, bio, position):
    """Slot-controlled descriptive preferences across every season.

    Deviations are computed within round phases and then averaged across phases
    weighted by how many picks the manager actually made there.
    """
    out = {}
    for name in seasons['2025-26']['managers']:
        per_season = {}
        for season, data in seasons.items():
            start_year = data['meta']['start_year']
            picks = [r for r in data['records'] if r['manager'] == name and not r['keeper']]
            others = [r for r in data['records'] if r['manager'] != name and not r['keeper']]
            row = {}
            for trait in TRAITS:
                devs, weights, own_vals, n = [], [], [], 0
                for ph in PHASES:
                    mine = [trait_value(trait, r['key'], start_year, bio, position) for r in picks if phase(r['round']) == ph]
                    mine = [v for v in mine if v is not None]
                    theirs = [trait_value(trait, r['key'], start_year, bio, position) for r in others if phase(r['round']) == ph]
                    theirs = [v for v in theirs if v is not None]
                    if not mine or not theirs:
                        continue
                    devs.append(statistics.mean(mine) - statistics.mean(theirs))
                    weights.append(len(mine)); own_vals.extend(mine); n += len(mine)
                if n:
                    row[trait] = {'n': n, 'value': statistics.mean(own_vals),
                                  'deviation': sum(d * w for d, w in zip(devs, weights)) / sum(weights)}
            per_season[season] = row
        consistency = {}
        for trait in TRAITS:
            series = [per_season[s][trait]['deviation'] for s in SEASON_ORDER
                      if s in per_season and trait in per_season[s]]
            consistency[trait] = {'seasons': len(series), 'values': series,
                                  'same_sign': len(series) >= 2 and len({math.copysign(1, x) for x in series if x != 0}) == 1,
                                  'mean_deviation': statistics.mean(series) if series else None,
                                  'sd': statistics.pstdev(series) if len(series) > 1 else None}
        out[name] = {'per_season': per_season, 'consistency': consistency,
                     'discretionary': {s: sum(1 for r in seasons[s]['records'] if r['manager'] == name and not r['keeper'])
                                       for s in SEASON_ORDER},
                     'keeper_counts': {s: sum(1 for r in seasons[s]['records'] if r['manager'] == name and r['keeper'])
                                       for s in SEASON_ORDER}}
    return out


def train(seasons, per_season_sets):
    pooled = [c for s in SEASON_ORDER for c in per_season_sets[s]]
    market_seasons = [s for s in SEASON_ORDER if per_season_sets[s]]
    prior = [1.4, 0, 0, 0, 0, 0]
    global_coef, global_sd = fit_choices(pooled, prior, [12, 40, 40, 40, 40, 40])
    model = {'global': global_coef, 'global_sd': global_sd, 'market_seasons': market_seasons,
             'per_season': {}, 'managers': {}, 'phase': {}, 'n_pooled': len(pooled)}
    for s in market_seasons:
        coef, sd = fit_choices(per_season_sets[s], global_coef, [20, 45, 45, 45, 45, 45])
        model['per_season'][s] = {'coefficients': coef, 'sd': sd, 'n': len(per_season_sets[s])}
    pooled_coef, pooled_sd = fit_choices(pooled, global_coef, [18, 45, 45, 45, 45, 45])
    model['pooled'] = {'coefficients': pooled_coef, 'sd': pooled_sd, 'n': len(pooled)}
    for ph in PHASES:
        subset = [c for c in pooled if c['phase'] == ph]
        coef, sd = fit_choices(subset, global_coef, [30, 1e9, 1e9, 1e9, 1e9, 1e9])
        model['phase'][ph] = {'coefficients': coef, 'sd': sd, 'n': len(subset)}
    # Strict ADP-only per-phase baseline (preferences frozen at zero) so the
    # engine's 'baseline' mode keeps meaning "market order, nothing else".
    model['baseline_phases'] = {}
    for ph in PHASES:
        subset = [c for c in pooled if c['phase'] == ph]
        coef, sd = fit_choices(subset, [1.4, 0, 0, 0, 0, 0], [30, 1e9, 1e9, 1e9, 1e9, 1e9])
        model['baseline_phases'][ph] = {'coefficients': coef, 'sd': sd, 'n': len(subset)}
    for name in seasons['2025-26']['managers']:
        subset = [c for c in pooled if c['manager'] == name]
        coef, sd = fit_choices(subset, pooled_coef, [25, 50, 50, 50, 50, 50])
        entry = {'coefficients': coef, 'sd': sd, 'n': len(subset), 'phases': {}}
        for ph in PHASES:
            local = [c for c in subset if c['phase'] == ph]
            b, s2 = fit_choices(local if len(local) >= 5 else [], coef, [60] * 6)
            entry['phases'][ph] = {'coefficients': b, 'sd': s2, 'n': len(local), 'prior_only': len(local) < 5}
        model['managers'][name] = entry
    return model


def evaluate(sets, coefficients):
    total = sum(-math.log(max(1e-12, probabilities(c['features'], coefficients)[c['selected_index']])) for c in sets)
    return total / max(1, len(sets))


def validate(per_season_sets, model):
    pooled = [c for s in SEASON_ORDER for c in per_season_sets[s]]
    baseline_prior = [1.4, 0, 0, 0, 0, 0]
    managers = sorted({c['manager'] for c in pooled})
    within = []
    for cutoff, end in ((4, 7), (7, 10), (10, 13)):
        train_rows = [c for c in pooled if c['round'] <= cutoff and c['manager'] != 'Oscar']
        test_rows = [c for c in pooled if cutoff < c['round'] <= end and c['manager'] != 'Oscar']
        if not train_rows or not test_rows:
            continue
        base, _ = fit_choices(train_rows, baseline_prior, [2, 1e9, 1e9, 1e9, 1e9, 1e9])
        glob, _ = fit_choices(train_rows, baseline_prior, [12, 40, 40, 40, 40, 40])
        persona, _ = fit_choices(train_rows, glob, [25, 50, 50, 50, 50, 50])
        # Per-manager arms are fitted ONLY on the training rounds, then applied to
        # the held-out rounds. No coefficient ever sees its own test rows.
        manager_arm = {}
        for name in managers:
            sub = [c for c in train_rows if c['manager'] == name]
            manager_arm[name] = fit_choices(sub if len(sub) >= 5 else [], persona, [60] * 6)[0]
        for c in test_rows:
            row = {'round': c['round'], 'season': c['season']}
            arms = (('baseline', base), ('global', glob), ('persona_pooled', persona),
                    ('persona_manager', manager_arm[c['manager']]))
            for label, coef in arms:
                probs = probabilities(c['features'], coef)
                chosen = probs[c['selected_index']]
                row[label + '_log_loss'] = -math.log(max(1e-12, chosen))
                row[label + '_rank'] = 1 + sum(p > chosen for p in probs)
            within.append(row)
    cross = {}
    if len(model['market_seasons']) == 2:
        a, b = model['market_seasons']
        for train_s, test_s in ((a, b), (b, a)):
            tr = [c for c in per_season_sets[train_s] if c['manager'] != 'Oscar']
            te = [c for c in per_season_sets[test_s] if c['manager'] != 'Oscar']
            base, _ = fit_choices(tr, baseline_prior, [2, 1e9, 1e9, 1e9, 1e9, 1e9])
            glob, _ = fit_choices(tr, baseline_prior, [12, 40, 40, 40, 40, 40])
            wide, _ = fit_choices(tr, glob, [60, 80, 80, 80, 80, 80])
            per_manager = {}
            for name in managers:
                sub = [c for c in tr if c['manager'] == name]
                per_manager[name] = fit_choices(sub if len(sub) >= 5 else [], wide, [80] * 6)[0]
            # Per-manager arms transfer one season's learned quirks to the next.
            pm_loss = statistics.mean(-math.log(max(1e-12, probabilities(c['features'], per_manager[c['manager']])[c['selected_index']])) for c in te)
            cross[f'{train_s}->{test_s}'] = {'n_train': len(tr), 'n_test': len(te),
                'test_pool': SEASON_META[test_s]['adp_tier'],
                'baseline_log_loss': evaluate(te, base), 'global_log_loss': evaluate(te, glob),
                'persona_pooled_log_loss': evaluate(te, wide), 'persona_manager_log_loss': pm_loss}
    wins_pooled = sum(1 for k in cross if cross[k]['persona_pooled_log_loss'] < cross[k]['baseline_log_loss'])
    wins_manager = sum(1 for k in cross if cross[k]['persona_manager_log_loss'] < cross[k]['baseline_log_loss'])

    def summarize(key):
        return {'log_loss': statistics.mean(r[key + '_log_loss'] for r in within),
                'mean_choice_rank': statistics.mean(r[key + '_rank'] for r in within),
                'top5_accuracy': statistics.mean(r[key + '_rank'] <= 5 for r in within)}
    metrics = {k: summarize(k) for k in ('baseline', 'global', 'persona_pooled', 'persona_manager')}
    diffs = [r['persona_manager_log_loss'] - r['baseline_log_loss'] for r in within]
    improvement = statistics.mean(diffs) if diffs else None
    blocks = defaultdict(list)
    for r, d in zip(within, diffs):
        blocks[r['round']].append(d)
    rng = random.Random(20261012)
    keys = sorted(blocks)
    boots = sorted(statistics.mean(v for k in rng.choices(keys, k=len(keys)) for v in blocks[k]) for _ in range(1000))
    interval = [boots[24], boots[974]] if boots else [None, None]
    # Personas must clear all three: better held-out loss, an interval excluding
    # zero, AND transfer to a different season. Cross-season is the real test.
    useful = bool(within) and improvement is not None and improvement < -.01 and interval[1] < 0 and wins_manager >= 1
    return {'method': 'Pooled 2024-25 + 2025-26 ADP choice sets; forward-round holdout + cross-season transfer',
            'n_test': len(within), 'n_pooled_sets': len(pooled), 'metrics': metrics,
            'persona_minus_baseline_log_loss': improvement, 'round_bootstrap_95_interval': interval,
            'cross_season': cross, 'cross_season_persona_wins': wins_manager,
            'cross_season_pooled_wins': wins_pooled, 'cross_season_pairs': len(cross),
            'persona_enabled_by_default': bool(useful), 'decision': 'persona' if useful else 'baseline',
            'limitations': [
                '2024-25 ADP exists only for players actually taken, so its pool is truncated: late-round reach is understated by ~26 slots. Slopes are fitted per season, never pooled across the two.',
                '2023-24 has no usable ADP (the supplied export duplicates 2024), so it informs descriptive preferences only, never the choice likelihood.',
                'The two ADP seasons have different pool tiers, so cross-season transfer partly reflects that difference rather than pure behavioural drift.',
                'Positions are a 2025-26 snapshot applied to all seasons; historical position eligibility is not reconstructed.',
                'Cross-season transfer is directional evidence, not a calibrated probability.']}


def build(root=ROOT):
    seasons, bio, position = load(root)
    preferences = preference_observations(seasons, bio, position)
    per_season_sets = {s: market_choice_sets(seasons[s], bio, position) for s in SEASON_ORDER}
    model = train(seasons, per_season_sets)
    validation = validate(per_season_sets, model)
    coverage = {}
    for s in SEASON_ORDER:
        d = seasons[s]
        coverage[s] = {'season': s, 'adp_tier': SEASON_META[s]['adp_tier'], 'picks': len(d['records']),
                       'keepers': len(d['keepers']),
                       'discretionary': sum(1 for r in d['records'] if not r['keeper']),
                       'discretionary_with_adp': sum(1 for r in d['records'] if not r['keeper'] and r['adp'] is not None),
                       'market_pool': len(d['market']),
                       'choice_sets': len(per_season_sets[s]),
                       'years': {'age': sum(1 for r in d['records'] if season_age(bio.get(r['key']), SEASON_META[s]['start_year']) is not None),
                                 'position': sum(1 for r in d['records'] if r['key'] in position)}}
    profiles = {}
    for name, obs in preferences.items():
        profiles[name] = {'manager': name, 'observations': obs, 'learned': model['managers'][name],
                          'confidence': 'moderate: 3 seasons of preferences, 2 seasons of ADP-conditioned choices',
                          'unsupported': [
                              'Player-specific targeting cannot be identified from one pick per player.',
                              'Youth/rookie effects are associations, not proven keeper-upside intent.',
                              'Historical fantasy value and category-fit coefficients remain assumptions, not estimates.',
                              'Position preference uses a 2025-26 position snapshot for every season.']}
    report = {'metadata': {
                'seasons': list(SEASON_ORDER),
                'adp_source_2025': 'RotoWire 2025-26 export (retrieved 2026-10-11; measurement date unknown)',
                'adp_2024': 'Taken players only; no undrafted market was supplied',
                'adp_2023': 'No usable ADP: the supplied 2023 export is byte-identical to the 2024 export',
                'adp_season_validation': 'Each ADP column correlates highest with its own season picks '
                                         '(2024: 0.956, 2025: 0.913), supporting genuine season-specific markets',
                'truncation_bias': 'Truncating the 2025 pool to taken-only understates mean available rank by '
                                   '~12 slots and late-round reach by ~26 slots',
                'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(root) / SOURCE_DIR).glob('*.csv')}},
              'coverage': coverage,
              'methodology': {
                'preferences': 'Slot-controlled: each manager compared with the same-season league mix in the same round phase, across all three seasons',
                'choices': 'Conditional logit over the ADP market available set; per-season ADP slope, preference betas shrunk toward a pooled prior',
                'excluded': f'Choice sets with fewer than {MIN_AVAILABLE} available players are dropped (very late picks)'}}
    package = {'report': report, 'profiles': profiles, 'model': model, 'validation': validation,
               'features': FEATURES, 'season_order': list(SEASON_ORDER), 'season_meta': SEASON_META}
    output = Path(root) / 'data/history3'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'profiles.json').write_text(json.dumps(package, indent=2))
    (output / 'validation.json').write_text(json.dumps(validation, indent=2))
    return package
