"""Loopback-only server; transactional picks never wait for recommendation work."""
import argparse
import json
import mimetypes
import secrets
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from .data import ROOT, Data
from .engine import Engine
from .sessions import Sessions
from .benchmark_jobs import BenchmarkJobs
from .evaluate import RosterEvaluator, EvaluationJobs
from .season_draft import SeasonDraft
from .season_inputs import SeasonInputs


class Application:
    def __init__(self, db):
        self.data = Data()
        self.sessions = Sessions(db, self.data)
        self.engine = Engine(self.data)
        self._benchmark_tmp = None
        if str(db) == ':memory:':
            import tempfile
            self._benchmark_tmp = tempfile.mkdtemp(prefix='draftlab-benchmarks-')
            benchmark_directory = Path(self._benchmark_tmp)
        else:
            benchmark_directory = Path(db).parent / (Path(db).stem + '_benchmarks')
        self.benchmarks = BenchmarkJobs(self.data, benchmark_directory)
        self.inputs = SeasonInputs(self.data)
        self.evaluator = RosterEvaluator(self.engine, self.inputs)
        self.evaluations = EvaluationJobs(benchmark_directory.parent / (benchmark_directory.name + '_evaluations'), self.evaluator)
        self.token = secrets.token_urlsafe(32)
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.RLock()
        self.result = None
        self.error = None
        self.running = False
        self.requested_revision = None
        self.schedule()

    @property
    def store(self):
        return self.sessions.store()

    def payload(self, include_players=False):
        state = self.store.state()
        info = self.sessions.info()
        prediction = None
        if info['mode'] == 'mock':
            prediction = self.engine.opponent_choices(state, info.get('model', 'fit'), info.get('randomness', .35))
        try:
            analysis = self.engine.team_analysis(state, state.get('settings'))
            analysis_error = None
        except Exception as exc:
            analysis = None
            analysis_error = str(exc)
        result = {'state': state, 'session': info, 'sessions': self.sessions.list(),
                  'mock_prediction': prediction, 'analysis': analysis,
                  'analysis_error': analysis_error}
        if include_players:
            result.update(metadata=self.data.metadata(), players=list(self.data.players.values()), token=self.token)
        return result

    def check_session(self, body):
        if body.get('session_id') != self.sessions.active_id:
            raise ValueError('Draft mode changed in another window. Refresh before recording a pick.')

    def advance_mock(self, body):
        if self.sessions.info()['mode'] != 'mock':
            raise ValueError('Opponent simulation is available only in a mock draft. Live picks are never automated.')
        if body.get('revision') != self.store.state()['revision']:
            raise ValueError('Draft changed in another window. Refresh and retry.')
        until_me = body.get('until_me', False)
        if not isinstance(until_me, bool):
            raise ValueError('Invalid simulation action')
        recorded = []
        blocked = None
        for _ in range(156 if until_me else 1):
            state = self.store.state()
            info = self.sessions.info()
            prediction = self.engine.opponent_choices(state, info.get('model', 'fit'), info.get('randomness', .35))
            if prediction['blocked']:
                blocked = prediction['blocked']
                break
            choice = self.engine.sample_opponent(prediction, info['seed'], state['revision'])
            self.store.append('pick', {'slot': prediction['slot'], 'player_id': choice['player_id'],
                              'simulation': {'model': info.get('model', 'fit'), 'reasons': choice['reasons'], 'seed': info['seed']}}, state['revision'])
            recorded.append({'slot': prediction['slot'], 'team': prediction['team'], 'name': choice['name'], 'reasons': choice['reasons']})
        return {'simulated': recorded, 'blocked': blocked}

    def complete_mock(self,body):
        if self.sessions.info()['mode']!='mock':raise ValueError('Full automatic draft is practice-only. Live selections are never automated.')
        state=self.store.state()
        if body.get('revision')!=state['revision']:raise ValueError('Draft changed. Refresh before automatic completion.')
        from .draft_model import apply_scenario,uncertainty_barrier
        scenario=body.get('scenario')
        forecast=apply_scenario(state,scenario,self.data) if scenario else state
        barrier=uncertainty_barrier(forecast,self.data)
        if barrier:raise ValueError(barrier[1]+'. Confirm exact assets on the board or explicitly choose one complete named hypothetical scenario.')
        strategy=body.get('strategy',{'name':'Current build','policy':'playoff','punts':state['settings'].get('punt',[]),'streaming':'aggressive'})
        SeasonInputs.validate_strategy(strategy)
        mode=body.get('opponent_mode','adp_deterministic')
        from .season_inputs import OPPONENT_MODES
        if mode not in OPPONENT_MODES:raise ValueError('Invalid opponent model.')
        draft=SeasonDraft(self.engine).complete(forecast,strategy,mode,self.sessions.info()['seed'])
        # All validation and simulation completes before any automatic selection
        # is saved. Explicit hypothetical asset corrections are mock-only events.
        if scenario:
            for number in scenario.get('clear_keeper_slots',[]):
                self.store.append('slot_override',{'slot':int(number),'changes':{'keeper':False,'keeper_player':'','player_name':''}})
            for number,owner in scenario.get('owners',{}).items():
                self.store.append('slot_override',{'slot':int(number),'changes':{'current_team':owner,'confidence':'explicit_mock_hypothesis'}})
            for number,name in scenario.get('keeper_slots',{}).items():
                self.store.append('slot_override',{'slot':int(number),'changes':{'keeper':True,'keeper_player':name,'player_name':name,'confidence':'explicit_mock_hypothesis'}})
            self.sessions.entries[self.sessions.active_id]['asset_hypothesis']=scenario['name'];self.sessions.save()
        for pick in draft['trace']:
            self.store.append('pick',{'slot':pick['slot'],'player_id':pick['player_id'],
                'simulation':{'model':mode,'own_strategy':strategy['name'],'full_auto_mock':True}})
        return {'simulated':draft['trace'],'automatic_draft':draft}

    def schedule(self):
        with self.lock:
            self.requested_revision = (self.sessions.active_id, self.store.state()['revision'])
            if not self.running:
                self.running = True
                self.pool.submit(self.calculate)

    def close(self):
        self.sessions.close()
        if self._benchmark_tmp:
            import shutil
            shutil.rmtree(self._benchmark_tmp, ignore_errors=True)

    def calculate(self):
        while True:
            with self.lock:
                sid = self.sessions.active_id
                state = self.store.state()
                info = self.sessions.info()
                state['simulation_config'] = {'model': info.get('model', 'fit'), 'randomness': info.get('randomness', .35)}
            start = time.perf_counter()
            try:
                result = self.engine.recommend(state)
                result['strategy'] = self.engine.strategy_summary(state, result)
                result.update(revision=state['revision'], session_id=sid, elapsed_seconds=round(time.perf_counter() - start, 3))
                error = None
            except Exception as exc:
                result, error = None, str(exc)
                import traceback
                traceback.print_exc()
            with self.lock:
                if sid == self.sessions.active_id:
                    if result is not None:
                        self.result = result
                    self.error = error
                if self.requested_revision == (sid, state['revision']):
                    self.running = False
                    return


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args and str(args[1] if len(args) > 1 else '').startswith(('4', '5')):
                super().log_message(fmt, *args)

        def send(self, payload, status=200, content_type='application/json', disposition=None):
            raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'")
            if disposition:
                self.send_header('Content-Disposition', disposition)
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                # Closing/reloading the browser during an in-flight poll is normal.
                pass

        def local_request(self):
            host = self.headers.get('Host', '')
            port = self.server.server_port
            if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                return False
            origin = self.headers.get('Origin')
            return not origin or origin in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')

        def do_GET(self):
            if not self.local_request():
                self.send({'error': 'Local requests only'}, 403)
                return
            path = urlparse(self.path).path
            if path == '/api/state':
                with app.lock:
                    self.send(app.payload(include_players=True))
            elif path == '/api/recommendations':
                with app.lock:
                    self.send({'result': app.result, 'running': app.running, 'error': app.error,
                               'session_id': app.sessions.active_id, 'revision': app.store.state()['revision']})
            elif path == '/api/backup':
                with app.lock:
                    mode = app.sessions.info()['mode']
                    self.send(dict(app.store.export(), session=app.sessions.info()), disposition=f'attachment; filename="fantasy-draft-{mode}-backup.json"')
            elif path == '/api/benchmark-config':
                self.send(app.benchmarks.inputs.metadata())
            elif path == '/api/benchmarks':
                self.send({'runs':app.benchmarks.list()})
            elif path == '/api/evaluations':
                self.send({'evaluations':app.evaluations.list()})
            elif path.startswith('/api/evaluations/'):
                try:
                    self.send(app.evaluations.status(path.split('/')[3]))
                except ValueError as exc:
                    self.send({'error': str(exc)}, 404)
            elif path.startswith('/api/benchmarks/'):
                try:
                    parts=path.split('/');run_id=parts[3];action=parts[4] if len(parts)>4 else 'status'
                    if action=='status':self.send(app.benchmarks.status(run_id))
                    elif action in ('results','export'):
                        self.send({'result':app.benchmarks.results(run_id)} if action=='results' else app.benchmarks.results(run_id),
                                  disposition='attachment; filename="season-benchmark.json"' if action=='export' else None)
                    elif action=='detail':
                        query=parse_qs(urlparse(self.path).query)
                        self.send(app.benchmarks.detail(run_id,*(int(query[k][0]) for k in ('case','draft','season'))))
                    else:self.send({'error':'Not found'},404)
                except (ValueError,KeyError,IndexError) as exc:self.send({'error':str(exc)},400)
            else:
                names = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
                name = names.get(path)
                if not name:
                    self.send({'error': 'Not found'}, 404)
                    return
                file = ROOT / 'web' / name
                self.send(file.read_bytes(), content_type=mimetypes.guess_type(name)[0] or 'text/plain')

        def do_POST(self):
            if not self.local_request() or self.headers.get('X-Draft-Token') != app.token:
                self.send({'error': 'Invalid local request token; reload the page.'}, 403)
                return
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 5_000_000:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(size))
                path = urlparse(self.path).path
                with app.lock:
                    app.check_session(body)
                    extra = {}
                    if path == '/api/event':
                        if 'revision' not in body:
                            raise ValueError('Draft revision required')
                        app.store.append(body['kind'], body['payload'], body['revision'])
                    elif path == '/api/restore':
                        if body.get('session', {}).get('mode') == 'mock' and app.sessions.info()['mode'] == 'live':
                            raise ValueError('This is a practice backup. Switch to a fresh mock session to restore it; live picks will not be changed.')
                        app.store.restore(body)
                    elif path == '/api/session':
                        action = body.get('action')
                        if action in ('new_mock', 'reset_mock'):
                            if action == 'reset_mock' and app.sessions.info()['mode'] != 'mock':
                                raise ValueError('Reset is only available for mock drafts; the live draft cannot be reset.')
                            app.sessions.new_mock()
                        elif action == 'switch':
                            app.sessions.switch(body['target_id'])
                        else:
                            raise ValueError('Unknown session action')
                        app.result = None
                        app.error = None
                    elif path == '/api/mock/config':
                        if app.sessions.info()['mode'] != 'mock':
                            raise ValueError('Mock settings are only available in practice mode.')
                        model, randomness = body.get('model'), body.get('randomness')
                        if model not in ('adp', 'fit') or not isinstance(randomness, (float, int)) or not .1 <= randomness <= 1:
                            raise ValueError('Invalid mock draft settings')
                        app.sessions.entries[app.sessions.active_id].update(model=model, randomness=randomness)
                        app.sessions.save()
                    elif path == '/api/mock/advance':
                        extra = app.advance_mock(body)
                    elif path == '/api/mock/complete':
                        extra=app.complete_mock(body)
                    elif path == '/api/evaluate':
                        if body.get('revision') != app.store.state()['revision']:
                            raise ValueError('Draft changed. Refresh before evaluating.')
                        state = app.store.state()
                        issues = app.evaluator.validate(state)
                        if issues:
                            self.send({'error': 'This draft is not ready to evaluate.', 'issues': issues}, 400)
                            return
                        seasons = body.get('seasons', 40)
                        streaming = body.get('streaming', 'aggressive')
                        if type(seasons) is not int or not 5 <= seasons <= 200:
                            raise ValueError('seasons must be an integer 5–200')
                        if streaming not in ('aggressive', 'observed', 'injury_only', 'off'):
                            raise ValueError('invalid streaming mode')
                        config, _ = app.inputs.prepare(state, {})
                        snapshot = app.evaluator.snapshot(state, app.sessions.info())
                        self.send(app.evaluations.start(snapshot, config, seasons, streaming))
                        return
                    elif path == '/api/benchmarks':
                        if body.get('revision')!=app.store.state()['revision']:raise ValueError('Draft changed. Refresh before freezing a benchmark snapshot.')
                        status=app.benchmarks.start(app.store.state(),body['config'],app.sessions.info())
                        self.send(status);return
                    elif path.startswith('/api/benchmarks/'):
                        parts=path.split('/');run_id=parts[3];action=parts[4] if len(parts)>4 else ''
                        if action=='cancel':status=app.benchmarks.cancel(run_id)
                        elif action=='resume':status=app.benchmarks.resume(run_id)
                        else:raise ValueError('Unknown benchmark action.')
                        self.send(status);return
                    else:
                        self.send({'error': 'Not found'}, 404)
                        return
                    app.schedule()
                    self.send(dict(app.payload(), **extra))
            except (ValueError, KeyError, TypeError) as exc:
                self.send({'error': str(exc)}, 400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Offline fantasy basketball draft assistant')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--db', type=Path, default=ROOT / 'local' / 'draft.sqlite3')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    app = Application(args.db)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(app))
    url = f'http://127.0.0.1:{server.server_port}'
    print(f'Draft assistant: {url}\nLocal saves: {args.db}\nCtrl-C to stop. Draft survives restarts.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.pool.shutdown(wait=True)
        app.close()


if __name__ == '__main__':
    main()
