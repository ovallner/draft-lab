import copy
import unittest

from app.data import Data
from app.engine import Engine
from app.evaluate import RosterEvaluator, projections_hash
from app.season_draft import SeasonDraft
from app.season_inputs import SeasonInputs
from app.store import Store

HYPOTHESIS = {'name': 'Test', 'owners': {'106': 'Raul', '113': 'Samet', '123': 'Nick'},
              'keeper_slots': {'111': 'VJ Edgecombe', '113': 'Dylan Harper',
                               '123': 'Jabari Smith Jr.', '128': 'Ace Bailey'}}
FIT = {'name': 'fit', 'policy': 'fit', 'punts': [], 'streaming': 'aggressive', 'playoff_weight': .8, 'risk': .5}


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Data(); cls.engine = Engine(cls.data); cls.inputs = SeasonInputs(cls.data)
        cls.store = Store(':memory:', cls.data)
        cls.config, cls.states = cls.inputs.prepare(cls.store.state(), {'asset_scenarios': [HYPOTHESIS]})
        cls.evaluator = RosterEvaluator(cls.engine, cls.inputs)

    @classmethod
    def tearDownClass(cls):
        cls.store.db.close()

    def _complete(self):
        draft = SeasonDraft(self.engine).complete(self.states[0], FIT, 'adp_deterministic', 5)
        st = copy.deepcopy(self.states[0])
        trace = {t['slot']: t['player_id'] for t in draft['trace']}
        for s in st['slots']:
            if not s['keeper'] and s['slot'] in trace:
                s['player_id'] = trace[s['slot']]; s['player_name'] = self.data.players[trace[s['slot']]]['name']
        st['drafted'] = [s['player_id'] for s in st['slots'] if s['player_id']]
        st['current_slot'] = None
        return st

    def test_incomplete_draft_is_flagged_not_completed(self):
        st = copy.deepcopy(self.states[0])   # nothing drafted
        issues = self.evaluator.validate(st)
        self.assertTrue(any(i['kind'] == 'incomplete' for i in issues))
        self.assertEqual(len(self.evaluator.engine.rosters(st)['Oscar']), 3)

    def test_snapshot_preserves_every_roster_immutably(self):
        st = self._complete()
        session = {'id': 'mock-x', 'name': 'Mock X', 'mode': 'mock'}
        snap = self.evaluator.snapshot(st, session)
        self.assertEqual(snap['session']['name'], 'Mock X')
        self.assertEqual(len(snap['rosters']), 12)
        self.assertTrue(all(len(v) == 13 for v in snap['rosters'].values()))
        self.assertEqual(sum(len(v) for v in snap['rosters'].values()), 156)
        self.assertEqual(snap['projections_sha256'], projections_hash(self.data))
        self.assertEqual(self.evaluator.validate(st), [])

    def test_fixed_roster_evaluation_runs_and_reports(self):
        st = self._complete()
        snap = self.evaluator.snapshot(st, {'id': 'm', 'name': 'M', 'mode': 'mock'})
        result = self.evaluator.evaluate(snap, self.config, 6, 'aggressive')
        self.assertEqual(result['format'], 'roster-evaluation-v1')
        self.assertEqual(result['season_count'], 6)
        self.assertEqual(set(result['teams']), set(self.data.teams))
        for team, row in result['teams'].items():
            self.assertTrue(0.0 <= row['title_rate'] <= 1.0)
            self.assertTrue(0.0 <= row['qualification_rate'] <= 1.0)
            self.assertTrue(0 <= row['advancement'] <= 4)
        self.assertIn('NOT independent draft constructions', result['note'])
        # repeated seeds are distinct worlds -> the run is not a fixed repeated outcome
        self.assertNotEqual(result['teams']['Oscar']['title_rate'], None)


if __name__ == '__main__':
    unittest.main()
