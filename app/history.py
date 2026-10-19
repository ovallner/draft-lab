"""Auditable historical choice sets and regularized conditional-choice profiles.

No current projections or category forecasts enter this module's training data.
"""
import csv
import hashlib
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from .data import ROOT, read_csv, normalize

FEATURES = ['adp_adherence', 'young', 'rookie', 'G', 'F', 'C']
PHASES = ('early', 'middle', 'late')
MANAGERS = {'Set the Bar': 'Addison', 'Murray-Culous': 'San', 'Number 33': 'Shiven',
            'Maxey hit the Markk': 'Samet', 'Next Chosen One': 'Adam', "Livin' Avdija Loca": 'Raul',
            'Team Stable Knees v2': 'Nick', 'Huevos Bancheros': 'Ashley', 'Live Laugh LeBron': 'Oscar',
            "It's Donkey Time": 'Austin', '2026-2027': 'Jipples', 'Koo': 'Koo'}
AGE_DATE = date(2025, 10, 1)


def name_key(name):
    key = normalize(re.sub(r'\s+(Jr\.?|II|III|IV)$', '', name, flags=re.I))
    return {'alexsarr': 'alexandresarr', 'nicolasclaxton': 'nicclaxton', 'ronholland': 'ronaldholland'}.get(key, key)


def phase(round_number):
    return 'early' if round_number <= 4 else 'middle' if round_number <= 9 else 'late'


def bio_features(bio, as_of=AGE_DATE):
    if not bio:
        return {'age': None, 'rookie': None, 'draft_year': None, 'nba_id': None}
    born = date.fromisoformat(bio['birthdate'])
    age = as_of.year - born.year - ((as_of.month, as_of.day) < (born.month, born.day))
    debut = bio.get('first_regular_season')
    rookie = None if debut is None or debut > as_of.year else debut == as_of.year
    return {'age': age, 'rookie': rookie, 'draft_year': bio.get('draft_year'), 'nba_id': bio['nba_id']}


def probabilities(features, coefficients):
    scores = [sum(x * b for x, b in zip(f, coefficients)) for f in features]
    peak = max(scores)
    weights = [math.exp(s - peak) for s in scores]
    total = sum(weights)
    return [w / total for w in weights]


def fit_choices(choices, prior, penalties, iterations=90):
    """Small ridge conditional logit, damped diagonal Newton gradient updates."""
    coefficients = list(prior)
    curvature = list(penalties)
    if not choices:
        return coefficients, [1 / math.sqrt(max(1., p)) for p in penalties]
    for _ in range(iterations):
        grad = [-p * (b - mean) for p, b, mean in zip(penalties, coefficients, prior)]
        curvature = list(penalties)
        for c in choices:
            fs = c['features']; probs = probabilities(fs, coefficients)
            chosen = fs[c['selected_index']]
            for j in range(len(coefficients)):
                mean = sum(p * f[j] for p, f in zip(probs, fs))
                var = sum(p * (f[j] - mean) ** 2 for p, f in zip(probs, fs))
                grad[j] += chosen[j] - mean
                curvature[j] += var
        step = [.35 * g / max(1., h) for g, h in zip(grad, curvature)]
        coefficients = [max(.35, min(4., b + s)) if j == 0 else max(-.7, min(.7, b + s)) for j, (b, s) in enumerate(zip(coefficients, step))]
        if max(abs(s) for s in step) < .00005:
            break
    return coefficients, [1 / math.sqrt(max(1., h)) for h in curvature]


