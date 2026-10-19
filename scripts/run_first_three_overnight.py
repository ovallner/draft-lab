#!/usr/bin/env python3
"""Deadline-driven, resumable overnight conditional-policy search.

Run only from the frozen experiment source, never against writable saved sessions.
Each finished task checkpoints immediately. SIGTERM/SIGINT preserve completed work.
"""
import argparse
import copy
import fcntl
import hashlib
import itertools
import json
import math
import os
import platform
import signal
import statistics as st
import sys
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path

from overnight_core import (atomic, available, context, digest, execute_task, prefix,
                            seed, MAIN, EXTRA, MODELS, LIVE, NS)
from overnight_report import publish, summarize

STOP = False


def interrupt(signum, frame):
    global STOP
    STOP = True


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Runner:
    def __init__(self, run, hours=None):
        self.run = run; self.cfg = json.loads((run/'run.json').read_text())
        self.start = self.cfg['started_epoch']
        if hours is not None:
            self.start = time.time(); self.cfg['resumed_epoch'] = self.start
            self.cfg['budget_seconds'] = hours*3600
            atomic(run/'run.json', self.cfg)
        self.deadline = self.start+self.cfg['budget_seconds']
        self.workers = self.cfg['workers']; self.elapsed_tasks = []
        self.data, self.engine, self.inputs, self.config, self.base = context()
        self.by_name = {p['name']: p for p in self.data.players.values()}
        self.executor = None
        self.errors = []

    def log(self, message, **extra):
        row = {'at': stamp(), 'elapsed_seconds': round(time.time()-self.start, 1), 'message': message, **extra}
        with (self.run/'progress.log').open('a') as f:
            f.write(json.dumps(row, ensure_ascii=False)+'\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def status(self, stage, **extra):
        atomic(self.run/'progress.json', {'stage': stage, 'at': stamp(), 'started_epoch': self.start,
                                         'deadline_epoch': self.deadline, 'elapsed_seconds': time.time()-self.start,
                                         'completed_tasks': sum(not p.name.endswith(('.checkpoint.json','.error.json')) for p in (self.run/'results').glob('*.json')),
                                         'errors': self.errors, **extra})

    def verify(self):
        source = Path(self.cfg['source'])
        # Full copied app/data/scripts are hash-locked, including imported history.
        files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                 and p.suffix not in ('.pyc','.DS_Store') and 'local' not in p.relative_to(source).parts]
        hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
        path = self.run/'manifest.json'
        if path.exists():
            old = json.loads(path.read_text())
            if hashes != old['hashes']:
                changed = [p for p in set(hashes)|set(old['hashes']) if hashes.get(p)!=old['hashes'].get(p)]
                raise ValueError('Frozen source changed; refusing mixed-code resume: '+', '.join(changed))
            return
        atomic(path, {'format': 'first-three-experiment-v1', 'created_at': stamp(), 'hashes': hashes,
                      'projection_source': self.cfg['projection_source'], 'projection_sha256': self.cfg['projection_sha256'],
                      'keepers': self.data.keepers, 'slots': self.base['slots'], 'roster_positions': self.data.config['roster_positions'],
                      'config': self.config, 'source_state': self.base,
                      'seed_namespace': NS,
                      'seed_derivation': 'SHA256(JSON([namespace, draft|world, phase, index, optional season])) first 128 bits. Model/candidate/policy excluded for common randomness. Confirmation has disjoint phase and new completions.',
                      'runtime': {'python': sys.version, 'platform': platform.platform(), 'workers': self.workers,
                                  'wall_seconds': self.cfg['budget_seconds'], 'start_epoch': self.start, 'deadline_epoch': self.deadline},
                      'pre_registered_equivalence_margin': .05,
                      'assumptions': ['Same-round duplicate keeper costs allowed (unverified rule).',
                                      'Yahoo positions provisional from Hashtag; 1 C + 3 UTIL, no arbitrary center cap.',
                                      'Primary ADP-stochastic; validated is baseline plus small prospective fit effects, persona disabled.',
                                      'No saved-session database opened. Start from verified source keeper/ownership board.',
                                      'Latest supplied Oct12 projection snapshot internally validated, not independently updated against injury news.'],
                      'targeted_checks': '31 season, guard and seed tests passed in frozen source before pilot; new workflow tests recorded separately.'})

    def estimate(self, discovery=False):
        if self.elapsed_tasks:
            costs = [s for s, kind in self.elapsed_tasks[-100:] if kind == discovery]
            if costs:
                return max(10, st.median(costs))
        p = json.loads((self.run/'pilot_timing.json').read_text())
        # Initial conservative contention allowance; replaced by measured worker wall time.
        return max(20, p['seconds']*(.5 if discovery else 1.8))

    def run_tasks(self, tasks, deadline, stage):
        tasks = list(tasks); pending = {}; results = []; i = 0
        if self.executor is None:
            self.executor = ProcessPoolExecutor(max_workers=self.workers)
        self.status(stage, scheduled=len(tasks)); self.log('stage_started', stage=stage, scheduled=len(tasks))
        while (i < len(tasks) or pending) and not STOP:
            while i < len(tasks) and len(pending) < self.workers:
                task = tasks[i]; path = Path(task['out'])
                if path.exists():
                    results.append(json.loads(path.read_text())); i += 1; continue
                if time.time()+self.estimate(task.get('discover', False))*1.15+30 > deadline:
                    i = len(tasks); break
                fut = self.executor.submit(execute_task, task); pending[fut] = task; i += 1
            if not pending:
                break
            done, _ = wait(pending, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                self.status(stage, active=len(pending), remaining_in_stage=len(tasks)-i)
            for fut in done:
                task = pending.pop(fut)
                try:
                    result = fut.result(); results.append(result)
                    if result['state'] == 'complete':
                        self.elapsed_tasks.append((result['seconds'], task.get('discover', False)))
                    self.log('task_finished', phase=task['phase'], index=task['index'], first=task['first'],
                             model=task['model'], policy=(task.get('policy') or {}).get('id'),
                             state=result['state'], seconds=round(result['seconds'],1))
                except Exception as exc:
                    err = {'task': task, 'error': str(exc), 'traceback': traceback.format_exc()}
                    self.errors.append(err); atomic(Path(task['out']).with_suffix('.error.json'), err)
                    self.log('task_failed', error=str(exc), output=task['out'])
                    # A broken contract must not burn the whole budget or masquerade as missing availability.
                    if len(self.errors) >= 3:
                        raise RuntimeError('Three task failures; stopping for diagnosis') from exc
            self.status(stage, active=len(pending), remaining_in_stage=max(0,len(tasks)-i))
        if STOP:
            for fut in pending:
                fut.cancel()
        return results

    def task(self, phase, index, first, model, policy=None, **extra):
        name = f'{phase}_{index:04d}_{first.replace(":","-")}_{model}_{(policy or {}).get("id","discover")}'
        if extra.get('stress'):
            name += '_'+extra['stress']
        return {'phase': phase, 'index': index, 'first': first, 'model': model, 'policy': policy,
                'seasons': 3, 'out': str(self.run/'results'/(name+'.json')), **extra}

    def first_screen(self):
        path = self.run/'first_screen.json'
        if path.exists():
            return json.loads(path.read_text())
        self.log('broad_first_pick_screen_started')
        data = self.data; engine = self.engine
        availability = {}; samples = {}
        for model in MODELS:
            counts = Counter()
            for i in range(256):
                state = prefix(model, i, 'availability')
                counts.update(p['id'] for p in available(state, data))
                if i < 3:
                    samples[(model,i)] = state
            availability[model] = dict(counts)
        # Production output across multiple observed first-five constructions.
        engine_rows = []
        for model,i in [('adp_stochastic',0), ('adp_stochastic',1), ('validated',0)]:
            t0 = time.time(); rec = engine.recommend(samples[(model,i)])
            rows = [{'id': r['player']['id'], 'name': r['player']['name'], 'rank': j+1,
                     'score': r['score'], 'adp': r['player']['market_adp'], 'fit': r['fit'],
                     'evaluated_punts': r['punt']} for j,r in enumerate(rec['recommendations'])]
            engine_rows.append({'model': model, 'index': i, 'rows': rows})
            self.log('first_pick_production_screen', model=model, index=i, seconds=time.time()-t0,
                     leaders=[r['name'] for r in rows[:10]])
        from app.market import market_key
        market = sorted([p for p in data.players.values() if not p['keeper']], key=market_key)
        elite = {p['id'] for p in market[:5]}
        candidates = [self.by_name[n]['id'] for n in MAIN+EXTRA]
        emergent = []
        for row in engine_rows[0]['rows']:
            pid = row['id']
            if pid not in candidates and pid not in elite and availability['adp_stochastic'].get(pid,0) >= 128:
                candidates.append(pid); emergent.append(pid); break
        all_ids = list(dict.fromkeys([r['id'] for block in engine_rows for r in block['rows'][:15]]+[p['id'] for p in market[:30]]+candidates))
        records = []
        for pid in all_ids:
            p = data.players[pid]
            records.append({'id':pid, 'name':p['name'], 'market_adp':p['market_adp'], 'value':engine.value(p),
                            'positions':p['positions'], 'eligible':not bool(p['keeper']),
                            'availability_at6':{m:{'available':availability[m].get(pid,0),'paths':256} for m in MODELS},
                            'treatment':'elite_contingency' if pid in elite else 'joint_screen' if pid in candidates else 'screened_not_deep',
                            'reason':'mandatory main branch' if p['name'] in MAIN else 'credible market/fit direction, not excluded by old championship samples' if p['name'] in EXTRA else 'unexpected production-engine leader' if pid in emergent else 'coverage bounded by current engine/market shortlist; no claim of inferiority'})
        result = {'candidates':candidates, 'records':records, 'production_screens':engine_rows,
                  'contingencies':[r for r in records if r['id'] in elite],
                  'note':'Availability is a model-conditioned count from naturally sampled first five picks, not calibrated real frequency. Elite branches are separate, not given equal compute.'}
        atomic(path,result); return result

    def compile_policies(self, first, discovery):
        data=self.data; engine=self.engine
        relevant = [r for r in discovery if r['task']['first']==first and r['task']['model']=='adp_stochastic' and r['state']=='complete']
        if not relevant:
            relevant = [r for r in discovery if r['task']['first']==first and r['state']=='complete']
        if not relevant:
            return None
        by_slot = defaultdict(list); conditional = defaultdict(list)
        for r in relevant:
            ds=r.get('discoveries',r.get('decisions',[]))
            for d in ds:
                by_slot[d['slot']].append(d)
            if len(ds)==2:
                conditional[ds[0]['selected']].append(ds[1])
        def order(ds):
            scores=defaultdict(list)
            for d in ds:
                for r in d['candidates']:
                    # Production ranks drive the default. Added category/value options
                    # remain in the union for explicit alternative-direction policies.
                    scores[r['id']].append(1/(r['engine_rank'] or 25))
            return sorted(scores,key=lambda p:(st.mean(scores[p]),engine.value(data.players[p])),reverse=True)
        rank43=order(by_slot[43]); rank54=order(by_slot[54])
        keeper=engine.rosters(self.base)['Oscar']; early=keeper+[data.players[first]]
        legal=[p for p in data.players.values() if not p['keeper'] and p['id']!=first]
        fallback=[p['id'] for p in sorted(legal,key=lambda p:engine.value(p,(),.5)+engine.need_bonus(early,p),reverse=True)]
        # #54 lookups are precomputed for every ranked #43 target, using discoveries
        # where observed and transparent projection/position fit elsewhere.
        r54={}
        for pid in rank43:
            if conditional[pid]:
                ids=order(conditional[pid])
            else:
                roster=early+[data.players[pid]]
                ids=sorted(rank54,key=lambda p:engine.value(data.players[p],(),.5)+engine.need_bonus(roster,data.players[p]),reverse=True)
            r54[pid]=[p for p in dict.fromkeys(ids+rank54) if p!=pid]
        simple={'id':'simple','rank43':rank43,'rank54':{},'default54':rank54,'fallback':fallback,
                'description':'Simple fixed availability list learned from production ranks; no opponent-roster conditions.'}
        cond={'id':'conditional','rank43':rank43,'rank54':r54,'default54':rank54,'fallback':fallback,
              'description':'#54 ranking depends only on actual #43 selection and current availability.'}
        # Explicit take-now versus wait policy: take second/third option at #43;
        # target former first choice at #54 only if opponents leave him available.
        target=rank43[0]
        wait43=rank43[1:3]+[target]+rank43[3:]
        wait54={p:list(dict.fromkeys(([target] if p!=target else [])+r54[p])) for p in r54}
        waitp={'id':'wait','rank43':wait43,'rank54':wait54,'default54':[target]+[p for p in rank54 if p!=target],
               'fallback':fallback,'wait_target':target,'description':'Pass on leading #43 target when second/third option exists; attempt him at #54 without protection.'}
        # A deliberately different viable direction, bounded to the discovered union.
        cats=[1,2,5] if 'C' in data.players[first]['positions'] else [0,4,7]
        direction43=sorted(rank43,key=lambda p:sum(engine.z[p][j] for j in cats)+.5*engine.value(data.players[p]),reverse=True)
        direction={'id':'direction','rank43':direction43,'rank54':r54,'default54':rank54,'fallback':fallback,
                   'description':'Different category route from the same candidate union; no fixed punt.', 'category_indices':cats}
        oracle={'id':'production','oracle':True,'description':'Full-board unpruned production choices at #43/#54; diagnostic comparator, not a precomputed rule.'}
        return [simple,cond,waitp,direction,oracle]

    def collect(self, phase=None):
        out=[]
        for p in (self.run/'results').glob('*.json'):
            if p.name.endswith(('.checkpoint.json','.error.json')):
                continue
            r=json.loads(p.read_text())
            if r.get('state')=='complete' and 'outcomes' in r and (phase is None or r['task']['phase']==phase):
                out.append(r)
        return out

    def select(self, policies, final=False, retained=None):
        rows=[r for r in self.collect() if r['task']['phase'] in ('screen','deep') and r['task']['model']=='adp_stochastic']
        by={}
        for first, ps in policies.items():
            scores={}
            for p in ps:
                if p.get('oracle'):continue
                rr=[r for r in rows if r['task']['first']==first and r['task']['policy']['id']==p['id']]
                if rr:
                    scores[p['id']]=summarize(rr)
            ranked=sorted(scores,key=lambda k:(scores[k]['championship_frequency'],scores[k]['qualification_frequency'],scores[k]['advancement']),reverse=True)
            by[first]={'chosen':ranked[0] if ranked else 'conditional',
                       'runners_up':ranked[1:], 'screening_evidence':scores,
                       'reason':'New exploratory championship frequency leads, qualification/advancement break exact observed ties. Selection-biased; not a superiority claim.'}
        mains=[self.by_name[n]['id'] for n in MAIN]
        if retained is None:
            extras=[pid for pid in by if pid not in mains]
            # Retain one alternative direction by new evidence plus production/fit;
            # all credible candidates received joint screening before this narrowing.
            def score(pid):
                stats=by[pid]['screening_evidence'].get(by[pid]['chosen'],{})
                return (stats.get('championship_frequency',-1),stats.get('qualification_frequency',-1),self.engine.value(self.data.players[pid]))
            extra=max(extras,key=score) if extras else None
            retained=[p for p in mains+([extra] if extra else []) if p in by]
        return {'frozen_at':stamp(),'frozen_before_confirmation':final,
                'selection_model':'adp_stochastic only; validated never averaged into ranking',
                'branches':{p:by[p] for p in retained},
                'all_screened':by,
                'policy_hash':digest(policies),
                'tie_margin':.05,
                'note':'At least KAT/Mobley/Sengun retained regardless of earlier samples. Additional branch chosen from this experiment after broad screening. No confirmation results used for selection.'}

    def allocation(self, selected, deadline, phase):
        remaining=max(0,deadline-time.time()-120)
        cost=self.estimate(False)
        units=sum(2 if v['chosen']!='simple' else 1 for v in selected['branches'].values())*len(MODELS)
        # Include full-board oracle on every fourth source path. Diversity first;
        # keep modest seasons and cap source paths only to bound disk/report size.
        per_index=units+len(selected['branches'])*len(MODELS)/4
        n=max(1,min(160,int(remaining*self.workers/(cost*per_index*1.2))))
        return {'phase':phase,'workers':self.workers,'measured_median_worker_seconds':cost,
                'available_wall_seconds':remaining,'planned_source_indices':n,
                'jobs_per_index_mean':per_index,'seasons_per_path':3,
                'target_paths_per_model':20,'note':'Effort target only. Candidate already gone at #6 is skipped; actual counts can be lower. Reserved confirmation uses new source indices and worlds.'}

    def evaluate_selected(self, selected, policies, phase, deadline):
        allocation=self.allocation(selected,deadline,phase)
        path=self.run/'allocation.json'
        all_alloc=json.loads(path.read_text()) if path.exists() else {}
        all_alloc[phase]=allocation; atomic(path,all_alloc)
        self.log('measured_allocation',**allocation)
        tasks=[]
        for i in range(allocation['planned_source_indices']):
            for first,v in selected['branches'].items():
                ids=list(dict.fromkeys([v['chosen'],'simple']+(['production'] if i%4==0 else [])))
                for model in MODELS:
                    for pid in ids:
                        p=next(p for p in policies[first] if p['id']==pid)
                        tasks.append(self.task(phase,i,first,model,p))
        # Fill spare budget with more independent paths (never more worlds on old
        # rosters); allocation is re-measured at checkpoint if initial plan finishes.
        self.run_tasks(tasks,deadline,phase)
        publish(self.run,'Running — '+phase+' checkpoint',selected)
        return allocation

    def run_all(self):
        self.verify(); self.run.joinpath('results').mkdir(exist_ok=True)
        self.log('overnight_started',deadline_epoch=self.deadline,workers=self.workers)
        budget=self.cfg['budget_seconds']
        confirm_start=self.start+.75*budget
        confirm_end=self.deadline-720
        publish(self.run,'Running — broad screening')
        screen=self.first_screen()
        candidates=screen['candidates']
        tasks=[self.task('discover',i,p,m,discover=True,explore_rank=i%4,seasons=0)
               for i in range(4) for p in candidates for m in MODELS]
        discovery=self.run_tasks(tasks,min(self.start+.24*budget,confirm_start-900),'candidate_pool_discovery')
        # Include all saved discovery records on resume.
        discovery=[]
        for t in tasks:
            if Path(t['out']).exists():discovery.append(json.loads(Path(t['out']).read_text()))
        policy_path=self.run/'policies.json'
        if policy_path.exists():
            policies=json.loads(policy_path.read_text())
        else:
            policies={}
            for first in candidates:
                ps=self.compile_policies(first,discovery)
                if ps:policies[first]=ps
            if not all(self.by_name[n]['id'] in policies for n in MAIN):
                raise ValueError('Missing main branch discovery; preserve partial results and inspect')
            atomic(policy_path,policies)
        publish(self.run,'Running — compiled exploratory rules')
        screen_tasks=[self.task('screen',i,p,m,policy)
                      for i in range(3) for p in policies for m in MODELS for policy in policies[p]]
        self.run_tasks(screen_tasks,min(self.start+.49*budget,confirm_start-600),'joint_policy_screen')
        deep_path=self.run/'deep_shortlist.json'
        if deep_path.exists():selected=json.loads(deep_path.read_text())
        else:
            selected=self.select(policies);atomic(deep_path,selected)
        publish(self.run,'Running — deeper shortlist',selected)
        if not (self.run/'frozen_finalists.json').exists():
            self.evaluate_selected(selected,policies,'deep',confirm_start-120)
            selected=self.select(policies,final=True,retained=list(selected['branches']))
            atomic(self.run/'frozen_finalists.json',selected)
            self.log('rules_frozen_before_confirmation',policy_hash=selected['policy_hash'],branches=selected['branches'])
        else:selected=json.loads((self.run/'frozen_finalists.json').read_text())
        # No artificial waiting: unused screening time flows into fresh confirmation.
        self.evaluate_selected(selected,policies,'confirm',confirm_end)
        stress=[]
        for first,v in selected['branches'].items():
            policy=next(p for p in policies[first] if p['id']==v['chosen'])
            for model in MODELS:
                # Stress cases are explicitly conditional constructions, not an
                # estimate of natural availability. Pick a legal supporting prefix.
                index=next(i for i in range(100) if first in {p['id'] for p in available(prefix(model,i,'stress'),self.data)})
                for intervention in ['remove43top2','remove54top2']:
                    stress.append(self.task('stress',index,first,model,policy,stress=intervention))
        self.run_tasks(stress,self.deadline-75,'adverse_board_stress')
        # If cost estimates were conservative, use the remaining budget for fresh
        # confirmation blocks rather than finishing early or replaying old worlds.
        existing_indices=[r['task']['index'] for r in self.collect('confirm')]
        index=max(existing_indices,default=-1)+1
        while not STOP and time.time()+self.estimate()*2+120 < self.deadline:
            tasks=[]
            for first,v in selected['branches'].items():
                for model in MODELS:
                    for pid in list(dict.fromkeys([v['chosen'],'simple'])):
                        p=next(p for p in policies[first] if p['id']==pid)
                        tasks.append(self.task('confirm',index,first,model,p))
            self.run_tasks(tasks,self.deadline-75,'confirmation_extra_paths')
            index+=1
            publish(self.run,'Running — additional fresh confirmation',selected)
        state='Interrupted — useful partial results saved' if STOP else 'Complete — wall-clock budget concluded'
        report=publish(self.run,state,selected)
        self.status('interrupted' if STOP else 'complete',publication='FIRST_THREE_PICKS_PLAYBOOK.md')
        self.log('overnight_finished',status=state,wall_seconds=time.time()-self.start,
                 complete_draft_paths=len(self.collect()),publication=str(Path(self.cfg['publication_root'])/'FIRST_THREE_PICKS_PLAYBOOK.md'))
        return report


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('run',type=Path)
    ap.add_argument('--resume-hours',type=float,help='Explicit additional wall budget for an interrupted run; same frozen source and saved tasks.')
    args=ap.parse_args();run=args.run.resolve()
    lock=(run/'run.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
    runner=Runner(run,args.resume_hours)
    try:
        runner.run_all()
    except Exception:
        error=traceback.format_exc();runner.log('fatal_error',traceback=error)
        runner.status('failed',error=error)
        try:publish(run,'Stopped — partial results; inspect progress.log')
        except Exception:traceback.print_exc()
        raise
    finally:
        if runner.executor:runner.executor.shutdown(wait=True,cancel_futures=True)
        lock.close()


if __name__=='__main__':
    main()
