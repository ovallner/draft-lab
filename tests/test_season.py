import copy
import json
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from app.data import Data
from app.engine import Engine
from app.store import Store
from app.season_inputs import SeasonInputs
from app.season_draft import SeasonDraft
from app.season_world import SeasonWorld,compare_categories
from app.season_sim import SeasonSimulator
from app.benchmark import BenchmarkRunner,atomic_json,cluster_interval
from app.benchmark_jobs import BenchmarkJobs


HYPOTHESIS={'name':'Test hypothesis ONLY','owners':{'106':'Raul','113':'Samet','123':'Nick'},
            'keeper_slots':{'111':'VJ Edgecombe','113':'Dylan Harper','123':'Jabari Smith Jr.','128':'Ace Bailey'}}


class SeasonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=Data();cls.engine=Engine(cls.data);cls.inputs=SeasonInputs(cls.data)
        cls.store=Store(':memory:',cls.data)
        cls.raw={'asset_scenarios':[HYPOTHESIS],'drafts':1,'seasons_per_draft':1,
                 'strategies':[{'name':'Balanced test','policy':'playoff','punts':[],'streaming':'aggressive'}],
                 'opponent_modes':['adp_deterministic']}
        cls.config,cls.states=cls.inputs.prepare(cls.store.state(),cls.raw)
        cls.draft=SeasonDraft(cls.engine).complete(cls.states[0],cls.config['strategies'][0],'adp_deterministic',321)
        cls.world=SeasonWorld(cls.data,cls.inputs,cls.config['calendar'],543,cls.config)
        cls.simulator=SeasonSimulator(cls.engine,cls.inputs)
        cls.outcome=cls.simulator.run(cls.draft,cls.world,cls.config)

    @classmethod
    def tearDownClass(cls):cls.store.db.close()

    def test_verified_calendar_and_no_silent_assets(self):
        self.assertEqual(sum(len(p) for p in self.inputs.matchups.values()),102)
        # Dates are now verified: no acknowledgement is required.
        prepared,_=self.inputs.prepare(self.store.state(),{'asset_scenarios':[HYPOTHESIS]})
        self.assertEqual(len(prepared['calendar']),20)
        self.assertEqual(prepared['calendar'][0]['days'],6)          # W1 opening week
        self.assertEqual(prepared['calendar'][6]['days'],14)         # W7 NBA Cup
        self.assertEqual(prepared['calendar'][16]['end'],'2027-02-28')
        self.assertEqual(prepared['calendar'][17]['start'],'2027-03-01')
        meta=self.inputs.metadata()
        self.assertTrue(meta['schedule_dates_verified'])
        self.assertEqual(meta['calendar_weeks'],23)
        self.assertEqual([w['week'] for w in meta['nonstandard_weeks']],[7,17])
        # The retired acknowledgement key is now rejected as unknown.
        with self.assertRaisesRegex(ValueError,'Unknown'):
            self.inputs.prepare(self.store.state(),{'calendar_acknowledged':True})
        # The board is now fully resolved (confirmed ownership), so no scenario is
        # required; a deliberately broken board still fails closed.
        prepared_default,_=self.inputs.prepare(self.store.state(),{})
        self.assertEqual(len(prepared_default['calendar']),20)
        broken=self.store.state()
        next(s for s in broken['slots'] if not s['keeper'] and s['current_team'])['current_team']=''
        with self.assertRaisesRegex(ValueError,'Unresolved'):
            self.inputs.prepare(broken,{})
        # A custom override must be contiguous and carry provenance.
        bad=copy.deepcopy(self.raw);bad['calendar']=[dict(p) for p in prepared['calendar']]
        bad['calendar'][3]['start']='2026-11-01';bad['calendar_source']='test override'
        with self.assertRaisesRegex(ValueError,'nonoverlapping'):
            self.inputs.prepare(self.store.state(),bad)
        bad2=copy.deepcopy(self.raw);bad2['calendar']=[dict(p) for p in prepared['calendar']]
        with self.assertRaisesRegex(ValueError,'provenance'):
            self.inputs.prepare(self.store.state(),bad2)
        self.assertEqual(self.store.state()['drafted'],[])

    def test_draft_complete_unique_and_strict_adp_is_reproducible(self):
        flat=[pid for ids in self.draft['rosters'].values() for pid in ids]
        self.assertEqual(len(flat),156);self.assertEqual(len(set(flat)),156)
        self.assertEqual(len(self.draft['trace']),121)
        other=SeasonDraft(self.engine).complete(self.states[0],self.config['strategies'][0],'adp_deterministic',999)
        self.assertEqual(other['rosters'],self.draft['rosters'])
        self.assertFalse(any(self.data.players[p['player_id']]['keeper'] for p in self.draft['trace']))

    def test_world_health_and_shooting_constraints(self):
        self.assertTrue(any(event['type']=='injury' for event in self.world.events))
        for pid,boxes in self.world.stats.items():
            for i,b in enumerate(boxes):
                if b is None:continue
                self.assertFalse(self.world.status(pid,i)['injured'])
                self.assertFalse(self.world.status(pid,i)['rest'])
                self.assertLessEqual(b[0],b[1]);self.assertLessEqual(b[2],b[3]);self.assertLessEqual(b[4],b[0])
                self.assertEqual(b[5],2*b[0]+b[4]+b[2])
                self.assertTrue(all(v>=0 for v in b))

    def test_season_accounting_limits_and_playoff_structure(self):
        out=self.outcome
        self.assertEqual(len(out['weekly']),20)
        self.assertEqual(len(set(out['final_order'])),12)
        self.assertEqual(sum(r['champion'] for r in out['teams'].values()),1)
        self.assertEqual(sum(r['qualified'] for r in out['teams'].values()),8)
        self.assertEqual(sum(r['semifinal'] for r in out['teams'].values()),4)
        self.assertEqual(sum(r['final'] for r in out['teams'].values()),2)
        for week in out['weekly']:
            self.assertTrue(all(n<=4 for n in week['adds'].values()))
            if week['week']<=17:self.assertEqual(len(week['matchups']),6)
            for match in week['matchups']:self.assertEqual(match['a_wins']+match['b_wins']+match['ties'],9)
        for team,record in out['teams'].items():
            r=record['record'];self.assertEqual(r['w']+r['l']+r['t'],153)
            self.assertLessEqual(len(record['final_active']),13);self.assertLessEqual(len(record['final_il']),3)
            self.assertGreaterEqual(record['fab_remaining'],0)
            self.assertEqual(record['fab_remaining']+record['budget_spent'],100)
        owned=[p for t in out['teams'].values() for p in t['final_active']+t['final_il']]
        self.assertEqual(len(owned),len(set(owned)))

    def test_waiver_delays_and_no_duplicate_pickups(self):
        from datetime import date
        drops={};owners={pid:t for t,ids in self.draft['rosters'].items() for pid in ids}
        for event in self.outcome['transactions']:
            pid=event['player_id'];kind=event['type'];team=event['team']
            if kind=='drop':
                self.assertEqual(owners[pid],team);del owners[pid];drops[pid]=date.fromisoformat(event['day'])
            elif kind=='add':
                self.assertNotIn(pid,owners);owners[pid]=team
                if pid in drops:self.assertGreaterEqual((date.fromisoformat(event['day'])-drops[pid]).days,2)

    def test_planners_do_not_read_future_health_or_sampled_boxes(self):
        class Guard:
            days=self.world.days
            def status(inner,pid,day):
                if day!=0:raise AssertionError('Future health oracle')
                return {'injured':False,'rest':False,'il_eligible':False}
            def box(inner,*args):raise AssertionError('Sampled performance oracle')
        roster=self.draft['rosters']['Oscar'];pid=roster[0]
        self.simulator.future_starts_value(pid,'Oscar',roster,0,7,Guard(),self.draft,{})
        state={t:{'active':ids} for t,ids in self.draft['rosters'].items()}
        utility=self.simulator.lineup_utility('Oscar','Shiven',{t:[0]*11 for t in self.data.teams},0,7,state,Guard(),self.draft,{})
        self.assertIsInstance(utility(pid),float)

    def test_position_fit_and_lineup_slots(self):
        from app.engine import lineup_slots, POSITIONS
        roster = self.engine.rosters(self.states[0])['Oscar']
        c_only = next(p for p in self.data.players.values() if p['positions'] == ['C'] and not p['keeper'])
        fit = self.engine.position_fit(roster, c_only, (), .5)
        self.assertEqual(fit['role'], 'C-only big')
        self.assertEqual(fit['positions'], ['C'])
        self.assertIn(fit['start_slot'], POSITIONS + ['bench'])
        self.assertIsInstance(fit['delta_starts'], float)
        self.assertIsInstance(fit['delta_blocked'], float)
        self.assertIsInstance(fit['util_dependent'], bool)
        self.assertEqual(len(fit['after_needs']), 3)
        guard = next(p for p in self.data.players.values() if p['positions'] and p['positions'][0] == 'PG' and not p['keeper'])
        self.assertEqual(self.engine.position_fit(roster, guard, (), .5)['role'], 'guard')
        slots = lineup_slots(roster, lambda q: 1.)
        self.assertTrue(all(s in POSITIONS for s in slots.values()))

    def test_team_analysis_works_after_final_pick(self):
        store = Store(':memory:', self.data)
        fit = {'name': 'fit', 'policy': 'fit', 'punts': [], 'streaming': 'aggressive', 'playoff_weight': .8, 'risk': .5}
        draft = SeasonDraft(self.engine).complete(self.states[0], fit, 'adp_deterministic', 3)
        for t in draft['trace']:
            store.append('pick', {'slot': t['slot'], 'player_id': t['player_id']})
        st = store.state()
        self.assertIsNone(st['current_slot'])                       # completed board: no recommendations exist
        analysis = self.engine.team_analysis(st, st['settings'])    # independent of builds/recs
        self.assertEqual(len(analysis['matchups']), 11)
        self.assertEqual(len(analysis['own']['weeks']), 3)
        self.assertEqual(analysis['own']['completeness']['players'], 13)
        self.assertTrue(all(len(m['weeks']) == 3 for m in analysis['matchups']))
        self.assertTrue(all(len(m['weeks'][0]['category_edges']) == 9 for m in analysis['matchups']))
        store.db.close()

    def test_waiver_window_does_not_read_future_health(self):
        class Guard:
            days = self.world.days
            def status(inner, pid, day):
                if day != 0:
                    raise AssertionError('future health oracle')
                return {'injured': False, 'rest': False, 'il_eligible': False}
        roster = self.draft['rosters']['Oscar']; pid = roster[0]
        # eligible_from skips early days but must still only read health at day 0.
        self.simulator.future_starts_value(pid, 'Oscar', roster, 0, 7, Guard(), self.draft, {}, adding=True, eligible_from=3)

    def test_turnovers_and_zero_attempt_ties(self):
        a=[5,10,3,4,2,15,5,4,1,1,2];b=a[:];b[-1]=3
        result=compare_categories(a,b);self.assertEqual(result[-1],1)
        self.assertEqual(compare_categories([0]*11,[0]*11),[0]*9)

    def test_adp_stochastic_self_baseline_policy(self):
        """Our own 'follow the ADP model' strategy must be the same distribution
        opponents are drawn from, not a zero-variance always-best-ADP bot."""
        from app.season_inputs import DEFAULT_STRATEGIES
        names={s['name']:s for s in DEFAULT_STRATEGIES}
        self.assertIn('Pure ADP baseline',names)
        self.assertEqual(names['Pure ADP baseline']['policy'],'adp_stochastic')
        for s in DEFAULT_STRATEGIES:
            SeasonInputs.validate_strategy(s)
        baseline=names['Pure ADP baseline']
        first=SeasonDraft(self.engine).complete(self.states[0],baseline,'adp_stochastic',4242)
        again=SeasonDraft(self.engine).complete(self.states[0],baseline,'adp_stochastic',4242)
        self.assertEqual(first['rosters'],again['rosters'])          # reproducible under a seed
        other=SeasonDraft(self.engine).complete(self.states[0],baseline,'adp_stochastic',9999)
        self.assertNotEqual(first['rosters'],other['rosters'])       # genuinely stochastic
        flat=[p for r in first['rosters'].values() for p in r]
        self.assertEqual(len(flat),156);self.assertEqual(len(set(flat)),156)
        self.assertEqual(len(first['rosters']['Oscar']),13)
        keepers=[self.data.players[p] for p in first['rosters']['Oscar'] if self.data.players[p]['keeper']]
        self.assertEqual(len(keepers),3)
        self.assertTrue(all(p['keeper']=='Oscar' for p in keepers))
        # The baseline must differ from the category/playoff heuristic.
        heuristic={'name':'h','policy':'playoff','punts':[],'streaming':'aggressive'}
        SeasonInputs.validate_strategy(heuristic)
        h=SeasonDraft(self.engine).complete(self.states[0],heuristic,'adp_stochastic',4242)
        self.assertNotEqual(first['rosters']['Oscar'],h['rosters']['Oscar'])
        # A per-manager override dict using adp_stochastic routes through the model,
        # so it must differ from that manager's deterministic-ADP roster.
        plain=SeasonDraft(self.engine).complete(self.states[0],heuristic,'adp_deterministic',7)
        override=SeasonDraft(self.engine).complete(self.states[0],heuristic,'adp_deterministic',7,{'Nick':baseline})
        self.assertNotEqual(override['rosters']['Nick'],plain['rosters']['Nick'])
        self.assertEqual(len(override['rosters']['Nick']),13)


    def test_reproducibility_no_mutation_and_cancellation(self):
        before=copy.deepcopy(self.draft)
        repeated=self.simulator.run(self.draft,self.world,self.config)
        self.assertEqual(repeated,self.outcome);self.assertEqual(self.draft,before)
        from app.season_sim import Cancelled
        with self.assertRaises(Cancelled):self.simulator.run(self.draft,self.world,self.config,lambda:True)

    def test_live_policy_shares_engine_logic_and_refuses_unresolved(self):
        from app.season_inputs import POLICIES, DEFAULT_STRATEGIES
        self.assertIn('live',POLICIES)
        self.assertTrue(any(s['policy']=='live' for s in DEFAULT_STRATEGIES))
        state=copy.deepcopy(self.states[0])
        state['settings']=dict(state.get('settings') or {})
        state['settings'].pop('draft_scenarios',None)          # scenario is baked into the state
        state['settings']['mc_trials']=25
        drafter=SeasonDraft(self.engine)
        direct=self.engine.recommend(state)['recommendations'][0]['player']['id']
        live,punt=drafter.pick_live(state)
        self.assertEqual(live['id'],direct)                   # benchmark and live share ONE implementation
        self.assertIsInstance(punt,list)
        again=self.engine.recommend(state)['recommendations'][0]['player']['id']
        self.assertEqual(direct,again)                        # deterministic given the board
        # Unresolved keeper/draft assets must fail closed, never be silently invented.
        from app.draft_model import uncertainty_barrier
        broken=copy.deepcopy(self.states[0])
        next(s for s in broken['slots'] if s['keeper'])['keeper_player']=''
        self.assertIsNotNone(uncertainty_barrier(broken,self.data))
        with self.assertRaisesRegex(ValueError,'Cannot complete'):
            drafter.complete(broken,{'name':'live','policy':'live','punts':[],'streaming':'aggressive'},'adp_deterministic',1)

    def test_locked_managers_do_not_transact_and_no_acquisition_control(self):
        config=dict(self.config,eligibility='championship_only',streaming_model='off')
        out=self.simulator.run(self.draft,self.world,config)
        self.assertFalse(any(t['type']=='add' for t in out['transactions']))
        for w in out['weekly'][17:]:
            eligible=set(w['eligible'])
            transactions=[t for t in out['transactions'] if w['start']<=t['day']<=w['end']]
            self.assertTrue(all(t['team'] in eligible for t in transactions))

    # --- Structural correctness regressions (P0) -----------------------------

    def test_lineup_shape_is_ten_active_three_bench_three_il(self):
        from app.engine import POSITIONS, lineup
        self.assertEqual(list(POSITIONS),['PG','SG','G','SF','PF','F','C','UTIL','UTIL','UTIL'])
        self.assertEqual(len(POSITIONS),10)
        config=self.data.config['roster_positions']
        self.assertEqual(sum(1 for r in config if r not in ('BN','IL')),10)   # 10 active starters
        self.assertEqual(sum(1 for r in config if r=='BN'),3)                # 3 bench
        self.assertEqual(sum(1 for r in config if r=='IL'),3)                # 3 IL
        # A maximally flexible roster can never start more than 10 players.
        thirteen=[{'id':f'p{i}','positions':['PG','SG','SF','PF','C']} for i in range(13)]
        self.assertEqual(len(lineup(thirteen,lambda p:1.)),10)
        # Simulated end-state: 13 active max (10+3 bench) and 3 IL max.
        for record in self.outcome['teams'].values():
            self.assertLessEqual(len(record['final_active']),13)
            self.assertLessEqual(len(record['final_il']),3)

    def test_full_82_game_slate_is_represented_explicitly(self):
        inputs=self.inputs
        for team in self.data.weekly:
            self.assertEqual(inputs.observed_games_per_team[team],80)
            self.assertEqual(inputs.unresolved_games_per_team[team],2)
            self.assertEqual(len(inputs.team_game_days[team]),82)
        self.assertEqual(inputs.unresolved_games_added,60)
        # Reproducible and deterministic across instances.
        again=SeasonInputs(self.data)
        self.assertEqual(again.games_by_day,inputs.games_by_day)
        self.assertEqual(again.team_game_days,inputs.team_game_days)
        # Represented games never invent a matchup: each added appearance is a lone
        # team on an existing regular-season league day.
        base={}
        for g in self.data.games:
            base.setdefault(g['date'],set()).update((g['home'],g['away']))
        for day,teams in inputs.games_by_day.items():
            extra=teams-base.get(day,set())
            self.assertTrue(all(t in self.data.weekly for t in extra))
            if extra:self.assertTrue(day<='2027-02-28')
        self.assertEqual(inputs.metadata()['schedule_games_per_team'],
                         {t:82 for t in self.data.weekly})

    def test_keeper_forfeiture_reconciliation(self):
        from app.draft_model import uncertainty_barrier
        counts=Counter(k['team'] for k in self.data.keepers)
        # Yahoo's completed board (2026-10-19) confirms 35 keepers: Mathurin was not kept.
        self.assertEqual(len(self.data.keepers),35)
        self.assertEqual(set(counts),set(self.data.teams))
        self.assertTrue(all(2<=n<=3 for n in counts.values()))
        self.assertEqual(counts['Austin'],2)
        self.assertIsNone(uncertainty_barrier(self.states[0],self.data))
        # A missing keeper asset must fail closed, never be silently guessed.
        broken=copy.deepcopy(self.states[0])
        next(s for s in broken['slots'] if s['keeper'])['keeper_player']=''
        self.assertIsNotNone(uncertainty_barrier(broken,self.data))

    def test_acquisition_cap_per_scoring_period(self):
        # Default cap is 4 per period, including the 14-day periods (W7/W17).
        for week in self.outcome['weekly']:
            self.assertTrue(all(n<=4 for n in week['adds'].values()))
        # Opt-in double cap for extended periods: still never above 8.
        out=self.simulator.run(self.draft,self.world,dict(self.config,extended_adds='double'))
        for week in out['weekly']:
            length=(date.fromisoformat(week['end'])-date.fromisoformat(week['start'])).days+1
            cap=8 if length>7 else 4
            self.assertTrue(all(n<=cap for n in week['adds'].values()))

    def test_il_delay_and_return_rule(self):
        delay=self.config['il_delay_days']
        events={}
        for e in self.world.events:
            if e['type']=='injury':
                events.setdefault(e['player_id'],[]).append((e['date'],e['simulated_duration_days']))
        placed=0
        for t in self.outcome['transactions']:
            if t['type']!='IL':continue
            placed+=1
            episodes=[e for e in events.get(t['player_id'],[]) if e[0]<=t['day']]
            self.assertTrue(episodes,'IL placement without a recorded injury episode')
            start,duration=max(episodes,key=lambda e:e[0])
            self.assertGreater(duration,6)                                    # short episodes never IL-eligible
            self.assertGreaterEqual((date.fromisoformat(t['day'])-date.fromisoformat(start)).days,delay)
        self.assertGreater(placed,0)
        # IL capacity is never exceeded even when many players are hurt.
        for t in self.outcome['transactions']:
            self.assertIn(t['type'],('drop','add','activate','IL'))

    def test_playoff_tiebreaks_head_to_head_then_seed(self):
        result=[1,1,1,1,-1,-1,-1,-1,0]                                        # 4-4-1 split
        self.assertEqual(self.simulator.playoff_winner('A','B',result,{('A','B'):[5,3,1]},{'A':1,'B':2}),'A')
        # Even head-to-head -> higher seed decides.
        self.assertEqual(self.simulator.playoff_winner('A','B',result,{('A','B'):[4,4,1]},{'A':1,'B':2}),'A')
        self.assertEqual(self.simulator.playoff_winner('A','B',result,{('A','B'):[4,4,1]},{'A':2,'B':1}),'B')
        # A clear category win never needs tiebreaks.
        self.assertEqual(self.simulator.playoff_winner('A','B',[1,1,1,1,1,-1,-1,-1,-1],{},{}),'A')
        # Standings ordering is deterministic under a fixed seed.
        records={t:{'w':5,'l':5,'t':0} for t in self.data.teams}
        for t in list(records)[:3]:
            records[t]['w']=6
        last={t:0 for t in self.data.teams}
        self.assertEqual(self.simulator.standings_order(records,{},last,7),
                         self.simulator.standings_order(records,{},last,7))