def train(choices):
    # Baseline learns only ADP slope. No rookie/value/position coefficient is
    # silently incorporated into the ADP-only comparator.
    baseline, baseline_sd = fit_choices(choices, [1.4, 0, 0, 0, 0, 0], [2, 1e9, 1e9, 1e9, 1e9, 1e9])
    global_profile, global_sd = fit_choices(choices, baseline, [12, 40, 40, 40, 40, 40])
    phases = {}
    for ph in PHASES:
        subset = [c for c in choices if c['phase'] == ph]
        value, sd = fit_choices(subset, baseline, [30, 1e9, 1e9, 1e9, 1e9, 1e9])
        phases[ph] = {'coefficients': value, 'sd': sd, 'n': len(subset)}
    managers = {}
    for manager in MANAGERS.values():
        subset = [c for c in choices if c['manager'] == manager]
        value, sd = fit_choices(subset, global_profile, [25, 50, 50, 50, 50, 50])
        managers[manager] = {'coefficients': value, 'sd': sd, 'n': len(subset), 'phases': {}}
        for ph in PHASES:
            local = [c for c in subset if c['phase'] == ph]
            # Very sparse stages remain exactly at the manager prior.
            b, s = fit_choices(local if len(local) >= 4 else [], value, [60] * 6)
            managers[manager]['phases'][ph] = {'coefficients': b, 'sd': s, 'n': len(local), 'prior_only': len(local) < 4}
    return {'baseline': baseline, 'baseline_sd': baseline_sd, 'global': global_profile,
            'global_sd': global_sd, 'baseline_phases': phases, 'managers': managers}


def validate(choices):
    rows = []
    folds = []
    # Predeclared forward splits. Hyperparameters are fixed, not selected on test.
    for cutoff, end in ((4, 7), (7, 10), (10, 13)):
        training = [c for c in choices if c['round'] <= cutoff and c['manager'] != 'Oscar']
        testing = [c for c in choices if cutoff < c['round'] <= end and c['manager'] != 'Oscar']
        model = train(training)
        metrics = {'baseline': [], 'persona': []}
        for c in testing:
            prior = model['baseline_phases'][c['phase']]['coefficients']
            persona = model['managers'][c['manager']]['phases'][c['phase']]['coefficients']
            result = {'slot': c['overall_pick'], 'round': c['round'], 'manager': c['manager'], 'fold': cutoff}
            for name, coefficients in (('baseline', prior), ('persona', persona)):
                probs = probabilities(c['features'], coefficients)
                chosen = probs[c['selected_index']]
                rank = 1 + sum(p > chosen for p in probs)
                result[name + '_log_loss'] = -math.log(max(1e-12, chosen))
                result[name + '_rank'] = rank
                # Multiclass Brier score, NOT a survival calibration claim.
                result[name + '_choice_brier'] = sum((p - (i == c['selected_index'])) ** 2 for i, p in enumerate(probs))
                metrics[name].append(result[name + '_log_loss'])
            rows.append(result)
        folds.append({'train_through_round': cutoff, 'test_through_round': end, 'n_train': len(training), 'n_test': len(testing),
                      'baseline_log_loss': statistics.mean(metrics['baseline']) if testing else None,
                      'persona_log_loss': statistics.mean(metrics['persona']) if testing else None})
    differences = [r['persona_log_loss'] - r['baseline_log_loss'] for r in rows]
    # Resample held-out rounds together, not individual dependent picks.
    blocks = defaultdict(list)
    for r, difference in zip(rows, differences):
        blocks[r['round']].append(difference)
    rng = random.Random(20251001)
    keys = sorted(blocks)
    boot = []
    for _ in range(1000):
        values = [v for key in rng.choices(keys, k=len(keys)) for v in blocks[key]]
        boot.append(statistics.mean(values))
    boot.sort()
    interval = [boot[24], boot[974]]
    improvement = statistics.mean(differences)
    useful = improvement < -.01 and interval[1] < 0 and sum(f['persona_log_loss'] < f['baseline_log_loss'] for f in folds) >= 2
    summary = {}
    for model in ('baseline', 'persona'):
        summary[model] = {'log_loss': statistics.mean(r[model + '_log_loss'] for r in rows),
                          'mean_choice_rank': statistics.mean(r[model + '_rank'] for r in rows),
                          'top5_accuracy': statistics.mean(r[model + '_rank'] <= 5 for r in rows),
                          'choice_brier': statistics.mean(r[model + '_choice_brier'] for r in rows)}
    return {'method': 'Forward-by-round holdouts; fixed shrinkage; round-block bootstrap', 'n_test': len(rows),
            'folds': folds, 'metrics': summary, 'persona_minus_baseline_log_loss': improvement,
            'round_bootstrap_95_interval': interval, 'persona_enabled_by_default': useful,
            'decision': 'persona' if useful else 'baseline', 'predictions': rows,
            'limitations': ['One league-season; historical ADP measurement date unknown.',
                           'Only known-ADP alternatives are scored; four live picks have missing ADP.',
                           'No historical fantasy value/roster-fit coefficients fitted. Exported positions are coarse and not verified historical Yahoo eligibility.',
                           'Choice Brier is not survival Brier. Multi-pick survival calibration is not established by this small single-season validation.']}


