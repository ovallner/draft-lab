"""Frozen full-policy audit scientific worker. No writable app sessions are opened."""
import argparse
import copy
import hashlib
import json
import math
import os
import random
import statistics as stat
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import Data, CATEGORIES
from app.engine import Engine, matchup
from app.market import market_key
from app.season_draft import SeasonDraft
from app.season_inputs import SeasonInputs
from app.season_world import SeasonWorld
from app.season_sim import SeasonSimulator
from app.store import Store
from app.draft_model import uncertainty_barrier

POLICIES = ('production', 'adp', 'fit', 'playbook')
PICKS = [6,43,54,67,78,91,102,115,126,150]
LIVE = {'name':'Audit policy','policy':'live','punts':[],'streaming':'aggressive'}
FIT = {'name':'ADP + fit','policy':'fit','punts':[],'streaming':'aggressive','playoff_weight':0.,'risk':.5}
NAMESPACE = 'complete-policy-audit-20261013-v1-never-first-three-or-heldout'


def atomic(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w') as f:
        json.dump(value,f,ensure_ascii=False,indent=1,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def hashed(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True).encode()).hexdigest()


def seed(*parts):
    return int.from_bytes(hashlib.sha256(json.dumps([NAMESPACE,*parts]).encode()).digest()[:16],'big')


def featured(recs):
    realistic=[r for r in recs if r.get('availability_at_next') is None or r['availability_at_next']>=.5]
    return (realistic or recs)[:3]


def setup():
    data=Data();engine=Engine(data);inputs=SeasonInputs(data);store=Store(':memory:',data)
    config,states=inputs.prepare(store.state(),{'strategies':[dict(LIVE)],'opponent_modes':['adp_stochastic','validated'],
        'seasons_per_draft':3,'start_mode':'keepers','seed_block':'production_lab','holdout':1})
    base=states[0];base['settings'].pop('draft_scenarios',None)
    base['settings']['punt']=[];base['simulation_config']={'model':'fit','randomness':.35}
    store.db.close()
    assert uncertainty_barrier(base,data) is None
    assert [s['slot'] for s in base['slots'] if s['current_team']=='Oscar' and not s['keeper']]==PICKS
    assert {p['name'] for p in engine.rosters(base)['Oscar']}=={'Shai Gilgeous-Alexander','Donovan Mitchell','Kyshawn George'}
    return data,engine,inputs,config,base


def fit_scores(engine, roster, pool):
    ordered=sorted(pool,key=market_key);sums=[sum(engine.z[p['id']][j] for p in roster) for j in range(9)]
    weights=[max(.25,math.exp(-.08*max(-3,min(6,x)))) for x in sums]
    window=ordered[:10 if len(roster)<7 else 16]
    scores={}
    for i,p in enumerate(window):
        health=1-.5*(1-p['gp']/82)
        category=sum(w*z for w,z in zip(weights,engine.z[p['id']]))/sum(weights)
        scores[p['id']]=(category+2)*health-2+engine.need_bonus(roster,p)-.025*math.log1p(i)
    return scores


def playbook_choice(book, slot, first, taken43, legal):
    if slot==6:
        names={p['name']:pid for pid,p in book['players'].items()}
        chain=[book['provisional_first']]+[names[n] for n in ['Evan Mobley','Alperen Sengün','Lauri Markkanen','Tyrese Maxey','Scottie Barnes','Kevin Durant','Bam Adebayo']]
    else:
        branch=book['branches'].get(first)
        if not branch:return None
        p=branch['policy']
        chain=(p['rank43'] if slot==43 else p['rank54'].get(taken43,p['default54']))+p['fallback']
    return next((pid for pid in chain if pid in legal),None)


class Paused(Exception):pass


class AuditDraft(SeasonDraft):
    def __init__(self, engine, task, book, cp, save, halt):
        super().__init__(engine);self.task=task;self.book=book;self.cp=cp;self.save=save;self.halt=halt

    def model_pick(self,pool,roster,team,round_number,policy,settings,uniform,drawn,draft_seed):
        model=self.task['model']
        # Slots store the round as text; the shared baseline coerces internally.
        # Coerce once here so robustness branches compare numerically.
        round_number=int(round_number)
        if model in ('adp_stochastic','validated'):
            return super().model_pick(pool,roster,team,round_number,model,settings,uniform,drawn,draft_seed)
        ordered=sorted(pool,key=market_key)
        if model in ('center_run','guard_run') and 4<=round_number<=7:
            positions={'C'} if model=='center_run' else {'PG','SG'}
            forced=next((p for p in ordered[:24] if positions & set(p['positions'])),None)
            if forced:return forced
        if model in ('center_run','guard_run'):
            return super().model_pick(pool,roster,team,round_number,'validated',settings,uniform,drawn,draft_seed)
        if model=='market_tight':
            window=ordered[:8];weights=[(i+1)**-3.5 for i in range(len(window))]
        elif model=='need_pressure':
            window=ordered[:24]
            sums=[sum(self.engine.z[p['id']][j] for p in roster) for j in range(9)]
            needs=sorted(range(9),key=lambda j:sums[j])[:3]
            style=seed('manager-style',team)%3
            cats=([0,4,7],[1,2,3],[3,5,6])[style]
            weights=[]
            for i,p in enumerate(window):
                z=self.engine.z[p['id']]
                tilt=.30*sum(max(-2,min(2,z[j])) for j in needs)+.8*self.engine.need_bonus(roster,p)+.25*sum(max(-2,min(2,z[j])) for j in cats)
                weights.append((i+1)**-1.1*math.exp(max(-3,min(3,tilt))))
        else:raise ValueError('Unknown audit opponent model: '+model)
        target=uniform*sum(weights);total=0
        for p,w in zip(window,weights):
            total+=w
            if target<=total:return p
        return window[-1]

    def pick_live(self,state):
        if self.halt():raise Paused()
        number=state['current_slot'];state=copy.deepcopy(state)
        state['revision']=len(state['drafted']);sid=f"audit:{self.task['stage']}:{self.task['index']}:{self.task['model']}:{self.task['policy']}"
        pool=sorted([p for p in self.data.players.values() if not p['keeper'] and p['id'] not in state['drafted']],key=market_key)
        roster=self.engine.rosters(state)['Oscar'];legal={p['id'] for p in pool}
        policy=self.task['policy'];rec=None;scores={};t0=time.perf_counter();reason=policy
        first=state['slots'][5]['player_id'];taken43=state['slots'][42]['player_id']
        if policy=='production' or policy=='playbook' and number>54:
            rec=self.engine.recommend(state)
            if not rec.get('recommendations'):raise ValueError(f'Material correctness failure: no production recommendations at #{number}')
            row=featured(rec['recommendations'])[0];selected=row['player'];punts=list(row.get('punt') or [])
        elif policy=='adp':selected=pool[0];punts=[]
        elif policy=='fit':
            scores=fit_scores(self.engine,roster,pool)
            selected=self.pick(pool,roster,FIT);punts=[]
            if selected['id']!=max(scores,key=scores.get):raise ValueError('Fit adapter differs from shared baseline')
        elif policy=='playbook':
            pid=playbook_choice(self.book,number,first,taken43,legal)
            if pid is None:pid=pool[0]['id'];reason='playbook outside-coverage ADP fallback'
            selected=self.data.players[pid];punts=[]
        else:raise ValueError('Unknown policy')
        seconds=time.perf_counter()-t0
        if selected['id'] not in legal:raise ValueError('Material correctness failure: selected player unavailable or keeper')
        recs=(rec or {}).get('recommendations',[])
        if any(r['player']['id'] not in legal for r in recs):raise ValueError('Material correctness failure: illegal recommendation row')
        next_pick=next((p for p in PICKS if p>number),None)
        row=next((r for r in recs if r['player']['id']==selected['id']),{})
        before=[p['id'] for p in roster]
        decision={'slot':number,'session_id':sid,'revision':state['revision'],'board_hash':hashed(state),
            'board':state,'available':[p['id'] for p in pool],'selected':selected['id'],'reason':reason,
            'roster_before':before,'roster_after':before+[selected['id']],
            'seconds':seconds,'recommended':bool(rec),'backend_first':recs[0]['player']['id'] if recs else None,
            'featured_ids':[r['player']['id'] for r in featured(recs)],'evaluated_punts':punts,
            'market_rank_remaining':next(i+1 for i,p in enumerate(pool) if p['id']==selected['id']),
            'market_adp':selected['market_adp'],'adp_estimated':selected.get('adp_estimated'),
            'next_pick':next_pick,'survival_if_passed_estimate':row.get('availability_later'),
            'wait_comparison':row.get('wait_comparison'),
            'fit':self.engine.position_fit(roster,selected,(),.5),
            'alternatives': [{'id':r['player']['id'],'score':r['score'],'punt':r.get('punt'),
                'availability_at_next':r.get('availability_at_next'),'availability_later':r.get('availability_later'),
                'fit':r.get('fit')} for r in recs] if rec else
                [{'id':p['id'],'score':scores.get(p['id']),'market_adp':p['market_adp']} for p in pool[:16]]}
        # Persist the entire legal partial board after this selection, including all
        # preceding opponent picks. Replayed opponent parameters are keyed by seed.
        after=copy.deepcopy(state);s=after['slots'][number-1]
        s.update(player_id=selected['id'],player_name=selected['name']);after['drafted'].append(selected['id'])
        after['current_slot']=next((s['slot'] for s in after['slots'] if not s['keeper'] and not s['player_id']),None)
        after['revision']+=1
        self.cp['decisions'].append(decision);self.cp['state']=after;self.save()
        return selected,punts


def diagnostics(engine,state,draft):
    analysis=engine.team_analysis(state,{**state['settings'],'punt':[]})
    edges={c:stat.mean(m['weeks'][w]['category_edges'][j] for m in analysis['matchups'] for w in range(3)) for j,c in enumerate(CATEGORIES)}
    routes=[sum(e>=.5 for e in w['category_edges'])>=5 for m in analysis['matchups'] for w in m['weeks']]
    roster=[engine.data.players[p] for p in draft['rosters']['Oscar']]
    ids=tuple(sorted(p['id'] for p in roster))
    riskweeks=engine.weekly_totals(ids,(),1.)
    scales=[max(.012 if j<2 else 1,stat.pstdev(analysis['teams'][t]['weeks'][w]['categories'][j] for t in analysis['teams'] for w in range(3))*.65) for j in range(9)]
    riskroutes=[]
    for m in analysis['matchups']:
        for w in range(3):
            _,e=matchup(riskweeks[w]['categories'],m['weeks'][w]['opp_categories'],scales)
            riskroutes.append(sum(x>=.5 for x in e)>=5)
    return {'category_edges':edges,'fifth_category_edge':sorted(edges.values(),reverse=True)[4],
        'five_category_route_fraction':stat.mean(routes),'risk1_route_fraction':stat.mean(riskroutes),
        'usable_starts':sum(w['usable_starts'] for w in analysis['own']['weeks']),
        'blocked_games':sum(w['blocked_games'] for w in analysis['own']['weeks']),
        'risk1_usable_starts':sum(w['usable_starts'] for w in riskweeks),
        'low_gp_players':[p['id'] for p in roster if p['gp']<65],
        'c_only':[p['id'] for p in roster if p['positions']==['C']],
        'multi_position_bigs':[p['id'] for p in roster if 'C' in p['positions'] and len(p['positions'])>1],
        'analysis':analysis,
        'note':'Projected neutral-category diagnostics, not simulated outcomes. 35/65% labels and route-fraction thresholds are descriptive heuristics. risk=1 is a stronger GP discount, not a new projection or calibrated injury scenario.'}


def execute(task,run,stop_after=None):
    data,engine,inputs,config,base=setup()
    lane=run/task['lane'];dest=lane/'tasks'/(task['id']+'.json');checkpoint=dest.with_suffix('.checkpoint.json')
    if dest.exists():return json.loads(dest.read_text())
    if checkpoint.exists():cp=json.loads(checkpoint.read_text())
    else:cp={'task':task,'task_hash':hashed(task),'state':base,'decisions':[],'outcomes':[],'active_seconds':0.}
    if cp['task_hash']!=hashed(task):raise ValueError('Checkpoint task definition changed')
    begin=time.monotonic();old_seconds=cp['active_seconds'];initial_boundaries=len(cp['decisions'])+len(cp['outcomes'])
    book=json.loads((data.root/'FIRST_THREE_PICKS_PLAYBOOK.json').read_text())
    def save():
        cp['active_seconds']=old_seconds+time.monotonic()-begin;atomic(checkpoint,cp)
    def halt():
        limit=stop_after is not None and len(cp['decisions'])+len(cp['outcomes'])-initial_boundaries>=stop_after
        return (lane/'STOP').exists() or limit
    try:
        if 'draft' not in cp:
            drafter=AuditDraft(engine,task,book,cp,save,halt)
            result=drafter.complete(copy.deepcopy(cp['state']),dict(LIVE),task['model'],seed('draft',task['lane'],task['stage'],task['index']))
            state=copy.deepcopy(cp['state'])
            for t in result['trace']:
                state['slots'][t['slot']-1].update(player_id=t['player_id'],player_name=t['name'])
            state['drafted']=[s['player_id'] for s in state['slots'] if s['player_id']];state['current_slot']=None
            result['trace']=[{'slot':s['slot'],'team':s['current_team'],'player_id':s['player_id'],'name':s['player_name']} for s in state['slots'] if not s['keeper']]
            # Identical season management across all drafting policies; temporary
            # candidate punt labels do not leak into different streaming policies.
            result['punts']={t:[] for t in data.teams};result['own_strategy']=dict(LIVE)
            cp['draft']=result;cp['state']=state;cp['diagnostics']=diagnostics(engine,state,result);save()
        for i in range(len(cp['outcomes']),task['seasons']):
            if halt():raise Paused()
            world_seed=seed('world',task['lane'],task['stage'],task['index'],i)
            world=SeasonWorld(data,inputs,config['calendar'],world_seed,config)
            out=SeasonSimulator(engine,inputs).run(cp['draft'],world,config)
            team=out['teams']['Oscar']
            cp['outcomes'].append({'seed':world_seed,'title':int(bool(team['champion'])),
                'qualified':int(bool(team['qualified'])),
                'advancement':sum(int(bool(team[k])) for k in ('qualified','semifinal','final','champion')),
                'team_outcomes':out['teams']});save()
        cp['status']='complete';save();atomic(dest,cp)
        return cp
    except Paused:
        save();return None


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--task',type=Path,required=True);parser.add_argument('--stop-after',type=int)
    args=parser.parse_args()
    try:
        result=execute(json.loads(args.task.read_text()),args.run,args.stop_after)
        sys.exit(0 if result is not None else 75)
    except Exception:
        import traceback
        error=traceback.format_exc();print(error,file=sys.stderr)
        atomic(args.task.with_suffix('.failure.json'),{'error':error,'at':time.time()})
        sys.exit(1)