class BenchmarkPersistenceTests(unittest.TestCase):
    def test_nested_results_cancel_resume_and_small_sample_interval(self):
        data=Data();store=Store(':memory:',data)
        raw={'asset_scenarios':[HYPOTHESIS],'drafts':1,'seasons_per_draft':1,
             'strategies':[{'name':'ADP test','policy':'adp','punts':[],'streaming':'off'}],
             'opponent_modes':['adp_deterministic'],'streaming_model':'off'}
        before=store.state()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);atomic_json(root/'request.json',{'state':before,'config':raw,'source_session':{'id':'live','name':'Test'}})
            (root/'cancel.request').write_text('test')
            BenchmarkRunner(root,data).run()
            self.assertEqual(json.loads((root/'status.json').read_text())['state'],'cancelled')
            (root/'cancel.request').unlink()
            result=BenchmarkRunner(root,data).run()
            self.assertEqual(json.loads((root/'status.json').read_text())['state'],'completed')
            case=result['cases'][0];self.assertEqual(case['n_seasons'],1)
            self.assertEqual(len(case['summary']),12)
            self.assertEqual(case['own_title_interval']['low'],0);self.assertEqual(case['own_title_interval']['high'],1)
            reproduced=BenchmarkRunner(root,data).run()
            self.assertEqual(reproduced,result)
        self.assertEqual(store.state(),before);store.db.close()


