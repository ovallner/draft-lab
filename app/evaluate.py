"""Fixed-roster season evaluation for a COMPLETED draft.

Immutable snapshot of every recorded roster + source session/revision. NO drafting occurs:
the recorded rosters are played out over several seasons to estimate playoff/championship
frequencies. Uncertainty is season-sampling conditional on the model — not a set of
independent draft constructions.

Season-management assumptions are explicit and identical for every manager (streaming, no
punts, standard config), so the comparison is fixed-roster only.
"""
import hashlib
import json
import random
import statistics
import threading
import time
from pathlib import Path

from . import seeds
from .draft_model import uncertainty_barrier
from .season_sim import SeasonSimulator
from .season_world import SeasonWorld

DEFAULT_SEASONS = 40
DEFAULT_STREAMING = 'aggressive'
SEED_SALT = 20261018


def projections_hash(data):
    return hashlib.sha256((data.root / 'hashtag_basketball_2026_27_projections_430.csv').read_bytes()).hexdigest()


class RosterEvaluator:
    def __init__(self, engine, inputs):
        self.engine = engine
        self.data = engine.data
        self.inputs = inputs
        self.simulator = SeasonSimulator(engine, inputs)

    def validate(self, state):
        """Return a list of concrete problems (with a repair hint) or []."""
        issues = []
        barrier = uncertainty_barrier(state, self.data)
        if barrier:
            issues.append({'kind': 'integrity', 'message': barrier[1], 'repair': 'Board settings'})
        rosters = self.engine.rosters(state)
        short = [t for t in self.data.teams if len(rosters[t]) != 13]
        if short:
            detail = ', '.join('%s %d/13' % (t, len(rosters[t])) for t in short)
            issues.append({'kind': 'incomplete', 'message': 'Rosters not complete: ' + detail, 'repair': 'Finish the draft (Board)'})
        unprojected = [p['name'] for r in rosters.values() for p in r if not p.get('projected')]
        if unprojected:
            issues.append({'kind': 'projection', 'message': '%d recorded player(s) lack projections: %s' % (len(unprojected), ', '.join(unprojected[:5])), 'repair': 'Board / projections'})
        return issues

    def snapshot(self, state, session):
        return {'session': {'id': session['id'], 'name': session['name'], 'mode': session['mode']},
                'revision': state['revision'],
                'rosters': {t: [p['id'] for p in r] for t, r in self.engine.rosters(state).items()},
                'projections_sha256': projections_hash(self.data),
                'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    def evaluate(self, snapshot, config, seasons, streaming, progress=None):
        teams = self.data.teams
        me = self.data.config['team_name']
        draft = {'rosters': {t: list(snapshot['rosters'][t]) for t in teams},
                 'punts': {t: [] for t in teams},
                 'own_strategy': {'name': 'Recorded roster', 'streaming': streaming, 'punts': [], 'playoff_weight': .8, 'risk': .5},
                 'opponent_mode': None,
                 'manager_policies': {t: {'streaming': streaming, 'punts': []} for t in teams if t != me}}
        t0 = time.perf_counter()
        per_team = {t: [] for t in teams}
        for i in range(seasons):
            world = SeasonWorld(self.data, self.inputs, config['calendar'],
                                seeds.world_seed(SEED_SALT, 'roster_eval', 1, i + 1, i), config)
            out = self.simulator.run(draft, world, config)
            for t in teams:
                per_team[t].append(out['teams'][t])
            if progress:
                progress(i + 1, seasons, time.perf_counter() - t0)

        def advancement(o):
            return int(bool(o['qualified'])) + int(bool(o['semifinal'])) + int(bool(o['final'])) + int(bool(o['champion']))

        def season_interval(values):
            if len(values) < 5:
                return {'low': None, 'high': None}
            rng = random.Random(11)
            boots = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(1000))
            return {'low': boots[24], 'high': boots[974]}

        summary = {}
        for t in teams:
            outs = per_team[t]
            titles = [float(bool(o['champion'])) for o in outs]
            advs = [advancement(o) for o in outs]
            summary[t] = {'title_rate': statistics.mean(titles), 'title_interval': season_interval(titles),
                          'advancement': statistics.mean(advs), 'advancement_interval': season_interval(advs),
                          'qualification_rate': statistics.mean(float(o['qualified']) for o in outs),
                          'final_rate': statistics.mean(float(o['final']) for o in outs),
                          'regular_rank': statistics.mean(o['regular_rank'] for o in outs)}
        elapsed = time.perf_counter() - t0
        return {'format': 'roster-evaluation-v1', 'session': snapshot['session'], 'revision': snapshot['revision'],
                'season_count': seasons, 'elapsed_seconds': round(elapsed, 1),
                'projections_sha256': snapshot['projections_sha256'], 'created_at': snapshot['created_at'],
                'assumptions': {'streaming': streaming, 'punts': 'none (all managers)',
                                'eligibility': config.get('eligibility'), 'starting_fab': config.get('starting_fab'),
                                'waiver_days': config.get('waiver_days'), 'injury_scale': config.get('injury_scale'),
                                'mean_injury_days': config.get('mean_injury_days'),
                                'calendar_source': config.get('calendar_source')},
                'teams': summary,
                'note': ('Fixed recorded rosters played out over %d synthetic seasons (%d distinct world seeds). '
                         'Uncertainty is season sampling conditional on the model; it is NOT independent draft '
                         'constructions, and there is no drafting to vary.' % (seasons, seasons))}


