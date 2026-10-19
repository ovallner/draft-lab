import copy
import json
import math
import unittest
from datetime import date
from app.data import Data, ROOT
from app.history import bio_features, fit_choices
from app.engine import Engine
from app.store import Store
from app.draft_model import uncertainty_barrier, apply_scenario, wilson


class HistoricalPipelineTests(unittest.TestCase):
    """The active three-season persona package (data/history3)."""

    @classmethod
    def setUpClass(cls):
        cls.data = Data()
        cls.package = cls.data.history_package

    def test_active_package_is_three_season_with_explicit_adp_tiers(self):
        self.assertEqual(self.package['source_file'], 'data/history3/profiles.json')
        coverage = self.package['report']['coverage']
        self.assertEqual(set(coverage), {'2023-24', '2024-25', '2025-26'})
        for season in coverage:
            self.assertEqual(coverage[season]['picks'], 156)
        self.assertEqual(coverage['2023-24']['adp_tier'], 'none')
        self.assertEqual(coverage['2024-25']['adp_tier'], 'taken_only')
        self.assertEqual(coverage['2025-26']['adp_tier'], 'full_market')
        # 2023 cannot feed the choice model because it has no usable ADP.
        self.assertEqual(coverage['2023-24']['choice_sets'], 0)
        self.assertEqual(coverage['2023-24']['discretionary_with_adp'], 0)
        self.assertGreater(coverage['2024-25']['choice_sets'], 100)
        self.assertGreater(coverage['2025-26']['choice_sets'], 100)
        # Only 2025 has an undrafted market; 2024 is truncated to taken players.
        self.assertGreater(coverage['2025-26']['market_pool'], coverage['2024-25']['market_pool'])
        self.assertIn('truncat', self.package['report']['metadata']['truncation_bias'].lower())

    def test_season_correct_age_and_rookie_not_a_fixed_date(self):
        from app.history3 import season_age, season_rookie
        lebron = {'birthdate': '1984-12-30', 'first_regular_season': 2003}
        self.assertEqual(season_age(lebron, 2023), 38)
        self.assertEqual(season_age(lebron, 2025), 40)
        self.assertEqual(season_age(lebron, 2026), 41)
        self.assertTrue(season_rookie({'first_regular_season': 2023}, 2023))
        self.assertFalse(season_rookie({'first_regular_season': 2003}, 2023))
        self.assertIsNone(season_rookie({'first_regular_season': None}, 2023))
        self.assertIsNone(season_age(None, 2025))

    def test_validation_gate_metrics_and_cross_season_transfer(self):
        v = self.package['validation']
        self.assertGreater(v['n_test'], 100)
        self.assertGreater(v['n_pooled_sets'], 200)
        for arm in ('baseline', 'global', 'persona_pooled', 'persona_manager'):
            self.assertIn(arm, v['metrics'])
            self.assertGreater(v['metrics'][arm]['log_loss'], 0)
        self.assertEqual(v['decision'], 'baseline')
        self.assertFalse(v['persona_enabled_by_default'])
        # Personas must transfer across seasons to be enabled; here they do not.
        self.assertLess(v['cross_season_persona_wins'], v['cross_season_pairs'])
        self.assertEqual(v['cross_season_pairs'], 2)
        for pair, row in v['cross_season'].items():
            self.assertIn('persona_manager_log_loss', row)
            self.assertIn('baseline_log_loss', row)
        interval = v['round_bootstrap_95_interval']
        self.assertLessEqual(interval[0], interval[1])

    def test_baseline_phase_coefficients_are_pure_adp(self):
        model = self.package['model']
        self.assertEqual(set(model['baseline_phases']), {'early', 'middle', 'late'})
        for ph in ('early', 'middle', 'late'):
            coefficients = model['baseline_phases'][ph]['coefficients']
            self.assertEqual(len(coefficients), 6)
            for value in coefficients[1:]:
                self.assertAlmostEqual(value, 0.0, places=6)

    def test_preference_consistency_is_well_formed(self):
        for name, profile in self.package['profiles'].items():
            consistency = profile['observations']['consistency']
            for trait in ('young', 'rookie', 'guard', 'forward', 'center'):
                self.assertIn(trait, consistency)
                self.assertLessEqual(consistency[trait]['seasons'], 3)
                if consistency[trait]['same_sign']:
                    values = [x for x in consistency[trait]['values'] if x != 0]
                    self.assertTrue(all(x > 0 for x in values) or all(x < 0 for x in values))
            # Overrides must never mutate stored observations.
            self.assertIn('young', profile['observations']['consistency'])


class LegacySingleSeasonArtifacts(unittest.TestCase):
    """The original 2025-only package is retained as a fallback and must stay valid."""

    @classmethod
    def setUpClass(cls):
        cls.legacy = json.loads((ROOT / 'data/history/profiles.json').read_text())
        cls.choices = json.loads((ROOT / 'data/history/choice_sets.json').read_text())

    def test_legacy_coverage_and_preliminary_agreement(self):
        report = self.legacy['report']
        self.assertEqual(report['coverage']['discretionary'], 120)
        self.assertEqual(report['coverage']['adp_covered_live'], 116)
        self.assertEqual(report['preliminary_disagreements'], [])
        self.assertEqual({r['slot'] for r in report['ownership_departures']}, {47, 93, 96, 97, 107, 113})

    def test_legacy_keeper_removed_before_slot_one(self):
        choices = self.choices['choices']
        self.assertEqual(len(choices), 116)
        shai = next(pid for pid, p in self.choices['players'].items() if p['name'] == 'Shai Gilgeous-Alexander')
        self.assertNotIn(shai, choices[0]['available_ids'])
        available = set(choices[0]['available_ids'])
        for c in choices:
            selected = c['available_ids'][c['selected_index']]
            self.assertIn(selected, available)
            available.discard(selected)

    def test_legacy_regularization_helpers(self):
        coef, sd = fit_choices([], [1.4, 0], [25, 50])
        self.assertEqual(coef, [1.4, 0])
        self.assertTrue(all(x > 0 for x in sd))
        for profile in self.legacy['profiles'].values():
            for stage in profile['learned']['phases'].values():
                if stage['n'] < 4:
                    self.assertTrue(stage['prior_only'])


class MonteCarloTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=Data();cls.engine=Engine(cls.data)

    def setUp(self):
        self.store=Store(':memory:',self.data)

    def tearDown(self):
        self.store.db.close()

    def test_survival_is_frequency_reproducible_and_adaptive(self):
        state=self.store.state()
        before=copy.deepcopy(state)
        a=self.engine.draft_model.survival(state,trials=50)
        b=self.engine.draft_model.survival(state,trials=50)
        self.assertEqual(a,b);self.assertEqual(state,before)
        case=a['scenarios'][0]
        # Board is fully resolved under confirmed ownership: no barrier, and horizons are
        # our next two owned live picks (#6, #43).
        self.assertIsNone(case['barrier'])
        self.assertEqual(case['horizons'], [6, 43])
        for row in case['estimates'].values():
            for h in row.values():
                if h['probability'] is not None:
                    self.assertEqual(h['probability'],h['successes']/h['n'])
                    self.assertTrue(0<=h['probability']<=1)
        jokic=next(p['id'] for p in self.data.players.values() if p['name']=='Nikola Jokic')
        self.store.append('pick',{'slot':1,'player_id':jokic})
        changed=self.engine.draft_model.survival(self.store.state(),trials=50)
        self.assertNotIn(jokic,changed['scenarios'][0]['estimates'])

    def test_later_uncertainty_censored_and_not_guessed(self):
        state=self.store.state()
        # Inject an unresolved asset so later horizons are censored (fail-closed) and
        # never fabricated. Ownership is otherwise confirmed.
        state['slots'][105]['current_team']=''
        # Focus on the last two actual remaining user picks; no fictitious owner.
        for slot in state['slots']:
            if slot['current_team']=='Oscar' and slot['slot']<102 and not slot['keeper']:
                slot.update(player_id='manual:test-'+str(slot['slot']),player_name='Test')
        # Use known player identities rather than fabricated stats for roster replay.
        for s,p in zip([s for s in state['slots'] if s['player_id']], [p for p in self.data.players.values() if not p['keeper']]):
            s['player_id']=p['id'];s['player_name']=p['name']
        state['drafted']=[s['player_id'] for s in state['slots'] if s['player_id']]
        report=self.engine.draft_model.survival(state,trials=50)
        self.assertEqual(report['scenarios'][0]['barrier']['slot'],106)
        example=next(iter(report['scenarios'][0]['estimates'].values()))
        self.assertEqual(example['later']['slot'],115)
        self.assertTrue(example['later']['censored'])
        self.assertIsNone(example['later']['probability'])

    def test_explicit_complete_scenario_and_full_remaining_samples(self):
        scenario={'name':'Test hypothetical ONLY, not confirmed facts',
                  'owners':{'106':'Raul','113':'Samet','123':'Nick'},
                  'keeper_slots':{'111':'VJ Edgecombe','113':'Dylan Harper','123':'Jabari Smith Jr.','128':'Ace Bailey'}}
        state=self.store.state();before=copy.deepcopy(state)
        hypothetical=apply_scenario(state,scenario,self.data)
        self.assertIsNone(uncertainty_barrier(hypothetical,self.data))
        self.assertEqual(state,before)
        self.store.append('settings',{'draft_scenarios':[scenario],'mc_trials':50})
        report=self.engine.draft_model.survival(self.store.state())
        case=report['scenarios'][0]
        self.assertIsNone(case['barrier'])
        self.assertEqual(case['full_paths_n'],16)
        for trace in case['full_remaining_paths']:
            self.assertEqual(len(trace),121)
            self.assertEqual(len(set(p['player_id'] for p in trace)),121)
            self.assertFalse(any(self.data.players[p['player_id']]['keeper'] for p in trace))
        self.assertFalse(report['averaged_scenarios'])
        self.assertEqual(self.store.state()['slots'][105]['current_team'],'Raul')

    def test_override_validation_and_model_not_fitted_from_override(self):
        with self.assertRaises(ValueError):self.store.append('settings',{'manager_overrides':{'Shiven':{'adherence':0}}})
        with self.assertRaises(ValueError):self.store.append('settings',{'draft_scenarios':[{'name':'Bad','owners':{'106':'Unknown'}}]})
        observed=copy.deepcopy(self.data.history_package['profiles']['Shiven']['observations'])
        self.store.append('settings',{'manager_overrides':{'Shiven':{'adherence':3.5,'rookie':.5}},'draft_model':'auto'})
        params=self.engine.draft_model.parameters('Shiven',1,self.store.state()['settings'])
        self.assertEqual(params[0],3.5);self.assertEqual(params[2],.5)
        self.assertEqual(self.data.history_package['profiles']['Shiven']['observations'],observed)
        self.assertEqual(self.engine.draft_model.mode(self.store.state()['settings']),'baseline')

    def test_confidence_interval_is_not_zero_width_at_zero(self):
        interval=wilson(0,300)
        self.assertEqual(interval[0],0)
        self.assertGreater(interval[1],0)


if __name__=='__main__':unittest.main()
