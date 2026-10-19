"""Practice drafts are isolated databases. Reset archives, never clears a draft."""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .store import Store


class Sessions:
    def __init__(self, live_path, data):
        self.data = data
        self.lock = threading.RLock()
        self.live_path = str(live_path)
        self.manifest = None if self.live_path == ':memory:' else Path(live_path).with_suffix('.sessions.json')
        self.directory = None if self.manifest is None else self.manifest.parent / (Path(live_path).stem + '_mocks')
        self.entries = {'live': {'id': 'live', 'mode': 'live', 'name': 'Live draft', 'seed': 0}}
        self.stores = {'live': Store(live_path, data)}
        self.active_id = 'live'
        if self.manifest and self.manifest.exists():
            saved = json.loads(self.manifest.read_text())
            for entry in saved.get('mocks', []):
                # Only our generated IDs can become a database filename.
                if not entry['id'].startswith('mock-') or len(entry['id']) != 37 or any(c not in '0123456789abcdef' for c in entry['id'][5:]):
                    raise ValueError('Invalid saved mock session ID')
                self.entries[entry['id']] = entry
            self.active_id = saved.get('active_id', 'live')
            if self.active_id not in self.entries:
                self.active_id = 'live'
        self.store()  # Verify active saved database is readable at startup.

    def store(self):
        if self.active_id not in self.stores:
            path = ':memory:' if self.directory is None else self.directory / (self.active_id + '.sqlite3')
            if path != ':memory:' and not path.exists():
                raise ValueError('Saved mock database missing; refusing to silently recreate it.')
            self.stores[self.active_id] = Store(path, self.data)
        return self.stores[self.active_id]

    def info(self):
        return dict(self.entries[self.active_id])

    def list(self):
        return list(self.entries.values())

    def save(self):
        if self.manifest:
            temp = self.manifest.with_suffix('.tmp')
            temp.write_text(json.dumps({'active_id': self.active_id, 'mocks': [e for e in self.entries.values() if e['mode'] == 'mock']}, indent=2))
            temp.replace(self.manifest)

    def switch(self, sid):
        if sid not in self.entries:
            raise ValueError('Unknown draft session')
        previous = self.active_id
        self.active_id = sid
        try:
            self.store()
            self.save()
        except Exception:
            self.active_id = previous
            raise

    def new_mock(self):
        source = self.store().state()
        sid = 'mock-' + uuid.uuid4().hex
        path = ':memory:' if self.directory is None else self.directory / (sid + '.sqlite3')
        store = Store(path, self.data)
        # Copy setup and assumptions, not selections. Clear moved keeper assets
        # before reassigning them, so keeper uniqueness validation stays intact.
        originals = {int(s['overall_slot']): s for s in self.data.slots}
        for s in source['slots']:
            original = originals[s['slot']]
            if original['keeper_forfeit_flag'] == 'true' and not s['keeper']:
                store.append('slot_override', {'slot': s['slot'], 'changes': {'keeper': False, 'keeper_player': '', 'player_name': ''}})
        for s in source['slots']:
            original = originals[s['slot']]
            changes = {}
            if s['current_team'] != original['current_team'] and s['current_team']:
                changes['current_team'] = s['current_team']
            if s['keeper'] and (original['keeper_forfeit_flag'] != 'true' or original['keeper_player'] != s['keeper_player']):
                changes.update(keeper=True, keeper_player=s['keeper_player'], player_name=s['keeper_player'])
            if changes:
                changes['confidence'] = 'user_confirmed'
                store.append('slot_override', {'slot': s['slot'], 'changes': changes})
        if source['settings']:
            store.append('settings', dict(source['settings']))
        self.stores[sid] = store
        self.entries[sid] = {'id': sid, 'mode': 'mock', 'name': 'Mock ' + str(len(self.entries)),
                             'created_at': datetime.now(timezone.utc).isoformat(),
                             'seed': uuid.uuid4().int % (2 ** 32)}
        self.active_id = sid
        self.save()
        return self.info()

    def close(self):
        for store in self.stores.values():
            store.db.close()
