import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'scripts'))
from policy_audit_worker import featured, seed, setup, fit_scores, FIT, hashed, playbook_choice, AuditDraft
from policy_audit import verify, lock_run, source_hashes, Supervisor, counts, task, tasks
from app.season_draft import SeasonDraft


class PolicyAuditTests(unittest.TestCase):
    def test_featured_matches_ui_contract_including_null_and_all_contingent(self):
        a={'player':{'id':'a'},'availability_at_next':.4};b={'player':{'id':'b'},'availability_at_next':.5}
        c={'player':{'id':'c'},'availability_at_next':None}
        self.assertEqual(featured([a,b,c]),[b,c]);self.assertEqual(featured([a]),[a])

    def test_new_paired_namespace_does_not_depend_on_policy_or_model(self):
        worlds={seed('world',lane,stage,i,j) for lane in ('pilot','main') for stage in ('primary','sensitivity','adverse') for i in range(30) for j in range(3)}
        self.assertEqual(len(worlds),540)
        self.assertNotEqual(seed('draft','main','primary',0),seed('draft','pilot','primary',0))

    def test_fit_replica_matches_shared_baseline(self):
        data,engine,_,_,base=setup();drafter=SeasonDraft(engine)
        pool=[p for p in data.players.values() if not p['keeper']];roster=engine.rosters(base)['Oscar']
        for extra in (0,4,7):
            rr=roster+pool[:extra];pp=pool[extra:]
            scores=fit_scores(engine,rr,pp)
            self.assertEqual(drafter.pick(pp,rr,FIT)['id'],max(scores,key=scores.get))

    def test_playbook_skips_already_selected_player(self):
        book={'branches':{'a':{'policy':{'rank43':['gone','b'],'rank54':{'b':['b','c']},'default54':['c'],'fallback':['d']}}}}
        self.assertEqual(playbook_choice(book,43,'a',None,{'b','c'}),'b')
        self.assertEqual(playbook_choice(book,54,'a','b',{'c'}),'c')
        self.assertIsNone(playbook_choice(book,43,'unknown',None,{'x'}))

    def test_correct_owned_picks_and_keepers(self):
        data,engine,_,_,base=setup()
        self.assertEqual([s['slot'] for s in base['slots'] if s['current_team']=='Oscar' and not s['keeper']],[6,43,54,67,78,91,102,115,126,150])
        self.assertEqual(len(engine.rosters(base)['Oscar']),3)

    def test_mutation_refuses_resume_and_lock_excludes_second_runner(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);(run/'source').mkdir();p=run/'source/input';p.write_text('original')
            (run/'manifest.json').write_text(json.dumps({'python':list(sys.version_info[:2]),'hashes':source_hashes(run/'source')}))
            verify(run);p.write_text('changed')
            with self.assertRaisesRegex(ValueError,'Frozen inputs changed'):verify(run)
            first=lock_run(run)
            try:
                with self.assertRaisesRegex(ValueError,'Another process'):lock_run(run)
            finally:first.close()

    def test_only_four_policy_completion_counts_as_complete_path(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);p=run/'main/tasks';p.mkdir(parents=True)
            for policy in ('production','adp','fit'):(p/f'primary.adp_stochastic.0000.{policy}.json').write_text('{}')
            self.assertEqual(counts(run,'main')['completed_independent_paths'],{})
            (p/'primary.adp_stochastic.0000.playbook.json').write_text('{}')
            self.assertEqual(counts(run,'main')['completed_independent_paths'],{'primary/adp_stochastic':1})

    def test_resume_budget_carries_elapsed_without_counting_offline_time(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('policy_audit.time.monotonic',return_value=100):s=Supervisor(Path(d),{},'main',1000,200)
            with patch('policy_audit.time.monotonic',return_value=112):self.assertEqual(s.elapsed,212)

    def test_robust_models_accept_text_rounds_and_stay_legal(self):
        # Regression: slot['round'] is a string; every robustness branch must
        # coerce it and still return an available player for both managers.
        data,engine,_,_,base=setup();pool=[p for p in data.players.values() if not p['keeper']]
        for model in ('center_run','guard_run','market_tight','need_pressure'):
            drafter=AuditDraft(engine,{'model':model},None,{},lambda:None,lambda:False)
            for round_text,team in [('1','Shiven'),('5','Shiven'),('7','Shiven'),('13','Shiven'),('5','Oscar')]:
                roster=engine.rosters(base)[team]
                pick=drafter.model_pick(pool,roster,team,round_text,model,base['settings'],.4,{},7)
                self.assertIn(pick['id'],{p['id'] for p in pool})

    def test_robust_models_change_choices_not_just_names(self):
        data,engine,_,_,base=setup();pool=[p for p in data.players.values() if not p['keeper']]
        roster=engine.rosters(base)['Shiven'];decisions={}
        for model in ('adp_stochastic','validated','market_tight','need_pressure','center_run','guard_run'):
            drafter=AuditDraft(engine,{'model':model},None,{},lambda:None,lambda:False)
            decisions[model]=[drafter.model_pick(pool,roster,'Shiven',5,model,base['settings'],u,{},19)['id'] for u in (.1,.4,.7,.95)]
        self.assertNotEqual(decisions['market_tight'],decisions['need_pressure'])
        self.assertNotEqual(decisions['center_run'],decisions['guard_run'])


if __name__=='__main__':unittest.main()
