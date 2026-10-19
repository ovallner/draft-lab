"""Bounded supervisor controls test using dummy children, not a draft workload."""
import json
import os
import signal
import sys
import tempfile
import threading
import time
import copy
from unittest.mock import patch
from pathlib import Path

run=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(run/'source/scripts'))
from policy_audit import Supervisor, lock_run, verify

DUMMY='''import argparse,json,time,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run',type=Path);p.add_argument('--task',type=Path);a=p.parse_args()
t=json.loads(a.task.read_text());lane=a.run/t['lane']
if t.get('fail'):sys.exit(1)
while not (lane/'STOP').exists():time.sleep(.025)
(lane/'dummy_checkpoint.json').write_text(json.dumps({'saved':True}))
sys.exit(75)
'''

def fixture(root):
    worker=root/'source/scripts/policy_audit_worker.py';worker.parent.mkdir(parents=True)
    worker.write_text(DUMMY)
    return {'id':'primary.test.0000.production','lane':'control','stage':'primary','model':'test','index':0,'policy':'production'}

proof={}
with tempfile.TemporaryDirectory() as d:
    root=Path(d);task=fixture(root);s=Supervisor(root,{},'control',30)
    previous=signal.signal(signal.SIGINT,s.request_stop)
    timer=threading.Timer(.25,lambda:os.kill(os.getpid(),signal.SIGINT));timer.start()
    try:
        assert s.run_task(task)==75
        assert json.loads((root/'control/dummy_checkpoint.json').read_text())['saved']
        proof['SIGINT_saves_boundary_and_returns_pause']=True
    finally:timer.join();signal.signal(signal.SIGINT,previous)

with tempfile.TemporaryDirectory() as d:
    root=Path(d);task=fixture(root);s=Supervisor(root,{},'control',.1);start=time.monotonic()
    assert s.run_task(task)==75
    assert s.stop and time.monotonic()-start<8
    proof['budget_expiry_requests_checkpoint_stop']=True

with tempfile.TemporaryDirectory() as d:
    root=Path(d);task=fixture(root);task['fail']=True;s=Supervisor(root,{},'control',30)
    try:s.run_task(task)
    except RuntimeError:pass
    else:raise AssertionError('Deterministic failure swallowed')
    events=(root/'control/events.jsonl').read_text()
    assert 'transient_retry' not in events
    assert len(s.failures)==1
    proof['deterministic_failure_propagates_without_retry']=True

verify(run)
proof['frozen_source_hashes_unchanged']=True
from policy_audit_report import load_rows, publish
pilot=load_rows(run,'pilot')
synthetic=[]
for model in ('adp_stochastic','validated'):
    for index in range(20):
        for original in pilot:
            r=copy.deepcopy(original);r['task'].update(stage='primary',model=model,index=index)
            r['diagnostics'].update(five_category_route_fraction=1.,fifth_category_edge=.9,blocked_games=0)
            for o in r['outcomes']:
                o.update(title=int(r['task']['policy']!='production'),qualified=1,advancement=4)
            synthetic.append(r)
with tempfile.TemporaryDirectory() as d:
    tmp=Path(d);(tmp/'source').mkdir();(tmp/'main').mkdir()
    (tmp/'manifest.json').write_bytes((run/'manifest.json').read_bytes())
    (tmp/'source/FIRST_THREE_PICKS_PLAYBOOK.json').write_bytes((run/'source/FIRST_THREE_PICKS_PLAYBOOK.json').read_bytes())
    (tmp/'operational.json').write_text(json.dumps({'passed':True}))
    (tmp/'main/status.json').write_text(json.dumps({'state':'complete'}))
    # Synthetic rubric checks only; no simulated draft/world is created here.
    with patch('policy_audit_report.load_rows',return_value=synthetic),patch('policy_audit_report.paired',return_value={'paths':0}):
        result=publish(tmp,'main')
        assert result['assessment'].startswith('2.')
        assert result['assessment_basis']['projected_downside_and_fit_comparison_pass']
        assert not result['assessment_basis']['observed_competitive_performance_guardrail_pass']
        for r in synthetic:
            for o in r['outcomes']:o['title']=1
        assert publish(tmp,'main')['assessment'].startswith('1.')
        (tmp/'main/status.json').write_text(json.dumps({'state':'failed'}))
        assert publish(tmp,'main')['assessment'].startswith('3.')
proof['readiness_checks_competitive_performance_and_correctness']=True
proof['no_overnight_workload_started']=not (run/'main').exists()
assert proof['no_overnight_workload_started']
(run/'control_checks.json').write_text(json.dumps(proof,indent=2))
print(json.dumps(proof,indent=2))