class EvaluationJobs:
    """One evaluation at a time; results persisted so a refresh restores them."""

    def __init__(self, directory, evaluator):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.evaluator = evaluator
        self.lock = threading.Lock()
        self.jobs = {}
        self.order = []

    def _write(self, job_id, name, payload):
        (self.directory / job_id).mkdir(parents=True, exist_ok=True)
        (self.directory / job_id / name).write_text(json.dumps(payload, indent=1))

    def running(self):
        return next((j for j in self.jobs.values() if j['state'] == 'running'), None)

    def start(self, snapshot, config, seasons, streaming):
        with self.lock:
            if self.running():
                raise ValueError('An evaluation is already running. Wait for it to finish or cancel it.')
            for jid, j in self.jobs.items():
                if (j.get('session', {}).get('id') == snapshot['session']['id']
                        and j.get('revision') == snapshot['revision'] and j['state'] == 'complete'):
                    return self.status(jid)   # idempotent: same session+revision already evaluated
            job_id = 'eval-' + hashlib.sha256((snapshot['session']['id'] + ':' + str(snapshot['revision']) + ':' + str(time.time())).encode()).hexdigest()[:12]
            job = {'id': job_id, 'state': 'running', 'done': 0, 'total': seasons,
                   'session': snapshot['session'], 'revision': snapshot['revision'], 'seasons': seasons,
                   'streaming': streaming, 'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   'result': None, 'issues': []}
            self.jobs[job_id] = job
            self.order.append(job_id)
            self._write(job_id, 'status.json', {k: v for k, v in job.items() if k != 'result'})
            threading.Thread(target=self._run, args=(job_id, snapshot, config, seasons, streaming), daemon=True).start()
            return self.status(job_id)

    def _run(self, job_id, snapshot, config, seasons, streaming):
        def progress(done, total, elapsed):
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job['done'] = done
                    job['elapsed_seconds'] = round(elapsed, 1)
                    job['eta_seconds'] = round(elapsed / done * (total - done), 1) if done else None
        try:
            result = self.evaluator.evaluate(snapshot, config, seasons, streaming, progress)
            with self.lock:
                job = self.jobs[job_id]
                job.update(state='complete', result=result, done=seasons, elapsed_seconds=result['elapsed_seconds'])
                snapshot_for_disk = {k: v for k, v in job.items()}
            self._write(job_id, 'status.json', {k: v for k, v in snapshot_for_disk.items() if k != 'result'})
            self._write(job_id, 'results.json', result)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            with self.lock:
                job = self.jobs[job_id]
                job.update(state='failed', error=str(exc))
            self._write(job_id, 'status.json', {k: v for k, v in self.jobs[job_id].items() if k != 'result'})

    def status(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            path = self.directory / job_id / 'status.json'
            if not path.exists():
                raise ValueError('Evaluation not found')
            job = json.loads(path.read_text())
            rpath = self.directory / job_id / 'results.json'
            if rpath.exists():
                job['result'] = json.loads(rpath.read_text())
        return job

    def list(self):
        rows = []
        for jid in reversed(self.order):
            j = self.jobs[jid]
            rows.append({'id': jid, 'state': j['state'], 'session': j.get('session'), 'revision': j.get('revision'),
                         'seasons': j.get('seasons'), 'started_at': j.get('started_at')})
        return rows
