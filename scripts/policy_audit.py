#!/usr/bin/env python3
"""Terminal-owned, single-worker policy audit. Preparation never launches a run."""
import argparse
import collections
import fcntl
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from policy_audit_worker import atomic, hashed, POLICIES, NAMESPACE

VERSION=1
ROOT=Path(__file__).resolve().parent.parent


def source_hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def verify(run):
    manifest=json.loads((run/'manifest.json').read_text())
    actual=source_hashes(run/'source')
    if actual!=manifest['hashes']:
        changed=[n for n in set(actual)|set(manifest['hashes']) if actual.get(n)!=manifest['hashes'].get(n)]
        raise ValueError('Frozen inputs changed; refusing mixed-code resume: '+', '.join(changed))
    if manifest['python']!=list(sys.version_info[:2]):raise ValueError('Python major/minor differs from frozen runtime')
    return manifest


def prepare(out,projection,hours):
    if out.exists():raise ValueError('Output directory already exists; choose a new directory')
    out.mkdir(parents=True);source=out/'source';source.mkdir()
    for name in ['app','web','data','fantasy_league_2026_27_schedule_with_dates',
                 'manager_persona_2025_adp_handoff','manager_persona_three_season_history']:
        shutil.copytree(ROOT/name,source/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    for p in ROOT.iterdir():
        if p.is_file() and p.suffix in ('.csv','.json'):shutil.copy2(p,source/p.name)
    for name in ['run.py','FIRST_THREE_PICKS_PLAYBOOK.md','OWNERSHIP_CONFIRMED.md']:
        shutil.copy2(ROOT/name,source/name)
    (source/'scripts').mkdir();(source/'tests').mkdir()
    for name in ['policy_audit.py','policy_audit_worker.py','policy_audit_report.py']:
        shutil.copy2(ROOT/'scripts'/name,source/'scripts'/name)
    for name in ['test_policy_audit.py','policy_audit_browser.cjs']:
        shutil.copy2(ROOT/'tests'/name,source/'tests'/name)
    shutil.copy2(projection,source/'hashtag_basketball_2026_27_projections_430.csv')
    config={'format':VERSION,'budget_seconds':int(hours*3600),'workers':1,'seasons':3,
        'namespace':NAMESPACE,'policy_order':list(POLICIES),
        'primary_models':['adp_stochastic','validated'],
        'sensitivity_models':['market_tight','need_pressure'],
        'adverse_models':['center_run','guard_run'],
        'schedule':'Per index both primary models; every fourth index one path/model of each sensitivity. Two center-run and two guard-run cases, inserted at indices 0 and 7. All four policies per case.',
        'season_management':'All policies: Oscar aggressive streaming, no imposed punt for any team, opponents observed activity, default placement eligibility/FAB/waivers/IL. Temporary draft build labels never change season management.',
        'production_selection':'Exact web featured rule: first row with availability_at_next null/missing or >=0.5; if no such row use backend first row. Stable backend tie order.',
        'adp_selection':'Minimum (market_adp, projection rank, provider ID) among available nonkeepers; source-rank market interpolation for missing ADP is labeled.',
        'fit_selection':'Shared SeasonDraft.pick policy=fit risk=.5, no punts, playoff_weight=0. Market window first 10 if roster<7 else16. Shrink saturated category weights; GP health discount; +.35 for first C, +.2 for first forward; -.025*log(1+market ordinal). Equal scores choose first market-ordered player. No center cap.',
        'playbook_selection':'Literal provisional first-pick chain KAT, Mobley, Sengun, Markkanen, Maxey, Barnes, Durant, Bam; #43/#54 branch from preserved JSON, first available ID. Outside chain/branch use best available ADP. From #67 follow displayed production. Optional elite-contingency override not used: old prose did not specify a unique automatic override rule.',
        'uncertainty':'Paired source draft paths are clusters, seasons averaged within path; models/scenarios kept separate. Pointwise cluster bootstrap plus conservative simultaneous bounded intervals. No equivalence/noninferiority claim from non-significance.',
        'heuristics':{'weak_route_fraction':.33,'high_blocked_games':12,'large_reach_remaining_rank':20,
                      'plausible_wait_probability':.6,'clock_seconds':45,'latency_guardrail_seconds':35},
        'readiness_rules':'See frozen policy_audit_report.py. Performance assessment includes route distributions, downside relative to competent fit, operational evidence and correctness; championship significance is not required.'}
    manifest={'format':VERSION,'prepared_epoch':time.time(),'python':list(sys.version_info[:2]),
        'platform':platform.platform(),'config':config,'projection_source':str(projection),
        'original_playbook_sha256':hashlib.sha256((source/'FIRST_THREE_PICKS_PLAYBOOK.json').read_bytes()).hexdigest(),
        'hashes':source_hashes(source)}
    atomic(out/'manifest.json',manifest)
    atomic(out/'prepared.json',{'state':'prepared_not_launched','manifest_hash':hashed(manifest)})
    print('Prepared only:',out,flush=True)


def task(run,manifest,lane,stage,model,index,policy):
    return {'id':f'{stage}.{model}.{index:04d}.{policy}','lane':lane,'stage':stage,'model':model,
            'index':index,'policy':policy,'seasons':manifest['config']['seasons'],
            'manifest_hash':hashed(manifest)}


def tasks(run,manifest,lane='main'):
    for i in range(10000):
        cases=[('primary',m,i) for m in manifest['config']['primary_models']]
        if i%4==3:cases += [('sensitivity',m,i//4) for m in manifest['config']['sensitivity_models']]
        if i in (0,7):cases += [('adverse',m,int(i==7)) for m in manifest['config']['adverse_models']]
        for stage,model,index in cases:
            for policy in POLICIES:yield task(run,manifest,lane,stage,model,index,policy)


def counts(run,lane):
    groups=collections.defaultdict(set);policies=collections.Counter()
    for p in (run/lane/'tasks').glob('*.json'):
        if p.name.endswith('.checkpoint.json'):continue
        stage,model,index,policy=p.stem.split('.')
        groups[(stage,model,index)].add(policy);policies[stage]+=1
    complete=collections.Counter(f'{s}/{m}' for (s,m,i),ps in groups.items() if set(POLICIES)==ps)
    return {'completed_policy_drafts':dict(policies),'completed_independent_paths':dict(complete),
            'partial_paths':sum(ps!=set(POLICIES) for ps in groups.values())}


def lock_run(run):
    f=(run/'run.lock').open('a')
    try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:f.close();raise ValueError('Another process owns this run directory')
    return f


class Supervisor:
    def __init__(self,run,manifest,lane,budget,prior=0.):
        self.run=run;self.manifest=manifest;self.lane=lane;self.budget=budget;self.prior=prior
        self.started=time.monotonic();self.stop=False;self.child=None;self.failures=[];self.current=None
        (run/lane).mkdir(exist_ok=True);(run/lane/'STOP').unlink(missing_ok=True)

    @property
    def elapsed(self):return self.prior+time.monotonic()-self.started

    def log(self,event,**fields):
        row={'at':time.time(),'event':event,'elapsed_seconds':round(self.elapsed,1),**fields}
        with (self.run/self.lane/'events.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)

    def status(self,state):
        row={'state':state,'pid':os.getpid(),'heartbeat_epoch':time.time(),'elapsed_seconds':self.elapsed,
             'budget_seconds':self.budget,'remaining_seconds':max(0,self.budget-self.elapsed),
             'current_task':self.current,'failures':self.failures,**counts(self.run,self.lane)}
        atomic(self.run/self.lane/'status.json',row);return row

    def request_stop(self,*_):
        self.stop=True;(self.run/self.lane/'STOP').touch()

    def run_task(self,t,stop_after=None):
        dest=self.run/self.lane/'tasks'/(t['id']+'.json')
        if dest.exists():return 0
        request=self.run/self.lane/'requests'/(t['id']+'.json');atomic(request,t)
        cmd=[sys.executable,'-B',str(self.run/'source/scripts/policy_audit_worker.py'),
             '--run',str(self.run),'--task',str(request)]
        if stop_after is not None:cmd+=['--stop-after',str(stop_after)]
        logs=self.run/self.lane/'logs';logs.mkdir(exist_ok=True)
        self.current=t['id'];self.status('running');self.log('task_started',task=t['id'])
        for attempt in range(2):
            begin=time.monotonic()
            with (logs/(t['id']+'.log')).open('ab') as log:
                self.child=subprocess.Popen(cmd,cwd=self.run/'source',stdout=log,stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,start_new_session=True)
                while True:
                    try:code=self.child.wait(timeout=5);break
                    except subprocess.TimeoutExpired:
                        if self.elapsed>=self.budget or (self.run/self.lane/'STOP').exists():self.request_stop()
                        if time.monotonic()-begin>600:
                            os.killpg(self.child.pid,signal.SIGKILL);self.child.wait()
                            raise RuntimeError('Task exceeded 600-second limit; inspect task log. No automatic timeout retry.')
                        self.status('stopping' if self.stop else 'running')
            self.child=None
            if code==0:
                if not dest.exists():raise RuntimeError('Worker exited without complete result')
                self.log('task_completed',task=t['id'],seconds=round(time.monotonic()-begin,2));return 0
            if code==75:
                self.log('checkpoint_saved',task=t['id']);return 75
            if code==-signal.SIGKILL and attempt==0 and not self.stop:
                self.log('transient_retry',task=t['id'],exit_code=code,note='One fresh-process retry after abrupt kill; cause unknown.')
                continue
            self.failures.append({'task':t['id'],'exit_code':code,'log':str(logs/(t['id']+'.log'))})
            raise RuntimeError(f'Worker failed ({code}); task {t["id"]}. No scientific-code changes or substitution allowed.')
        raise RuntimeError('Retry exhausted')


def pilot(run):
    manifest=verify(run);lock=lock_run(run)
    supervisor=Supervisor(run,manifest,'pilot',600)
    signal.signal(signal.SIGINT,supervisor.request_stop);signal.signal(signal.SIGTERM,supervisor.request_stop)
    try:
        t=task(run,manifest,'pilot','primary','adp_stochastic',0,'production')
        checkpoint=run/'pilot/tasks'/(t['id']+'.checkpoint.json');dest=run/'pilot/tasks'/(t['id']+'.json')
        if dest.exists():raise ValueError('Pilot already completed; use saved measurements, do not duplicate it')
        assert supervisor.run_task(t,2)==75
        cp=json.loads(checkpoint.read_text());assert len(cp['decisions'])==2
        first_hash=hashed(cp['decisions'])
        assert supervisor.run_task(t,9)==75
        cp=json.loads(checkpoint.read_text());assert len(cp['decisions'])==10 and len(cp['outcomes'])==1
        assert hashed(cp['decisions'][:2])==first_hash
        world_hash=hashed(cp['outcomes'][0]);assert supervisor.run_task(t)==0
        result=json.loads(dest.read_text());assert len(result['decisions'])==10 and len(result['outcomes'])==3
        assert hashed(result['outcomes'][0])==world_hash
        before=dest.read_bytes();assert supervisor.run_task(t)==0;assert dest.read_bytes()==before
        for p in POLICIES[1:]:
            if supervisor.stop or supervisor.elapsed>550:raise RuntimeError('Bounded pilot did not finish; main workload remains unlaunched')
            assert supervisor.run_task(task(run,manifest,'pilot','primary','adp_stochastic',0,p))==0
        rows=[json.loads(p.read_text()) for p in (run/'pilot/tasks').glob('*.json') if not p.name.endswith('.checkpoint.json')]
        costs={r['task']['policy']:r['active_seconds'] for r in rows};bundle=sum(costs.values())
        # Approximately 20% of time goes to sensitivity/adverse/reporting. Inflate
        # measured costs for cold caches, harder boards and thermal variability.
        hours=manifest['config']['budget_seconds']/3600
        estimate=[int(hours*3600*.75/(bundle*2*1.6)),int(hours*3600*.8/(bundle*2*1.1))]
        proof={'complete':True,'pilot_seconds':supervisor.elapsed,'cost_per_policy':costs,
            'paired_bundle_seconds':bundle,'estimated_primary_paths_per_model_range':estimate,
            'estimate_note':'Single-worker effort estimate, not promised coverage; independent source indices per primary model. Pilot deliberately excluded from main evidence.',
            'resume_checks':{'mid_draft':True,'mid_season_batch':True,'no_duplicate_complete_task':True,
                             'saved_picks_unchanged':True,'saved_world_unchanged':True},'manifest_hash':hashed(manifest)}
        atomic(run/'pilot/proof.json',proof);supervisor.status('complete')
        from policy_audit_report import publish
        publish(run,'pilot');print(json.dumps(proof,indent=2),flush=True)
    except Exception:
        supervisor.status('failed');raise
    finally:lock.close()


def seal(run):
    manifest=verify(run)
    proof=json.loads((run/'pilot/proof.json').read_text());ops=json.loads((run/'operational.json').read_text())
    checks=json.loads((run/'checks.json').read_text())
    if not proof['complete'] or not ops['passed'] or not checks['passed']:raise ValueError('Readiness checks failed; main run blocked')
    atomic(run/'READY.json',{'manifest_hash':hashed(manifest),
        'evidence_hashes':{n:hashlib.sha256((run/n).read_bytes()).hexdigest() for n in ['pilot/proof.json','operational.json','checks.json']},
        'state':'ready_not_launched','sealed_epoch':time.time()})
    print('Ready. Overnight workload has NOT been launched.',flush=True)


def run_main(run,resume,hours,workers):
    manifest=verify(run);ready=json.loads((run/'READY.json').read_text())
    if ready['manifest_hash']!=hashed(manifest):raise ValueError('Readiness manifest mismatch')
    for name,h in ready['evidence_hashes'].items():
        if hashlib.sha256((run/name).read_bytes()).hexdigest()!=h:raise ValueError('Sealed readiness evidence changed: '+name)
    if workers!=1 or hours*3600!=manifest['config']['budget_seconds']:raise ValueError('Runtime options differ from frozen config')
    lock=lock_run(run);status_path=run/'main/status.json';prior=0.
    if status_path.exists():
        if not resume:raise ValueError('Existing run: pass --resume to reuse checkpoints')
        previous=json.loads(status_path.read_text());prior=previous['elapsed_seconds']
        if previous['state']=='failed':
            resolution=run/'main/RESOLUTION.json'
            if not resolution.exists():
                raise ValueError('Previous failure requires diagnosis. Write main/RESOLUTION.json with keys diagnosis, classification, fix and evidence_before_failure, then resume.')
            note=json.loads(resolution.read_text())
            if not note.get('diagnosis') or not note.get('classification'):raise ValueError('Resolution must record diagnosis and classification')
            print('Resuming after recorded diagnosis: '+note['classification'],flush=True)
        if previous['state']=='complete':print('Run already complete; saved report retained.');lock.close();return
    supervisor=Supervisor(run,manifest,'main',hours*3600,prior)
    signal.signal(signal.SIGINT,supervisor.request_stop);signal.signal(signal.SIGTERM,supervisor.request_stop)
    from policy_audit_report import publish
    try:
        supervisor.log('resumed' if resume else 'started',workers=1,manifest_hash=hashed(manifest))
        completed_since_report=0
        for t in tasks(run,manifest):
            if (run/'main/tasks'/(t['id']+'.json')).exists():continue
            if supervisor.stop or supervisor.elapsed>=supervisor.budget-20:break
            verify(run)
            code=supervisor.run_task(t)
            if code==75:supervisor.request_stop();break
            completed_since_report+=1
            if completed_since_report>=8:
                supervisor.status('reporting');publish(run,'main');completed_since_report=0
        state='interrupted' if supervisor.stop and supervisor.elapsed<supervisor.budget else 'complete'
        if not supervisor.stop:state='complete'
        supervisor.status(state);publish(run,'main');supervisor.log('finished',state=state,**counts(run,'main'))
    except Exception:
        import traceback
        supervisor.log('failure',traceback=traceback.format_exc());supervisor.status('failed');publish(run,'main')
        raise
    finally:
        if supervisor.child and supervisor.child.poll() is None:
            supervisor.request_stop();supervisor.child.wait(timeout=90)
        lock.close()


def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--out',type=Path,required=True);p.add_argument('--projection',type=Path,required=True);p.add_argument('--hours',type=float,default=7)
    for command in ['pilot','seal','status','stop','report']:
        p=sub.add_parser(command);p.add_argument('--run',type=Path,required=True)
    p=sub.add_parser('run');p.add_argument('--run',type=Path,required=True);p.add_argument('--resume',action='store_true');p.add_argument('--hours',type=float,default=7);p.add_argument('--workers',type=int,choices=[1],default=1)
    args=ap.parse_args()
    if args.command=='prepare':return prepare(args.out.resolve(),args.projection.resolve(),args.hours)
    run=args.run.resolve()
    if args.command=='pilot':return pilot(run)
    if args.command=='seal':return seal(run)
    if args.command=='run':return run_main(run,args.resume,args.hours,args.workers)
    if args.command=='stop':
        if not (run/'main').exists():raise ValueError('Main run has not started')
        (run/'main/STOP').touch();print('Graceful stop requested; waiting task checkpoints at next pick/season boundary.');return
    if args.command=='report':
        verify(run)
        from policy_audit_report import publish
        publish(run,'main');return
    if args.command=='status':
        p=run/'main/status.json'
        if not p.exists():print(json.dumps({'state':'ready_not_launched' if (run/'READY.json').exists() else 'prepared_not_launched'},indent=2));return
        s=json.loads(p.read_text());s['heartbeat_age_seconds']=round(time.time()-s['heartbeat_epoch'],1)
        try:l=lock_run(run);l.close();active=False
        except ValueError:active=True
        s['active_run_lock']=active
        if not active and s['state'] in ('running','reporting','stopping'):s['state']='interrupted_without_final_status'
        print(json.dumps(s,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr);sys.exit(1)
