"""Local process jobs with immutable requests, cancellation and resumable files."""
import hashlib
import json
import re
import subprocess
import sys
import uuid
import fcntl
from datetime import datetime,timezone
from pathlib import Path
from .benchmark import atomic_json
from .season_inputs import SeasonInputs


INPUT_FILES = ('league_config.json','keepers.csv','draft_slots.csv','hashtag_basketball_2026_27_projections_430.csv',
               'data/nba_schedule.json','data/player_bios.json','data/history3/profiles.json','data/history3/validation.json',
               'manager_persona_three_season_history/combined_draft_2023_2025.csv',
               'manager_persona_three_season_history/keepers_2023_yahoo_marked.csv',
               'data/streaming_activity_2025.csv','playoff_team_weekly_games.csv',
               'fantasy_league_2026_27_schedule_with_dates/fantasy_week_calendar.csv',
               'fantasy_league_2026_27_schedule_with_dates/weekly_matchups.csv',
               'fantasy_league_2026_27_schedule_with_dates/weekly_team_schedule.csv','fantasy_league_2026_27_schedule_with_dates/teams.csv')
INPUT_FILES += ('app/season_inputs.py','app/season_draft.py','app/season_world.py','app/season_sim.py',
                'app/benchmark.py','app/engine.py','app/draft_model.py','app/market.py',
                'app/data.py','app/history.py','app/seeds.py')


def input_hashes(root):
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in INPUT_FILES if (root/name).exists()}


def locked(path):
    if not path.exists():return False
    with path.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        fcntl.flock(handle,fcntl.LOCK_UN);return False


class BenchmarkJobs:
    def __init__(self,data,directory):
        self.data=data;self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.inputs=SeasonInputs(data);self.processes={}

    def path(self,run_id):
        if not isinstance(run_id,str) or not re.fullmatch(r'[a-f0-9]{32}',run_id):raise ValueError('Invalid benchmark ID')
        path=self.directory/run_id
        if not path.is_dir():raise ValueError('Benchmark not found')
        return path

    def active(self):
        return any(p.poll() is None for p in self.processes.values()) or locked(self.directory/'.active.lock')

    def launch(self,path):
        if self.active():raise ValueError('A benchmark is already running. Cancel it or wait before starting another.')
        log=(path/'worker.log').open('ab')
        try:
            process=subprocess.Popen([sys.executable,'-m','app.benchmark_worker',str(path.resolve())],cwd=self.data.root,
                                     stdout=log,stderr=log)
        finally:log.close()
        self.processes[path.name]=process

    def start(self,state,config,session):
        if self.active():raise ValueError('A benchmark is already running.')
        prepared,_=self.inputs.prepare(state,config)
        run_id=uuid.uuid4().hex;path=self.directory/run_id;path.mkdir()
        request={'state':state,'config':prepared,'source_session':session,
                 'created_at':datetime.now(timezone.utc).isoformat(),'input_hashes':input_hashes(self.data.root)}
        # Persist user-facing config, not derived fields rejected by prepare().
        request['config']=config
        atomic_json(path/'request.json',request)
        atomic_json(path/'status.json',{'state':'running','completed':0,'total':prepared['total_seasons'],'run_id':run_id})
        self.launch(path)
        return self.status(run_id)

    def status(self,run_id):
        path=self.path(run_id)
        result=json.loads((path/'status.json').read_text())
        process=self.processes.get(run_id)
        if result['state']=='running' and not locked(path/'worker.lock') and (process is None or process.poll() is not None):
            result=dict(result,state='interrupted',error='Worker is not active in this server. Resume to reuse saved seasons.')
        return result

    def list(self):
        rows=[]
        for p in sorted(self.directory.iterdir(),key=lambda p:p.name,reverse=True):
            if not p.is_dir() or not (p/'request.json').exists():continue
            try:
                req=json.loads((p/'request.json').read_text());status=self.status(p.name)
                status.update(created_at=req['created_at'],source_session=req['source_session']);rows.append(status)
            except (ValueError,OSError,KeyError):continue
        return sorted(rows,key=lambda r:r['created_at'],reverse=True)[:30]

    def cancel(self,run_id):
        path=self.path(run_id)
        (path/'cancel.request').write_text('User requested cancellation. Completed seasons are retained.\n')
        return self.status(run_id)

    def resume(self,run_id):
        path=self.path(run_id);request=json.loads((path/'request.json').read_text())
        if request['input_hashes']!=input_hashes(self.data.root):raise ValueError('Inputs changed since this request. Start a new benchmark; mixed-input resumes are refused.')
        if self.status(run_id)['state']=='completed':raise ValueError('This benchmark is already complete.')
        if self.active():raise ValueError('A benchmark is already running.')
        (path/'cancel.request').unlink(missing_ok=True)
        atomic_json(path/'status.json',{'state':'running','completed':0,'total':0,'run_id':run_id,'resuming':True})
        self.launch(path);return self.status(run_id)

    def results(self,run_id):
        path=self.path(run_id)/'results.json'
        if not path.exists():return None
        result=json.loads(path.read_text())
        # Runs created before the recommendation feature still get one computed on
        # read. This never rewrites the stored file.
        if result.get('cases') and not result.get('recommendation'):
            try:
                from .benchmark import BenchmarkRunner
                result['recommendation']=BenchmarkRunner.recommendation(result,result['config']['seed'])
            except Exception:
                pass
        return result

    def detail(self,run_id,case,draft,season):
        for x in (case,draft,season):
            if type(x) is not int or x<0 or x>1000:raise ValueError('Invalid detail index.')
        path=self.path(run_id)/f'case-{case}-draft-{draft}-season-{season}.json'
        if not path.exists():raise ValueError('Season detail not available.')
        return json.loads(path.read_text())