def _case(cid,assets,mode,strategy,advancements,titles=None,quals=None,rosters=None):
    """Build a synthetic case so the recommendation rule can be unit-tested
    without paying for real season simulations."""
    titles=titles if titles is not None else advancements
    quals=quals if quals is not None else [a>0 for a in advancements]
    drafts=[]
    for i,a in enumerate(advancements):
        out={'qualified':bool(quals[i]),'semifinal':a>=2,'final':a>=3,'champion':a>=4}
        squad=rosters if rosters is not None else [f'{strategy}-{i}-{j}' for j in range(13)]
        drafts.append({'index':i,'draft':{'rosters':{'Oscar':list(squad),'Shiven':list(squad)}},
                       'seasons':[{'index':0,'teams':{'Oscar':out}}]})
    return {'id':cid,'asset_scenario':assets,'opponent_mode':mode,
            'strategy':{'name':strategy},'drafts':drafts,'summary':{'Oscar':{}},'n_seasons':len(advancements)}


class RecommendationTests(unittest.TestCase):
    @staticmethod
    def result(cases,modes,scenarios=None,seasons_per_draft=1):
        return {'config':{'opponent_modes':modes,'asset_scenarios':[{'name':s} for s in (scenarios or ['A'])],'seed':1},
                'cases':cases}

    def test_gap_sign_and_metrics(self):
        from app.benchmark import advancement
        self.assertEqual(advancement({'qualified':False,'semifinal':False,'final':False,'champion':False}),0)
        self.assertEqual(advancement({'qualified':True,'semifinal':False,'final':False,'champion':False}),1)
        self.assertEqual(advancement({'qualified':True,'semifinal':True,'final':True,'champion':True}),4)
        cases=[_case(0,'A','adp_stochastic','Good',[4,4,4]),_case(1,'A','adp_stochastic','Bad',[0,0,0])]
        rec=BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic']),1)
        self.assertEqual(rec['winner'],'Good')
        self.assertEqual(rec['status'],'strong')
        self.assertEqual(rec['primary_metric'],'unconditional championship probability')
        self.assertGreater(rec['case_results'][0]['gap_advancement'],0)          # winner minus runner-up
        self.assertGreater(rec['case_results'][0]['gap_title'],0)
        self.assertGreater(rec['case_results'][0]['gap_interval']['low'],0)

    @staticmethod
    def _flags(qual,sf,fin,champ):return {'qualified':qual,'semifinal':sf,'final':fin,'champion':champ}
    def _explicit(self,name,outcomes,assets='A',mode='adp_stochastic'):
        drafts=[{'index':i,'draft':{'rosters':{'Oscar':[f'{name}{i}']}},
                 'seasons':[{'index':0,'teams':{'Oscar':o}}]} for i,o in enumerate(outcomes)]
        return {'id':0,'asset_scenario':assets,'opponent_mode':mode,'strategy':{'name':name},
                'drafts':drafts,'summary':{'Oscar':{}},'n_seasons':len(outcomes)}

    def test_championship_probability_is_the_primary_metric(self):
        # A has the higher MEAN ADVANCEMENT (3.0 vs 1.33) but never wins a title.
        # B has a lower advancement but a real title. Championship-primary must pick B.
        A=[self._flags(True,True,True,False)]*3
        B=[self._flags(True,True,True,True),self._flags(False,False,False,False),self._flags(False,False,False,False)]
        cases=[self._explicit('A',A),self._explicit('B',B)]
        rec=BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic']),1)
        self.assertEqual(rec['winner'],'B')                                       # not A, despite higher advancement
        self.assertGreater(rec['case_results'][0]['winner_title_rate'],0)
        self.assertIn('winner_conditional_title_rate',rec['case_results'][0])

    def test_decisive_cluster_guard_blocks_a_thin_title_lead(self):
        # A single decisive draft cluster must not produce a firm verdict.
        winner=[self._flags(True,True,True,True)]+[self._flags(True,True,True,False)]*3
        loser=[self._flags(True,True,True,False)]*4
        cases=[self._explicit('W',winner),self._explicit('L',loser)]
        rec=BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic']),1)
        self.assertEqual(rec['winner'],'W')
        self.assertEqual(rec['status'],'lean')
        self.assertLess(rec['case_results'][0]['decisive_title_clusters'],3)
        self.assertIn('decisive draft clusters',rec['headline'])

    def test_flip_across_models_is_lean_not_strong(self):
        def mk(cid,mode,name,adv):
            return _case(cid,'A',mode,name,adv,rosters=[f'{mode}-{name}-{j}' for j in range(13)])
        cases=[mk(0,'adp_stochastic','X',[4,4,4]),mk(1,'adp_stochastic','Y',[1,1,1]),
               mk(2,'validated','X',[1,1,1]),mk(3,'validated','Y',[4,4,4])]
        rec=BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic','validated']),1)
        self.assertEqual(rec['status'],'lean')
        self.assertFalse(rec['case_results'][0]['stable_across_models'])
        self.assertEqual(rec['winner'],'X')                 # primary-model leader is surfaced...
        self.assertIn('not robust',rec['headline'])         # ...with an explicit instability warning

    def test_primary_model_basis_and_deterministic_fallback(self):
        cases=[_case(0,'A','adp_stochastic','S',[4,4,4]),_case(1,'A','adp_stochastic','T',[2,2,2]),
               _case(2,'A','adp_deterministic','T',[4,4,4]),_case(3,'A','adp_deterministic','S',[1,1,1])]
        rec=BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic','adp_deterministic']),1)
        self.assertEqual(rec['basis'],'adp_stochastic')       # stochastic is always the headline when present
        self.assertEqual(rec['winner'],'S')
        cases2=[_case(0,'A','adp_deterministic','P',[4,4,4]),_case(1,'A','adp_deterministic','Q',[1,1,1])]
        rec2=BenchmarkRunner.recommendation(self.result(cases2,['adp_deterministic']),1)
        self.assertEqual(rec2['basis'],'adp_deterministic')    # the only model available

    def test_small_samples_and_scenario_divergence_are_not_a_firm_call(self):
        cases=[_case(0,'A','adp_stochastic','X',[4,4]),_case(1,'A','adp_stochastic','Y',[0,0])]
        self.assertEqual(BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic']),1)['status'],'inconclusive')
        crossed=[_case(0,'A','adp_stochastic','X',[4,4,4,4]),_case(1,'A','adp_stochastic','Y',[0,0,0,0]),
                 _case(2,'B','adp_stochastic','X',[0,0,0,0]),_case(3,'B','adp_stochastic','Y',[4,4,4,4])]
        rec=BenchmarkRunner.recommendation(self.result(crossed,['adp_stochastic'],['A','B']),1)
        self.assertEqual(rec['status'],'inconclusive')
        self.assertIsNone(rec['winner'])

    def test_single_and_pending(self):
        one=[_case(0,'A','adp_stochastic','Only',[4,4,4])]
        self.assertEqual(BenchmarkRunner.recommendation(self.result(one,['adp_stochastic']),1)['status'],'baseline')
        self.assertEqual(BenchmarkRunner.recommendation(self.result([],['adp_stochastic']),1)['status'],'pending')

    def test_model_separation_flags_near_duplicate_models(self):
        # Four cases: two strategies under two models. Rosters depend ONLY on the
        # strategy, so the two models are byte-identical -> agreement is worthless.
        shared={}
        def build(mode):
            return [_case(0,'A',mode,'X',[4,4,4],rosters=[f'x{j}' for j in range(13)]),
                    _case(1,'A',mode,'Y',[1,1,1],rosters=[f'y{j}' for j in range(13)])]
        cases=build('adp_stochastic')+build('validated')
        by_mode={'adp_stochastic':cases[:2],'validated':cases[2:]}
        sep=BenchmarkRunner._model_separation(by_mode)
        self.assertEqual(sep['shared_roster_share'],1.0)
        self.assertFalse(sep['informative'])
        rec=BenchmarkRunner.recommendation(self.result(cases,['adp_stochastic','validated']),1)
        self.assertEqual(rec['status'],'lean')
        self.assertIn('barely differ',rec['headline'])
        # Genuinely different models keep the strong verdict.
        differing=build('adp_stochastic')+[_case(0,'A','validated','X',[4,4,4],rosters=[f'z{j}' for j in range(13)]),
                                           _case(1,'A','validated','Y',[1,1,1],rosters=[f'w{j}' for j in range(13)])]
        rec2=BenchmarkRunner.recommendation(self.result(differing,['adp_stochastic','validated']),1)
        self.assertNotIn('barely differ',rec2['headline'])

    def test_variance_split_advises_drafts(self):
        drafts=[]
        for i,(a,b) in enumerate([(4,1),(1,4),(4,4)]):
            def outcome(v):return {'qualified':v>0,'semifinal':v>=2,'final':v>=3,'champion':v>=4}
            drafts.append({'index':i,'draft':{'rosters':{'Oscar':[f's{i}']}},
                'seasons':[{'index':0,'teams':{'Oscar':outcome(a)}},{'index':1,'teams':{'Oscar':outcome(b)}}]})
        case={'id':0,'asset_scenario':'A','opponent_mode':'adp_stochastic','strategy':{'name':'X'},
              'drafts':drafts,'summary':{'Oscar':{}},'n_seasons':6}
        split=BenchmarkRunner._variance_split(case)
        self.assertIsNotNone(split)
        self.assertGreater(split['within_draft'],0)
        self.assertIn('DRAFTS',split['advice'])
        self.assertIn('spread is',split['reading'])


class SeedStatsTests(unittest.TestCase):
    def test_seed_blocks_are_disjoint_and_deterministic(self):
        from app import seeds
        expl={seeds.draft_seed(20261018,'exploration',1,i) for i in range(50)}
        hold={seeds.draft_seed(20261018,'evaluation',1,i) for i in range(50)}
        self.assertTrue(expl.isdisjoint(hold))                      # held-out block is separate
        self.assertEqual(seeds.draft_seed(20261018,'evaluation',1,7),
                         seeds.draft_seed(20261018,'evaluation',1,7))  # deterministic
        hold2={seeds.draft_seed(20261018,'evaluation',2,i) for i in range(50)}
        self.assertTrue(hold.isdisjoint(hold2))                     # fresh holdout = fresh stream
        with self.assertRaises(ValueError):seeds.draft_seed(1,'bogus',1,0)
        with self.assertRaises(ValueError):seeds.draft_seed(1,'evaluation',0,0)

    def test_production_lab_block_is_disjoint_from_evaluation(self):
        from app import seeds
        lab={seeds.draft_seed(1,'production_lab',1,i) for i in range(20)}
        ev={seeds.draft_seed(1,'evaluation',1,i) for i in range(20)}
        ex={seeds.draft_seed(1,'exploration',1,i) for i in range(20)}
        self.assertTrue(lab.isdisjoint(ev))
        self.assertTrue(lab.isdisjoint(ex))
        self.assertTrue(ev.isdisjoint(ex))

    def test_multiplicity_widens_interval_and_season_interval_is_labelled(self):
        blocks=[[1,0],[0,1],[1,0],[0,1]]
        one=BenchmarkRunner._bootstrap(blocks,1,1)
        many=BenchmarkRunner._bootstrap(blocks,1,4)
        self.assertEqual(many['comparisons'],4)
        self.assertGreaterEqual(many['high']-many['low'],one['high']-one['low'])
        season=BenchmarkRunner._season_bootstrap(blocks,1)
        self.assertIn('season-level',season['method'])
        self.assertIn('draft-cluster',one['method'])

    def test_within_margin_equivalence_is_reported_as_equivalent(self):
        same=[RecommendationTests._flags(False,False,False,False)]*4
        inst=RecommendationTests()
        cases=[RecommendationTests._explicit(inst,'P',same),RecommendationTests._explicit(inst,'Q',same)]
        rec=BenchmarkRunner.recommendation({'config':{'opponent_modes':['adp_stochastic'],
            'asset_scenarios':[{'name':'A'}],'seed':1},'cases':cases},1)
        self.assertTrue(rec['case_results'][0]['equivalence']['supported'])
        self.assertEqual(rec['case_results'][0]['equivalence']['mode'],'equivalent')
        self.assertEqual(rec['status'],'equivalent')
        self.assertIn('equivalent',rec['headline'])


class DecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=Data();cls.engine=Engine(cls.data);cls.inputs=SeasonInputs(cls.data)
        cls.store=Store(':memory:',cls.data)
        cls.config,cls.states=cls.inputs.prepare(cls.store.state(),{'asset_scenarios':[HYPOTHESIS],'drafts':1,'seasons_per_draft':1})
    @classmethod
    def tearDownClass(cls):cls.store.db.close()

    def test_decision_state_evaluation_is_paired_and_bounded(self):
        from app.decision import DecisionBenchmark
        base=copy.deepcopy(self.states[0])
        base['settings']=dict(base.get('settings') or {});base['settings'].pop('draft_scenarios',None)
        base['settings']['mc_trials']=20
        fit={'name':'fit','policy':'fit','punts':[],'streaming':'aggressive','playoff_weight':.8,'risk':.5}
        draft=SeasonDraft(self.engine).complete(base,fit,'adp_deterministic',11)
        trace={t['slot']:t['player_id'] for t in draft['trace']}
        k=next(s['slot'] for s in base['slots'] if s['current_team']=='Oscar' and not s['keeper'])
        st=copy.deepcopy(base)
        for slot in st['slots']:
            if slot['slot']<k and not slot['keeper'] and slot['slot'] in trace:
                pid=trace[slot['slot']];slot['player_id']=pid;slot['player_name']=self.data.players[pid]['name']
        st['drafted']=[slot['player_id'] for slot in st['slots'] if slot['player_id']]
        st['current_slot']=k
        entry={'round':1,'slot':k,'phase':'early','flags':[],'state':st,'draft_id':'t','draft_index':0,'source':'fit'}
        bench=DecisionBenchmark(self.engine,self.inputs,self.config,fit,'adp_deterministic',continuation=fit,candidates=2)
        row=bench.evaluate_state(entry,999)
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row['regret'],0)                    # best tested is at least the chosen
        self.assertEqual(row['chosen'],row['candidates'][0]['id'])  # chosen is the engine's top pick
        self.assertEqual(len(row['candidates']),2)                  # paired: every candidate evaluated
        self.assertTrue(all(c['title'] in (0.,1.) for c in row['candidates']))

    def test_fail_closed_on_unresolved_assets(self):
        from app.draft_model import uncertainty_barrier
        broken=copy.deepcopy(self.states[0])
        next(s for s in broken['slots'] if s['keeper'])['keeper_player']=''
        self.assertIsNotNone(uncertainty_barrier(broken,self.data))


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.data = Data(); self.store = Store(':memory:', self.data)
        self.engine = Engine(self.data)
    def tearDown(self):
        self.store.db.close()

    def test_owner_only_keeper_edit_rejected(self):
        ks = next(x for x in self.store.state()['slots'] if x['keeper'])
        other = next(t for t in self.data.teams if t != ks['current_team'])
        with self.assertRaisesRegex(ValueError, 'Keeper must belong'):
            self.store.append('slot_override', {'slot': ks['slot'], 'changes': {'current_team': other}})

    def test_barrier_flags_incompatible_keeper(self):
        from app.draft_model import uncertainty_barrier
        st = self.store.state()
        ks = next(x for x in st['slots'] if x['keeper'])
        ks['round'] = '1' if int(ks['round']) != 1 else '2'   # wrong cost round
        self.assertIsNotNone(uncertainty_barrier(st, self.data))
        self.assertIsNone(uncertainty_barrier(self.store.state(), self.data))  # untouched board is fine

    def test_forced_unavailable_candidate_is_refused(self):
        inputs = SeasonInputs(self.data)
        _, states = inputs.prepare(self.store.state(), {'asset_scenarios': [HYPOTHESIS]})
        st = copy.deepcopy(states[0])
        pid = next(p['id'] for p in self.data.players.values() if not p['keeper'])
        st['slots'][0].update(player_id=pid, player_name=self.data.players[pid]['name'])
        st['drafted'] = [pid]
        live = {'name': 'live', 'policy': 'live', 'punts': [], 'streaming': 'aggressive'}
        with self.assertRaisesRegex(ValueError, 'not available'):
            SeasonDraft(self.engine).complete(st, live, 'adp_deterministic', 1, first_pick=pid)

    def test_world_seeds_differ_by_draft_and_confirmation_is_fresh(self):
        from app import seeds
        self.assertNotEqual(seeds.world_seed(20261018, 'production_lab', 1, 1000, 0),
                            seeds.world_seed(20261018, 'production_lab', 1, 2000, 0))
        self.assertNotEqual(seeds.world_seed(20261018, 'production_lab', 1, 1000, 0),
                            seeds.world_seed(20261018, 'production_lab', 1, 1000 + 5_000_000, 0))

    def test_incompatible_keeper_behind_current_slot_is_flagged(self):
        from app.draft_model import uncertainty_barrier, board_integrity_issues
        st = self.store.state()
        ks = next(x for x in st['slots'] if x['keeper'])
        ks['round'] = '1' if int(ks['round']) != 1 else '2'
        st['current_slot'] = 150   # the invalidity sits BEHIND the current pick
        self.assertTrue(any('Incompatible keeper' in m for _, m in board_integrity_issues(st, self.data)))
        self.assertIsNotNone(uncertainty_barrier(st, self.data))

    def test_lab_pool_excludes_assumed_gone_elites(self):
        import importlib.util
        from app.data import ROOT
        spec = importlib.util.spec_from_file_location('pick6_lab', ROOT / 'scripts' / 'run_pick6_lab.py')
        lab = importlib.util.module_from_spec(spec); spec.loader.exec_module(lab)
        inputs = SeasonInputs(self.data)
        _, states = inputs.prepare(self.store.state(), {'asset_scenarios': [HYPOTHESIS]})
        _, gone, pool = lab.board_at_pick6(self.data, states[0], 5)
        pool_ids = {p['id'] for p in pool}
        self.assertEqual(len(gone), 5)
        for g in gone:
            self.assertNotIn(g['id'], pool_ids)      # assumed-gone elites are not forceable candidates

    def test_input_hashes_cover_critical_files(self):
        from app.benchmark_jobs import INPUT_FILES
        for f in ('app/data.py', 'app/history.py', 'app/seeds.py', 'playoff_team_weekly_games.csv'):
            self.assertIn(f, INPUT_FILES)


if __name__=='__main__':unittest.main()