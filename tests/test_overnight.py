"""Contract checks for the isolated, precomputed overnight policy workflow."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'scripts'))
from overnight_core import (context, seed, prefix, available, PolicyDraft,
                            static_select, Unavailable, stress_state)
from app.season_draft import SeasonDraft
from overnight_report import paired


class OvernightContractTests(unittest.TestCase):
    def test_observable_policy_skips_unavailable_and_no_future_input(self):
        policy={'rank43':['a','b','c'], 'rank54':{'b':['a','d','e']},
                'default54':['d','e'], 'fallback':['f','g']}
        before=copy.deepcopy(policy)
        self.assertEqual(static_select(policy,43,None,['b','c','g']),'b')
        self.assertEqual(static_select(policy,54,'b',['d','e','g']),'d')
        self.assertEqual(static_select(policy,43,None,['g']),'g')
        self.assertIsNone(static_select(policy,54,'unknown',[]))
        self.assertEqual(policy,before)

    def test_seed_phases_worlds_disjoint_and_policy_pairing(self):
        seeds={seed('world',phase,i,j) for phase in ['pilot','screen','deep','confirm','stress']
               for i in range(100) for j in range(3)}
        self.assertEqual(len(seeds),1500)
        self.assertNotEqual(seed('draft','screen',1),seed('draft','confirm',1))
        self.assertEqual(seed('world','confirm',9,0),seed('world','confirm',9,0))

    def test_actual_picks_keepers_prefix_and_no_mutation(self):
        data,engine,_,_,base=context(); original=copy.deepcopy(base)
        state=prefix('adp_stochastic',3,'workflow_test')
        self.assertEqual(state['current_slot'],6)
        self.assertEqual(len(state['drafted']),5)
        self.assertEqual(base,original)
        self.assertEqual([s['slot'] for s in state['slots'] if s['current_team']=='Oscar' and not s['keeper']],
                         [6,43,54,67,78,91,102,115,126,150])

    def test_unavailable_first_pick_never_protected_or_substituted(self):
        data,engine,_,_,_=context()
        state=prefix('adp_stochastic',0,'workflow_test')
        drafter=PolicyDraft(engine,{'first':state['drafted'][0]})
        with self.assertRaises(Unavailable):drafter.pick_live(state)

    def test_after54_calls_shared_production_policy(self):
        _,engine,_,_,base=context()
        state=copy.deepcopy(base);state['current_slot']=67
        drafter=PolicyDraft(engine,{'first':'irrelevant'}, {'id':'simple'})
        with patch.object(SeasonDraft,'pick_live',return_value=('production-player',['TO'])) as production:
            self.assertEqual(drafter.pick_live(state),('production-player',['TO']))
            production.assert_called_once_with(state)

    def test_stress_reassigns_without_duplicate_or_own_pick_loss(self):
        data,engine,_,_,base=context()
        first=next(p['id'] for p in data.players.values() if p['name']=='Karl-Anthony Towns')
        index=next(i for i in range(20) if first in {p['id'] for p in available(prefix('adp_stochastic',i,'stress_test'),data)})
        ids=[p['id'] for p in data.players.values() if not p['keeper'] and p['id']!=first]
        policy={'rank43':ids,'rank54':{},'default54':ids,'fallback':ids}
        task={'phase':'stress_test','index':index,'first':first,'model':'adp_stochastic','stress':'remove43top2'}
        state,swaps=stress_state(task,policy)
        self.assertEqual(state['slots'][5]['player_id'],first)
        self.assertEqual(state['current_slot'],43)
        self.assertEqual(len(state['drafted']),len(set(state['drafted'])))
        self.assertEqual(len(swaps),2)
        self.assertTrue(all(s['inserted'] in state['drafted'] and s['removed'] not in state['drafted'] for s in swaps))

    def test_paired_counts_paths_not_repeated_worlds(self):
        rows=[]
        for i in range(4):
            for p,win in [('a',1),('b',0)]:
                rows.append({'task':{'phase':'confirm','index':i,'first':'first','policy':{'id':p}},
                             'outcomes':[{'seed':seed('world','confirm',i,s),'title':win} for s in range(3)]})
        result=paired(rows,'first/a','first/b',10)
        self.assertEqual(result['paths'],4)
        self.assertEqual(result['difference'],1)
        self.assertFalse(result['equivalent_within_5_points'])
        self.assertLess(result['simultaneous_bounded_95'][0],0)


if __name__=='__main__':unittest.main()