def describe(values):
    return {'mean': statistics.mean(values), 'median': statistics.median(values), 'sd': statistics.pstdev(values),
            'min': min(values), 'max': max(values)} if values else None


def validate_survival(choices, normalized, trials=120):
    """Forward holdout survival replay on fixed candidate strata, no future leakage."""
    first = choices[0]
    static = {pid: f[1:] for pid, f in zip(first['available_ids'], first['features'])}
    known_adp = {r['player_id']: r['yahoo_adp'] for r in normalized if r['yahoo_adp'] is not None}
    # Include undrafted alternatives: their relative order is available in the
    # initial choice set. No actual future selection determines test candidates.
    initial_order = {pid: i for i, pid in enumerate(first['available_ids'])}
    result = []
    anchor_count = 0
    for cutoff, end in ((4, 7), (7, 10), (10, 13)):
        fitted = train([c for c in choices if c['round'] <= cutoff and c['manager'] != 'Oscar'])
        anchors = [c for c in choices if cutoff < c['round'] <= end and c['manager'] != 'Oscar']
        for anchor in anchors:
            target = next((c for c in choices if c['overall_pick'] > anchor['overall_pick'] and c['manager'] == anchor['manager']), None)
            if not target or target['round'] > end:
                continue
            intervening = [r for r in normalized if anchor['overall_pick'] < int(r['overall_pick']) < target['overall_pick'] and not r['is_keeper']]
            if any(r['yahoo_adp'] is None for r in intervening):
                continue
            selected = anchor['available_ids'][anchor['selected_index']]
            pool = [pid for pid in anchor['available_ids'] if pid != selected]
            strata = [0, 1, 2, 3, 5, 8, 12, 20, 35, 55, 80]
            candidates = [pool[i] for i in strata if i < len(pool)]
            counts = {'baseline': Counter(), 'persona': Counter()}
            for mode in counts:
                for trial in range(trials):
                    remaining = list(pool)
                    rng = random.Random(f'holdout:{anchor["overall_pick"]}:{trial}')
                    for event in intervening:
                        fs = [[-math.log(i + 1)] + static[pid] for i, pid in enumerate(remaining)]
                        ph = phase(int(event['round']))
                        coefs = fitted['baseline_phases'][ph]['coefficients'] if mode == 'baseline' else fitted['managers'][event['manager']]['phases'][ph]['coefficients']
                        probs = probabilities(fs, coefs)
                        pick = rng.choices(range(len(remaining)), weights=probs, k=1)[0]
                        remaining.pop(pick)
                    counts[mode].update(pid for pid in candidates if pid in remaining)
            actual = set(target['available_ids'])
            for pid in candidates:
                result.append({'anchor_slot': anchor['overall_pick'], 'target_slot': target['overall_pick'], 'round': anchor['round'],
                               'player_id': pid, 'observed_survived': pid in actual,
                               'baseline_probability': counts['baseline'][pid] / trials,
                               'persona_probability': counts['persona'][pid] / trials})
            anchor_count += 1
    metrics = {}
    for mode in ('baseline', 'persona'):
        scores = [(r[mode + '_probability'] - r['observed_survived']) ** 2 for r in result]
        bins = []
        for lo in (0, .2, .4, .6, .8):
            subset = [r for r in result if lo <= r[mode + '_probability'] < lo + .2 or lo == .8 and r[mode + '_probability'] == 1]
            bins.append({'low': lo, 'high': lo + .2, 'n': len(subset),
                         'predicted': statistics.mean(r[mode + '_probability'] for r in subset) if subset else None,
                         'observed': statistics.mean(r['observed_survived'] for r in subset) if subset else None})
        metrics[mode] = {'survival_brier': statistics.mean(scores) if scores else None, 'reliability_bins': bins}
    return {'n_anchors': anchor_count, 'n_candidate_outcomes': len(result), 'trials_per_anchor_model': trials,
            'metrics': metrics, 'predictions': result,
            'method': 'Forward-round training; every eligible held-out choice anchors next-manager-live-pick forecasts. Fixed available-rank strata; actual current choice known, intervening choices simulated. Horizons crossing missing-ADP live picks censored.',
            'limitations': 'Few correlated horizons from one season; descriptive calibration, not evidence of transportability to 2026. Undrafted alternatives follow initial known-ADP order; historical eligibility/ADP-date uncertainty remains.'}


