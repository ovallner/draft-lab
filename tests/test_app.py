import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from app.data import Data, ROOT
from app.engine import Engine, aggregate, lineup, eligible, matchup, seed_scenarios, DEFAULTS
from app.store import Store
from app.server import Application, make_handler
from app.sessions import Sessions
from app.market import apply_market_estimates, market_key
from scripts.fetch_schedule import normalize_schedule


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Data()

    def test_projection_coverage_and_alias(self):
        self.assertEqual(len(self.data.players), 430)
        self.assertEqual(sum(bool(p['keeper']) for p in self.data.players.values()), 35)
        self.assertEqual(next(p['keeper'] for p in self.data.players.values() if p['name'] == 'Alexandre Sarr'), 'Addison')

    def test_oscar_exact_slots(self):
        self.assertEqual([int(s['overall_slot']) for s in self.data.slots if s['current_team'] == 'Oscar' and s['keeper_forfeit_flag'] == 'false'], [6,43,54,67,78,91,102,115,126,150])
        # Confirmed ownership resolves the previously-flagged traded picks.
        self.assertEqual([int(s['overall_slot']) for s in self.data.slots if not s['current_team']], [])
        owners = {int(s['overall_slot']): s['current_team'] for s in self.data.slots}
        self.assertEqual(owners[106], 'Raul')
        self.assertEqual(owners[113], 'Samet')
        self.assertEqual(owners[123], 'Nick')

    def test_schedule_reconciliation(self):
        raw = json.loads((ROOT / 'data/nba_schedule_source.json').read_text())
        games, counts = normalize_schedule(raw)
        self.assertEqual(sum(counts.values()) // 2, 154)
        self.assertEqual(len(games), len({g['id'] for g in games}))
        self.assertTrue(any(g['date'] == '2027-02-28' for g in games))
        self.assertTrue(any(g['date'] == '2027-03-22' for g in games))

    def test_timezone_and_invalid_schedule(self):
        raw = json.loads((ROOT / 'data/nba_schedule_source.json').read_text())
        bad = copy.deepcopy(raw)
        bad.append(bad[0])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            normalize_schedule(bad)
        bad = copy.deepcopy(raw)
        bad[0]['HomeTeam'] = 'Invented Team'
        with self.assertRaisesRegex(ValueError, 'Unknown team'):
            normalize_schedule(bad)
        # Midnight UTC must remain the preceding fantasy day in Eastern time.
        game = next(g for g in self.data.games if g['tipoff_utc'].startswith('2027-03-02T00:'))
        self.assertEqual(game['date'], '2027-03-01')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.data = Data()
        self.store = Store(':memory:', self.data)
        self.pid = next(p['id'] for p in self.data.players.values() if p['name'] == 'Nikola Jokic')

    def tearDown(self):
        self.store.db.close()

    def pick(self, slot=1, pid=None):
        return self.store.append('pick', {'slot': slot, 'player_id': pid or self.pid})

    def test_pick_undo_exact_state(self):
        before = self.store.state()
        picked = self.pick()
        self.assertIn(self.pid, picked['drafted'])
        restored = self.store.append('undo', {'event_id': picked['undo_event']})
        for field in ('slots', 'drafted', 'current_slot'):
            self.assertEqual(before[field], restored[field])
        self.assertEqual(len(restored['events']), 2)

    def test_keeper_duplicate_unresolved_and_revision(self):
        keeper = next(p['id'] for p in self.data.players.values() if p['keeper'])
        with self.assertRaisesRegex(ValueError, 'kept'):
            self.pick(pid=keeper)
        with self.assertRaisesRegex(ValueError, 'Keeper slots'):
            self.pick(slot=19)
        # Traded ownership is now CONFIRMED: #106 belongs to Raul, so a pick records it.
        other = next(p['id'] for p in self.data.players.values() if not p['keeper'] and p['id'] != self.pid)
        resolved = self.store.append('pick', {'slot': 106, 'player_id': other})
        self.assertEqual(resolved['slots'][105]['current_team'], 'Raul')
        picked = self.pick()
        with self.assertRaisesRegex(ValueError, 'already drafted'):
            self.pick(slot=2)
        with self.assertRaisesRegex(ValueError, 'another window'):
            self.store.append('clear_pick', {'slot': 1}, revision=0)
        self.assertEqual(picked['revision'], self.store.state()['revision'])

    def test_correction_and_clear_undo(self):
        self.pick()
        other = next(p['id'] for p in self.data.players.values() if p['name'] == 'Luka Doncic')
        corrected = self.store.append('pick', {'slot':1,'player_id':other})
        self.assertNotIn(self.pid, corrected['drafted'])
        self.store.append('undo', {'event_id':corrected['undo_event']})
        self.assertIn(self.pid, self.store.state()['drafted'])
        cleared = self.store.append('clear_pick', {'slot':1})
        self.assertNotIn(self.pid, cleared['drafted'])
        self.store.append('undo', {'event_id':cleared['undo_event']})
        self.assertIn(self.pid, self.store.state()['drafted'])

    def test_owner_and_keeper_reconciliation(self):
        state = self.store.append('slot_override', {'slot':106,'changes':{'current_team':'Nick'}})
        self.assertEqual(state['slots'][105]['current_team'], 'Nick')
        # Ace Bailey currently occupies #123; assigning him to another slot must fail.
        with self.assertRaisesRegex(ValueError, 'already occupies'):
            self.store.append('slot_override', {'slot':128,'changes':{'keeper':True,'keeper_player':'Ace Bailey','player_name':'Ace Bailey'}})
        with self.assertRaisesRegex(ValueError, 'belong'):
            self.store.append('slot_override', {'slot':111,'changes':{'keeper':True,'keeper_player':'Nikola Jokic'}})

    def test_unlisted_identity_and_undo(self):
        custom = {'id':'manual:test','name':'Unlisted Prospect'}
        state = self.store.append('pick', {'slot':1,'player_id':custom['id'],'custom_player':custom})
        self.assertFalse(state['custom_players'][0]['projected'])
        self.store.append('undo', {'event_id':state['undo_event']})
        self.assertEqual(len(self.store.state()['custom_players']), 1)
        self.store.append('pick', {'slot':2,'player_id':'manual:test'})
        with self.assertRaisesRegex(ValueError, 'exists in projections'):
            self.store.append('pick', {'slot':1,'player_id':'manual:duplicate','custom_player':{'id':'manual:duplicate','name':'Nikola Jokic'}})

    def test_invalid_settings(self):
        for payload in ({'risk':2}, {'punt':['FG%','FT%','TO']}, {'punt':['Unknown']}, {'week_weights':[1,0,1]}, {'streaming':'yes'}):
            with self.assertRaises(ValueError):
                self.store.append('settings', payload)

    def test_persistence_backup_atomic_restore(self):
        self.pick()
        self.store.append('settings', {'punt':['TO']})
        backup = self.store.export()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.sqlite3'
            restored = Store(path, self.data)
            restored.restore(backup)
            self.assertEqual(restored.state()['slots'], self.store.state()['slots'])
            restored.db.close()
            reopened = Store(path, self.data)
            self.assertIn(self.pid, reopened.state()['drafted'])
            with self.assertRaisesRegex(ValueError, 'empty draft'):
                reopened.restore(backup)
            reopened.db.close()
            bad_store = Store(':memory:', self.data)
            invalid = copy.deepcopy(backup)
            invalid['events'][1]['payload'] = {'risk':2}
            with self.assertRaises(ValueError):
                bad_store.restore(invalid)
            self.assertEqual(bad_store.events(), [])
            bad_store.db.close()


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Data()
        cls.engine = Engine(cls.data)

    def test_ratio_aggregation(self):
        a = [5,10,1,2,1,10,2,3,1,1,2]
        b = [1,1,9,10,1,10,2,3,1,1,2]
        result = aggregate([a,b])
        self.assertAlmostEqual(result[0], 6/11)
        self.assertAlmostEqual(result[1], 10/12)
        self.assertNotAlmostEqual(result[0], .75)

    def test_turnovers_lower_is_better(self):
        a = [.5,.8,50,700,250,170,40,30,60]
        b = a[:-1] + [90]
        win, categories = matchup(a,b,[.02,.02,10,100,30,30,10,10,15])
        self.assertGreater(categories[-1], .5)
        self.assertGreater(win,.5)

    def test_position_matching_congestion(self):
        roster = [{'id':str(i),'positions':['PG'],'quality':i} for i in range(13)]
        chosen = lineup(roster, lambda p:p['quality'])
        self.assertEqual(len(chosen), 5)  # PG, G, three UTIL
        self.assertEqual({int(p['id']) for p in chosen}, {8,9,10,11,12})
        diverse = [{'id':str(i),'positions':[pos]} for i,pos in enumerate(['PG','SG','SG','SF','PF','PF','C','C','C','C','C','PG','SF'])]
        self.assertEqual(len(lineup(diverse,lambda p:1)),10)

    def test_punt_changes_values(self):
        players = list(self.data.players.values())
        regular = sorted(players, key=lambda p:self.engine.value(p,(),0),reverse=True)[:10]
        punt = sorted(players, key=lambda p:self.engine.value(p,('FT%','TO'),0),reverse=True)[:10]
        self.assertNotEqual([p['id'] for p in regular], [p['id'] for p in punt])

    def test_rankings_keeper_filter_paths_and_streaming(self):
        store = Store(':memory:',self.data)
        result = self.engine.recommend(store.state())
        self.assertEqual(result['next_pick'],6)
        self.assertTrue(result['recommendations'])
        for rec in result['recommendations']:
            self.assertIsNone(rec['player']['keeper'])
            self.assertLessEqual(len(rec['completed_roster']),13)
            self.assertEqual(len(set(rec['completed_roster'])),len(rec['completed_roster']))
        self.assertFalse(result['valuation_incomplete'])
        self.assertIsNone(result['valuation_barrier'])
        settings = dict(result['settings'])
        market = self.engine.market([p for p in self.data.players.values() if not p['keeper']])
        rosters, rest, _ = self.engine.simulate(store.state(),market,(),settings)
        flattened = [p['id'] for r in rosters.values() for p in r]
        self.assertEqual(len(flattened),len(set(flattened)))
        self.assertTrue(all(len(r)<=13 for r in rosters.values()))
        for plan in result['builds'][0]['stream_plans']:
            self.assertLessEqual(plan['adds'],4)
        first = result['recommendations'][0]['player']['id']
        picked = store.append('pick', {'slot':6,'player_id':first})
        changed = self.engine.recommend(picked)
        self.assertEqual(changed['next_pick'],43)
        self.assertNotIn(first, [r['player']['id'] for r in changed['recommendations']])
        store.append('undo',{'event_id':picked['undo_event']})
        restored = self.engine.recommend(store.state())
        self.assertEqual([r['player']['id'] for r in result['recommendations']], [r['player']['id'] for r in restored['recommendations']])
        store.db.close()

    def test_seed_fields_always_include_user_and_are_frozen(self):
        order=[t for t in self.data.teams if t!='Oscar']+['Oscar']
        fields=seed_scenarios(order,'Oscar')
        self.assertEqual(len(fields),3)
        self.assertTrue(all(len(field)==8 and len(set(field))==8 and 'Oscar' in field for field in fields))

    def test_stronger_opponent_lowers_index_with_common_context(self):
        # Includes an opponent outside the baseline seeded field: the uncertain-
        # field component must still see the player handed to that manager.
        engine=Engine.__new__(Engine)
        engine.data=self.data
        base=[.5,.8,50,700,250,170,40,30,75]
        weekly={t:[{'categories':base[:],'totals':[0]*11,'usable_starts':40,'scheduled_games':40,'blocked_games':0} for _ in range(3)] for t in self.data.teams}
        rosters={t:[] for t in self.data.teams}
        engine.forecast=lambda *args:(copy.deepcopy(weekly),{t:[] for t in self.data.teams})
        settings=dict(DEFAULTS,streaming=False)
        context=engine.comparison_context(rosters,(),settings)
        before=engine.evaluate(rosters,(),settings,[],context)
        outside=next(t for t in self.data.teams if t not in context['seeds'][0])
        for w in weekly[outside]:
            w['categories']=[.6,.9,100,1100,400,250,70,50,40]
        after=engine.evaluate(rosters,(),settings,[],context)
        self.assertLess(after['score'],before['score'])

    def test_pick_six_regression_wait_for_edey_and_opponent_denial(self):
        store=Store(':memory:',self.data)
        by_name={p['name']:p for p in self.data.players.values()}
        for slot,name in enumerate(['Nikola Jokic','Cade Cunningham','Victor Wembanyama','Luka Doncic','Tyrese Maxey'],1):
            store.append('pick',{'slot':slot,'player_id':by_name[name]['id']})
        result=self.engine.recommend(store.state())
        self.assertEqual(result['next_pick'],6)
        self.assertNotIn('Zach Edey',[r['player']['name'] for r in result['recommendations']])
        edey=result['candidate_audit'].get(by_name['Zach Edey']['id'])
        if edey:
            self.assertEqual(edey['wait_comparison']['target_slot'],43)
            self.assertTrue(edey['wait_comparison']['preferred'])
        estimate=result['survival']['scenarios'][0]['estimates'][by_name['Zach Edey']['id']]['later']
        self.assertGreater(estimate['probability'],.5)
        # Projection/snapshot dependent. With the Yahoo-reconciled board (35 keepers;
        # Mathurin available) the remaining #6 board is a near-tie and the documented
        # <=0.02 scarcity safeguard selects Clingan. Re-baseline on snapshot changes.
        self.assertEqual(result['recommendations'][0]['player']['name'],'Donovan Clingan')
        self.assertTrue(any(r.get('market_tiebreak') for r in result['recommendations']))
        settings=dict(DEFAULTS,**store.state()['settings'])
        market=self.engine.market([p for p in self.data.players.values() if not p['keeper'] and p['id'] not in store.state()['drafted']])
        trace={}
        rosters,_,selected=self.engine.simulate(store.state(),market,(),settings,candidate=by_name['Zach Edey'],trace=trace)
        giannis=by_name['Giannis Antetokounmpo']['id']
        self.assertTrue(selected)
        self.assertNotEqual(trace[giannis]['team'],'Oscar')
        other_trace={}
        other,_,_=self.engine.simulate(store.state(),market,('FT%',),settings,candidate=by_name['Giannis Antetokounmpo'],trace=other_trace)
        self.assertEqual(other_trace[giannis],{'team':'Oscar','slot':6})
        self.assertFalse(any(p['id']==giannis for t,roster in other.items() if t!='Oscar' for p in roster))
        store.db.close()


class MarketAndMockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = Data()
        cls.engine = Engine(cls.data)

    def test_yahoo_order_and_estimated_fallback(self):
        players = [{'id':'a','rank':1,'adp':2.}, {'id':'b','rank':10,'adp':None},
                   {'id':'c','rank':20,'adp':12.}, {'id':'d','rank':30,'adp':None}]
        apply_market_estimates(players)
        self.assertEqual(players[0]['market_adp'],2.)
        self.assertEqual(players[2]['market_adp'],12.)
        self.assertTrue(players[1]['adp_estimated'])
        self.assertGreater(players[1]['market_adp'],2.)
        self.assertLess(players[1]['market_adp'],12.)
        self.assertGreater(players[-1]['market_adp'],12.)
        ordered=sorted((p for p in self.data.players.values() if p['adp'] is not None),key=market_key)
        self.assertEqual([p['adp'] for p in ordered],sorted(p['adp'] for p in ordered))

    def test_reset_archives_and_live_is_untouched(self):
        sessions=Sessions(':memory:',self.data)
        live=sessions.store()
        pid=next(p['id'] for p in self.data.players.values() if p['name']=='Nikola Jokic')
        live.append('pick',{'slot':1,'player_id':pid})
        live.append('settings',{'punt':['TO']})
        live.append('slot_override',{'slot':106,'changes':{'current_team':'Nick'}})
        before=copy.deepcopy(live.state())
        first=sessions.new_mock()['id']
        self.assertEqual(sessions.store().state()['current_slot'],1)
        self.assertEqual(sessions.store().state()['drafted'],[])
        self.assertEqual(sessions.store().state()['settings']['punt'],['TO'])
        self.assertEqual(sessions.store().state()['slots'][105]['current_team'],'Nick')
        sessions.store().append('pick',{'slot':1,'player_id':pid})
        second=sessions.new_mock()['id']
        self.assertNotEqual(first,second)
        self.assertEqual(sessions.store().state()['drafted'],[])
        sessions.switch(first)
        self.assertIn(pid,sessions.store().state()['drafted'])
        sessions.switch('live')
        self.assertEqual(sessions.store().state(),before)
        sessions.close()

    def test_mock_sessions_survive_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'live.sqlite3'
            sessions=Sessions(path,self.data)
            sid=sessions.new_mock()['id']
            pid=next(p['id'] for p in self.data.players.values() if not p['keeper'])
            sessions.store().append('pick',{'slot':1,'player_id':pid})
            sessions.close()
            restored=Sessions(path,self.data)
            self.assertEqual(restored.active_id,sid)
            self.assertIn(pid,restored.store().state()['drafted'])
            restored.switch('live')
            self.assertEqual(restored.store().state()['drafted'],[])
            restored.close()

    def test_mock_choices_adp_fit_sampling_and_stop_at_user(self):
        store=Store(':memory:',self.data)
        prediction=self.engine.opponent_choices(store.state(),model='adp')
        self.assertEqual(prediction['team'],'Shiven')
        pool=sorted((p for p in self.data.players.values() if not p['keeper']),key=market_key)
        self.assertEqual(prediction['choices'][0]['player_id'],pool[0]['id'])
        self.assertAlmostEqual(sum(c['weight'] for c in prediction['choices']),1)
        fit=self.engine.opponent_choices(store.state(),model='fit')
        self.assertNotEqual([c['score'] for c in fit['choices']],[c['score'] for c in prediction['choices']])
        self.assertEqual(self.engine.sample_opponent(fit,42,0),self.engine.sample_opponent(fit,42,0))
        for slot in range(1,6):
            guess=self.engine.opponent_choices(store.state())
            choice=self.engine.sample_opponent(guess,42,store.state()['revision'])
            self.assertFalse(self.data.players[choice['player_id']]['keeper'])
            store.append('pick',{'slot':slot,'player_id':choice['player_id']})
        blocked=self.engine.opponent_choices(store.state())
        self.assertEqual(blocked['choices'],[])
        self.assertIn('Your turn',blocked['blocked'])
        store.db.close()

    def test_mock_refuses_unknown_owner_and_full_roster(self):
        store=Store(':memory:',self.data)
        store.append('slot_override',{'slot':1,'changes':{'current_team':'Shiven'}})
        # Ownership is confirmed, so inject an unresolved slot locally to exercise the
        # fail-closed message (an unresolved slot is never given to its original owner).
        state=store.state();state['slots'][105]['current_team']='';state['current_slot']=106
        self.assertIn('unresolved',self.engine.opponent_choices(state)['blocked'].lower())
        state['current_slot']=1
        free=[p for p in self.data.players.values() if not p['keeper']]
        for slot,player in zip(state['slots'][1:11],free[:10]):
            slot.update(current_team='Shiven',player_id=player['id'])
        self.assertIn('already has 13',self.engine.opponent_choices(state)['blocked'])
        store.db.close()


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Application(':memory:')
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.app))
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        cls.app.pool.shutdown(wait=True); cls.app.close()

    def test_local_api_and_token(self):
        with urllib.request.urlopen(self.url+'/api/state') as r:
            state = json.load(r)
        self.assertEqual(len(state['players']),430)
        body = json.dumps({'kind':'settings','payload':{'risk':.5},'revision':state['state']['revision'],'session_id':state['session']['id']}).encode()
        request = urllib.request.Request(self.url+'/api/event',data=body,headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(request)
        self.assertEqual(cm.exception.code,403)
        request.add_header('X-Draft-Token',state['token'])
        with urllib.request.urlopen(request) as r:
            saved = json.load(r)
        self.assertEqual(saved['state']['revision'],1)

    def test_host_rebinding_and_static(self):
        request = urllib.request.Request(self.url+'/api/state',headers={'Host':'evil.example'})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(request)
        self.assertEqual(cm.exception.code,403)
        with urllib.request.urlopen(self.url+'/') as r:
            self.assertIn(b'Draft Lab',r.read())
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.url+'/../league_config.json')

    def test_mock_api_safety_and_stale_window(self):
        with urllib.request.urlopen(self.url+'/api/state') as r:
            payload=json.load(r)
        def post(path,body):
            request=urllib.request.Request(self.url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Draft-Token':payload['token']})
            with urllib.request.urlopen(request) as r:
                return json.load(r)
        before=copy.deepcopy(self.app.store.state())
        with self.assertRaises(urllib.error.HTTPError):
            post('/api/mock/advance',{'session_id':'live','revision':before['revision']})
        with self.assertRaises(urllib.error.HTTPError):
            post('/api/session',{'session_id':'live','action':'reset_mock'})
        mock=post('/api/session',{'session_id':'live','action':'new_mock'})
        sid=mock['session']['id']
        with self.assertRaises(urllib.error.HTTPError):
            post('/api/event',{'session_id':'live','kind':'pick','payload':{'slot':1,'player_id':'ht:9196'},'revision':before['revision']})
        advanced=post('/api/mock/advance',{'session_id':sid,'revision':mock['state']['revision'],'until_me':True})
        self.assertEqual(len(advanced['simulated']),5)
        self.assertEqual(advanced['state']['current_slot'],6)
        self.assertIn('Your turn',advanced['blocked'])
        live=post('/api/session',{'session_id':sid,'action':'switch','target_id':'live'})
        self.assertEqual(live['state'],before)

    def test_benchmark_and_completion_guardrails(self):
        with urllib.request.urlopen(self.url+'/api/state') as r:
            payload=json.load(r)
        def post(path,body):
            request=urllib.request.Request(self.url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Draft-Token':payload['token']})
            with urllib.request.urlopen(request) as r:
                return json.load(r)
        def bad(path,body):
            request=urllib.request.Request(self.url+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Draft-Token':payload['token']})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(request)
            return json.loads(cm.exception.read())
        with urllib.request.urlopen(self.url+'/api/benchmark-config') as r:
            config=json.load(r)
        self.assertEqual(config['regular_weeks'],17)
        self.assertTrue(config['schedule_dates_verified'])
        # Live mode never auto-completes a draft (checked while live is active).
        self.assertIn('practice',bad('/api/mock/complete',{'session_id':'live','revision':payload['state']['revision']})['error'])
        mock=post('/api/session',{'session_id':'live','action':'new_mock'})
        sid=mock['session']['id']
        # Board is fully resolved under confirmed ownership; fail-closed on missing
        # assets is covered by unit tests (uncertainty_barrier). Here we assert config
        # guardrails still reject an invalid benchmark request.
        invalid=bad('/api/benchmarks',{'session_id':sid,'revision':mock['state']['revision'],
            'config':{'drafts':0}})
        self.assertIn('drafts',invalid['error'])
        # Global assets are unchanged by any refused request.
        with urllib.request.urlopen(self.url+'/api/state') as r:
            self.assertEqual(json.load(r)['state']['drafted'],[])
        # Preserve the shared class state for later tests in this class.
        post('/api/session',{'session_id':sid,'action':'switch','target_id':payload['session']['id']})

    def test_analysis_failure_is_explicit_and_never_reused(self):
        # The payload must distinguish "unavailable" from a retained previous analysis.
        from unittest.mock import patch
        good = self.app.payload()
        self.assertIsNotNone(good['analysis'])
        self.assertIsNone(good['analysis_error'])
        with patch.object(self.app.engine,'team_analysis',side_effect=RuntimeError('boom')):
            failed = self.app.payload()
        self.assertIsNone(failed['analysis'])
        self.assertEqual(failed['analysis_error'],'boom')
        # Recovery clears the error again.
        self.assertIsNone(self.app.payload()['analysis_error'])


if __name__ == '__main__':
    unittest.main()
