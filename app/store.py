"""Transactional append-only events plus a replayable current draft state."""
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


class Store:
    def __init__(self, path, data):
        self.path = str(path)
        if self.path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.data = data
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY CHECK(id=1), state TEXT NOT NULL)')
        self.db.commit()

    def events(self):
        with self.lock:
            return [{'id': r[0], 'timestamp': r[1], 'kind': r[2], 'payload': json.loads(r[3])}
                    for r in self.db.execute('SELECT id,timestamp,kind,payload FROM events ORDER BY id')]

    def state(self):
        with self.lock:
            events = self.events()
            disabled = {e['payload']['event_id'] for e in events if e['kind'] == 'undo'}
            slots = {int(s['overall_slot']): dict(s, slot=int(s['overall_slot']),
                     keeper=s['keeper_forfeit_flag'] == 'true', player_id=None, player_name=s['keeper_player'])
                     for s in self.data.slots}
            settings = {}
            custom = {}
            for e in events:
                if e['id'] in disabled:
                    continue
                p = e['payload']
                if e['kind'] == 'pick':
                    if p.get('custom_player'):
                        custom[p['player_id']] = p['custom_player']
                    slots[p['slot']].update(player_id=p['player_id'], player_name=p['player_name'])
                    if p.get('team'):
                        slots[p['slot']]['current_team'] = p['team']
                elif e['kind'] == 'clear_pick':
                    slots[p['slot']].update(player_id=None, player_name='')
                elif e['kind'] == 'slot_override':
                    slots[p['slot']].update(p['changes'])
                elif e['kind'] == 'settings':
                    settings.update(p)
            drafted = {s['player_id'] for s in slots.values() if s['player_id']}
            # Keep custom identities after undo so search/correction can select them again.
            for e in events:
                if e['kind'] == 'pick' and e['payload'].get('custom_player'):
                    custom[e['payload']['player_id']] = e['payload']['custom_player']
            current = next((s['slot'] for s in slots.values() if not s['keeper'] and not s['player_id']), None)
            active = [e for e in events if e['id'] not in disabled and e['kind'] in ('pick', 'clear_pick', 'slot_override')]
            return {'slots': list(slots.values()), 'drafted': sorted(drafted), 'current_slot': current,
                    'settings': settings, 'custom_players': list(custom.values()),
                    'revision': events[-1]['id'] if events else 0,
                    'undo_event': active[-1]['id'] if active else None, 'events': events}

    def append(self, kind, payload, revision=None):
        with self.lock:
            state = self.state()
            if revision is not None and revision != state['revision']:
                raise ValueError('Draft changed in another window. Refresh and retry.')
            self.validate(kind, payload, state)
            with self.db:
                self.db.execute('INSERT INTO events(timestamp,kind,payload) VALUES(?,?,?)',
                    (datetime.now(timezone.utc).isoformat(), kind, json.dumps(payload, ensure_ascii=False)))
                result = self.state()
                self.db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(result),))
            return result

    def validate(self, kind, p, state):
        if kind not in ('pick', 'clear_pick', 'slot_override', 'undo', 'settings'):
            raise ValueError('Unknown event type')
        if kind == 'undo':
            if p.get('event_id') != state['undo_event'] or state['undo_event'] is None:
                raise ValueError('Only the latest active draft action can be undone.')
            return
        if kind == 'settings':
            allowed = {'streaming', 'playoff_priority', 'risk', 'history_weight', 'punt', 'week_weights', 'future_keeper',
                       'draft_model', 'mc_trials', 'manager_overrides', 'draft_scenarios'}
            if set(p) - allowed:
                raise ValueError('Unknown setting')
            for key in ('playoff_priority', 'risk', 'history_weight', 'future_keeper'):
                if key in p and (not isinstance(p[key], (float, int)) or not 0 <= p[key] <= 1):
                    raise ValueError('Slider values must be between zero and one.')
            if 'streaming' in p and not isinstance(p['streaming'], bool):
                raise ValueError('Streaming must be boolean.')
            from .data import CATEGORIES
            if 'punt' in p and (not isinstance(p['punt'], list) or len(p['punt']) > 2 or len(set(p['punt'])) != len(p['punt']) or any(c not in CATEGORIES for c in p['punt'])):
                raise ValueError('Choose at most two distinct categories to punt.')
            if 'week_weights' in p and (not isinstance(p['week_weights'], list) or len(p['week_weights']) != 3 or any(not isinstance(v, (int, float)) or not 0 < v <= 5 for v in p['week_weights'])):
                raise ValueError('Provide three positive week weights, at most five each.')
            if 'draft_model' in p and p['draft_model'] not in ('auto', 'baseline', 'persona'):
                raise ValueError('Unknown draft prediction model')
            if 'mc_trials' in p and (type(p['mc_trials']) is not int or not 50 <= p['mc_trials'] <= 1000):
                raise ValueError('Monte Carlo trials must be an integer from 50 to 1000.')
            if 'manager_overrides' in p:
                overrides = p['manager_overrides']
                if not isinstance(overrides, dict) or set(overrides) - set(self.data.teams):
                    raise ValueError('Overrides must be mapped to known managers.')
                for manager, values in overrides.items():
                    if not isinstance(values, dict) or set(values) - {'adherence', 'young', 'rookie', 'guard', 'forward', 'center', 'targets'}:
                        raise ValueError('Unknown manager override field')
                    for key, value in values.items():
                        if key == 'targets':
                            if not isinstance(value, dict) or len(value) > 10 or any(pid not in self.data.players or not isinstance(b, (int, float)) or not -1 <= b <= 1 for pid, b in value.items()):
                                raise ValueError('Player targeting accepts up to ten known IDs with log-weight adjustments from -1 to 1.')
                        elif not isinstance(value, (int, float)) or not ((.35 <= value <= 4) if key == 'adherence' else (-.7 <= value <= .7)):
                            raise ValueError('Adherence must be .35–4; preference overrides must be -.7–.7.')
            if 'draft_scenarios' in p:
                scenarios = p['draft_scenarios']
                if not isinstance(scenarios, list) or len(scenarios) > 5:
                    raise ValueError('Provide at most five named asset scenarios.')
                from .draft_model import apply_scenario
                for scenario in scenarios:
                    apply_scenario(state, scenario, self.data)
                if len({s['name'] for s in scenarios}) != len(scenarios):
                    raise ValueError('Scenario names must be distinct.')
            return
        slot = p.get('slot')
        if not isinstance(slot, int) or not 1 <= slot <= 156:
            raise ValueError('Slot must be 1–156')
        s = state['slots'][slot - 1]
        if kind == 'slot_override':
            changes = p.get('changes', {})
            if not changes or set(changes) - {'current_team', 'keeper', 'keeper_player', 'player_name', 'confidence'}:
                raise ValueError('Invalid slot override')
            if 'current_team' in changes and changes['current_team'] not in self.data.teams:
                raise ValueError('Select a known manager')
            if 'keeper' in changes and not isinstance(changes['keeper'], bool):
                raise ValueError('Keeper flag must be boolean.')
            result_owner = changes.get('current_team', s['current_team'])
            result_keeper = changes.get('keeper', s['keeper'])
            result_name = changes.get('keeper_player', s['keeper_player'])
            if result_keeper:
                if s['player_id']:
                    raise ValueError('Clear the live pick before changing keeper status.')
                keeper = next((x for x in self.data.keepers if x['team'] == result_owner and x['player'] == result_name), None)
                if keeper is None:
                    raise ValueError('Keeper must belong to the selected manager.')
                if any(x['slot'] != slot and x['keeper'] and x.get('keeper_player') == result_name for x in state['slots']):
                    raise ValueError('That keeper already occupies another slot.')
                if int(keeper['forfeited_round']) != int(s['round']):
                    raise ValueError('Keeper cost round does not match this slot.')
            return
        if s['keeper']:
            raise ValueError('Keeper slots are not live picks. Resolve slot settings first.')
        if kind == 'clear_pick':
            if not s['player_id']:
                raise ValueError('This slot is already empty.')
            return
        player = self.data.players.get(p.get('player_id')) or next((x for x in state['custom_players'] if x['id'] == p.get('player_id')), None)
        if p.get('custom_player'):
            player = p['custom_player']
            if not player.get('name', '').strip() or not player.get('id', '').startswith('manual:') or player.get('id') != p.get('player_id'):
                raise ValueError('Invalid unlisted player')
            from .data import normalize
            if any(normalize(player['name']) == normalize(x['name']) for x in self.data.players.values()):
                raise ValueError('Player exists in projections; select the listed identity.')
            if any(normalize(player['name']) == normalize(x['name']) and player['id'] != x['id'] for x in state['custom_players']):
                raise ValueError('Unlisted player already exists; search for them.')
            player = {'id': player['id'], 'name': player['name'].strip()[:120], 'positions': [],
                      'projected': False, 'keeper': None, 'team': '', 'stats': [0] * 11, 'gp': 0,
                      'rank': 9999, 'adp': None, 'mpg': 0}
            p['custom_player'] = player
        if not player or player.get('keeper'):
            raise ValueError('Player is unknown or kept.')
        if p['player_id'] in state['drafted'] and s['player_id'] != p['player_id']:
            raise ValueError('Player already drafted.')
        owner = p.get('team') or s['current_team']
        if owner not in self.data.teams:
            raise ValueError('Pick ownership unresolved. Choose the manager explicitly.')
        p['team'] = owner
        p['player_name'] = player['name']

    def export(self):
        return {'format': 'fantasy-draft-v1', 'league_id': self.data.config['yahoo_league_id'],
                'season': self.data.config['season'], 'events': self.events()}

    def restore(self, backup):
        """Validate an entire imported history before atomically installing it in an empty DB."""
        if backup.get('format') != 'fantasy-draft-v1' or backup.get('league_id') != self.data.config['yahoo_league_id'] or backup.get('season') != self.data.config['season']:
            raise ValueError('Backup format, league, or season does not match.')
        with self.lock:
            if self.events():
                raise ValueError('Restore requires an empty draft database. Launch with --db a-new-file.sqlite3; your current draft will not be overwritten.')
            trial = Store(':memory:', self.data)
            try:
                for e in backup.get('events', []):
                    if e['id'] != trial.state()['revision'] + 1:
                        raise ValueError('Backup events are not sequential.')
                    trial.append(e['kind'], e['payload'])
                with self.db:
                    for e in backup.get('events', []):
                        self.db.execute('INSERT INTO events VALUES(?,?,?,?)', (e['id'], e['timestamp'], e['kind'], json.dumps(e['payload'])))
                    self.db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?)', (json.dumps(self.state()),))
            finally:
                trial.db.close()
            return self.state()