def build_history(source=ROOT / 'manager_persona_2025_adp_handoff', output=ROOT / 'data' / 'history'):
    source, output = Path(source), Path(output)
    draft = read_csv(source / 'draft_2025_results.csv')
    keepers = read_csv(source / 'keepers_2025.csv')
    adp = read_csv(source / 'rotowire_2025_adp.csv')
    if sorted(int(r['overall_pick']) for r in draft) != list(range(1, 157)):
        raise ValueError('Historical slots must cover 1–156 exactly once')
    if len({name_key(r['player']) for r in draft}) != 156:
        raise ValueError('Duplicate historical player selections')
    if len(keepers) != 36 or set(Counter(k['manager'] for k in keepers).values()) != {3}:
        raise ValueError('Historical keeper coverage invalid')
    if len({r['rotowire_player_id'] for r in adp}) != len(adp):
        raise ValueError('Duplicate RotoWire IDs')
    lookup = defaultdict(list)
    for r in adp:
        lookup[name_key(r['player'])].append(r)
    def match(name):
        matches = lookup[name_key(name)]
        if len(matches) != 1:
            raise ValueError('Historical player match is missing/ambiguous: ' + name)
        return matches[0]
    bios_path = ROOT / 'data' / 'player_bios.json'
    bios = json.loads(bios_path.read_text()) if bios_path.exists() else {'metadata': {}, 'players': []}
    bio_lookup = {name_key(p['name']): p for p in bios['players']}
    historical_players = {}
    current_names = defaultdict(list)
    for r in read_csv(ROOT / 'hashtag_basketball_2026_27_projections_430.csv'):
        # Identity crosswalk ONLY; none of these current statistical projections
        # are accessible to the historical choice fitting functions.
        current_names[name_key(r['player'])].append('ht:' + r['player_id'])
    for r in adp:
        if r['yahoo_adp_2025'] or any(name_key(s['player']) == name_key(r['player']) for s in draft):
            pid = 'rw:' + r['rotowire_player_id']
            value = float(r['yahoo_adp_2025']) if r['yahoo_adp_2025'] else None
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError('Invalid historical Yahoo ADP')
            historical_players[pid] = {'id': pid, 'name': r['player'], 'adp': value,
                'position_as_exported': r['position'],
                'current_player_id': current_names[name_key(r['player'])][0] if len(current_names[name_key(r['player'])]) == 1 else None,
                'crosswalk_method': 'Unique normalized explicit-name/suffix alias' if len(current_names[name_key(r['player'])]) == 1 else 'Current projection identity missing/ambiguous; historical choice retained',
                **bio_features(bio_lookup.get(name_key(r['player'])))}
    keeper_ids = {'rw:' + match(k['player'])['rotowire_player_id']: k for k in keepers}
    pool = {pid: p for pid, p in historical_players.items() if pid not in keeper_ids}
    initial_known = sorted((p for p in pool.values() if p['adp'] is not None), key=lambda p: (p['adp'], p['id']))
    initial_rank = {p['id']: 1 + sum(q['adp'] < p['adp'] for q in initial_known) for p in initial_known}
    first_order = [r['drafting_team'] for r in draft[:12]]
    normalized, choices, aliases, deviations, keeper_seen = [], [], [], [], set()
    live_index = known_index = 0
    for raw in sorted(draft, key=lambda r: int(r['overall_pick'])):
        slot, round_number, within = int(raw['overall_pick']), int(raw['round']), int(raw['selection_within_round'])
        if slot != (round_number - 1) * 12 + within:
            raise ValueError('Round/slot disagreement')
        if raw['drafting_team'] not in MANAGERS:
            raise ValueError('Unmapped historical manager')
        manager = MANAGERS[raw['drafting_team']]
        source_player = match(raw['player']); pid = 'rw:' + source_player['rotowire_player_id']
        player = historical_players[pid]
        original_owner = first_order[within - 1 if round_number % 2 else 12 - within]
        is_keeper = pid in keeper_ids
        if (raw['keeper_marked_on_yahoo'] == 'yes') != is_keeper:
            raise ValueError('Yahoo/sheet keeper disagreement')
        if is_keeper:
            keeper_seen.add(pid)
            if keeper_ids[pid]['manager'] != manager or int(keeper_ids[pid]['keeper_cost_round']) != round_number:
                raise ValueError('Keeper owner/cost disagreement')
        else:
            if pid not in pool:
                raise ValueError('Historical selected player was unavailable')
            live_index += 1
        row = dict(raw, manager=manager, player_id=pid, nba_id=player['nba_id'], is_keeper=is_keeper,
                   original_snake_owner=MANAGERS[original_owner], ownership_departure=raw['drafting_team'] != original_owner,
                   yahoo_adp=player['adp'], age_2025_10_01=player['age'], rookie_2025=player['rookie'], draft_year=player['draft_year'],
                   discretionary_index=None if is_keeper else live_index, known_adp_index=None,
                   raw_deviation=None, keeper_adjusted_deviation=None, available_rank=None, available_percentile=None,
                   adp_gap_to_best=None, available_known_count=None)
        if normalize(raw['player']) != normalize(source_player['player']):
            aliases.append({'draft_name': raw['player'], 'source_name': source_player['player'], 'player_id': pid, 'method': 'Unique explicit suffix/name alias'})
        if row['ownership_departure']:
            deviations.append({'slot': slot, 'snake_owner': row['original_snake_owner'], 'actual_manager': manager})
        if not is_keeper and player['adp'] is not None:
            known_index += 1
            available = sorted((p for p in pool.values() if p['adp'] is not None), key=lambda p: (p['adp'], p['id']))
            rank = 1 + sum(p['adp'] < player['adp'] for p in available)
            row.update(known_adp_index=known_index, raw_deviation=slot - player['adp'],
                       keeper_adjusted_deviation=known_index - initial_rank[pid], available_rank=rank,
                       available_percentile=(rank - 1) / max(1, len(available) - 1),
                       adp_gap_to_best=player['adp'] - available[0]['adp'], available_known_count=len(available))
            features = []
            for p in available:
                r = 1 + sum(q['adp'] < p['adp'] for q in available)
                age = p['age']
                features.append([-math.log(r), max(-1.5, min(1.5, (26 - age) / 8)) if age is not None else 0,
                                 float(p['rookie']) if p['rookie'] is not None else 0,
                                 float('G' in p['position_as_exported']), float('F' in p['position_as_exported']), float('C' in p['position_as_exported'])])
            choices.append({'overall_pick': slot, 'round': round_number, 'manager': manager, 'phase': phase(round_number),
                            'selected_index': next(i for i, p in enumerate(available) if p['id'] == pid),
                            'available_ids': [p['id'] for p in available], 'features': features})
        if not is_keeper:
            del pool[pid]
        normalized.append(row)
    if keeper_seen != set(keeper_ids):
        raise ValueError('Keeper records missing from historical draft')
    # Verify preliminary analyses, rather than using their flags or fitted summaries.
    preliminary = read_csv(source / 'draft_2025_vs_yahoo_adp.csv')
    preliminary_errors = []
    for row, pre in zip(normalized, preliminary):
        if row['player_id'] != 'rw:' + pre['rotowire_player_id'] or row['is_keeper'] != (pre['is_2025_keeper'] == '1') or (row['yahoo_adp'] is not None and float(pre['yahoo_adp_2025']) != row['yahoo_adp']):
            preliminary_errors.append(row['overall_pick'])
    report = {'metadata': {'season': '2025-26', 'adp_source': 'https://www.rotowire.com/basketball/adp.php?season=2025',
              'adp_endpoint': 'https://www.rotowire.com/basketball/tables/adp.php?pos=ALL&season=2025',
              'adp_retrieved_date': '2026-10-11', 'adp_measurement_date': None, 'verified_draft_day_snapshot': False,
              'age_as_of': AGE_DATE.isoformat(), 'bio_metadata': bios['metadata'],
              'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.glob('*.csv')}},
              'coverage': {'draft_slots': 156, 'keepers': 36, 'discretionary': live_index, 'adp_covered_live': known_index,
                           'known_adp_market': len(initial_known), 'adp_records': len(adp),
                           'historical_bio_coverage': sum(p['age'] is not None for p in historical_players.values()),
                           'historical_candidate_records': len(historical_players)},
              'manager_mapping': MANAGERS, 'aliases': aliases, 'ownership_departures': deviations,
              'missing_adp_live': [r for r in normalized if not r['is_keeper'] and r['yahoo_adp'] is None],
              'preliminary_disagreements': preliminary_errors,
              'current_identity_gaps': [{'player_id': p['id'], 'name': p['name']} for p in historical_players.values() if p['current_player_id'] is None],
              'methodology': {'raw': 'overall_pick minus historical Yahoo ADP; negative means selected early.',
                  'keeper_adjusted': 'known-ADP discretionary index minus initial keeper-depleted known-ADP market rank; negative means early. Ties use minimum rank. Unknown-ADP live picks do not advance this known-market clock.',
                  'available_rank': '1 plus number of available alternatives with strictly better Yahoo ADP. All 36 keepers removed before slot 1.',
                  'pool': '200 known-ADP records plus observed missing-ADP selections, not all 1,344 retired/FA records. Historical eligible universe is incomplete.',
                  'adp_gap': 'Selected ADP minus best available ADP: positive means bypassing better-ADP options. Different sign convention from timing deviations.'}}
    opponents = [c for c in choices if c['manager'] != 'Oscar']
    report['preliminary_summary_disagreements'] = []
    for r in read_csv(source / 'manager_2025_adp_summary.csv'):
        rows = [x for x in normalized if x['manager'] == MANAGERS[r['draft_team']] and not x['is_keeper'] and x['yahoo_adp'] is not None]
        mean = statistics.mean(x['raw_deviation'] for x in rows)
        if len(rows) != int(r['eligible_discretionary_picks']) or abs(mean - float(r['mean_draft_minus_yahoo_adp'])) > .015:
            report['preliminary_summary_disagreements'].append(r['draft_team'])
    model = train(opponents)
    validation = validate(opponents)
    # Survival validation needs the first actual choice set to retain the whole
    # initial known-ADP universe, including undrafted players.
    survival_validation = validate_survival(choices, normalized)
    validation['survival_replay'] = survival_validation
    brier = survival_validation['metrics']
    if not survival_validation['n_anchors'] or brier['persona']['survival_brier'] >= brier['baseline']['survival_brier']:
        validation['persona_enabled_by_default'] = False
        validation['decision'] = 'baseline'
    profiles = {}
    for manager in MANAGERS.values():
        rows = [r for r in normalized if r['manager'] == manager and not r['is_keeper']]
        covered = [r for r in rows if r['yahoo_adp'] is not None]
        profiles[manager] = {'manager': manager, 'observations': {'n_discretionary': len(rows), 'n_adp': len(covered),
            'raw_deviation': describe([r['raw_deviation'] for r in covered]),
            'keeper_adjusted_deviation': describe([r['keeper_adjusted_deviation'] for r in covered]),
            'available_rank': describe([r['available_rank'] for r in covered]),
            'top3_available_share': statistics.mean(r['available_rank'] <= 3 for r in covered),
            'positions_as_exported': dict(Counter(historical_players[r['player_id']]['position_as_exported'] for r in rows)),
            'age': describe([r['age_2025_10_01'] for r in rows if r['age_2025_10_01'] is not None]),
            'rookie_count': sum(r['rookie_2025'] is True for r in rows), 'rookie_known_n': sum(r['rookie_2025'] is not None for r in rows)},
            'learned': model['managers'][manager], 'confidence': 'low: one season, 9–10 ADP-covered picks',
            'unsupported': ['Player-specific loyalty/targeting cannot be identified from one pick per player.',
                            'Youth/rookie preferences are conditional associations, not proven keeper-upside intent.',
                            'Historical value and category-fit coefficients are assumptions, not estimated.']}
    package = {'report': report, 'profiles': profiles, 'model': model, 'validation': validation, 'features': FEATURES}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'profiles.json').write_text(json.dumps(package, indent=2))
    (output / 'choice_sets.json').write_text(json.dumps({'players': historical_players, 'choices': choices}, indent=2))
    with (output / 'draft_validated.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(normalized[0])); writer.writeheader(); writer.writerows(normalized)
    (output / 'validation.json').write_text(json.dumps(validation, indent=2))
    return package
