"""Read-only source ingestion. Provider IDs are not Yahoo or NBA IDs."""
import csv
import hashlib
import json
import unicodedata
from datetime import date
from pathlib import Path
from .market import apply_market_estimates

ROOT = Path(__file__).resolve().parent.parent
TEAMS = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
    'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GS', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
    'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL',
    'Memphis Grizzlies': 'MEM', 'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL',
    'Minnesota Timberwolves': 'MIN', 'New Orleans Pelicans': 'NO', 'New York Knicks': 'NY',
    'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI',
    'Phoenix Suns': 'PHO', 'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC',
    'San Antonio Spurs': 'SA', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA',
    'Washington Wizards': 'WAS',
}
ALIASES = {'NOP': 'NO', 'PHX': 'PHO', 'GSW': 'GS', 'SAS': 'SA', 'NYK': 'NY'}
STATS = ['fgm_pg', 'fga_pg', 'ftm_pg', 'fta_pg', 'three_pm', 'pts', 'reb', 'ast', 'stl', 'blk', 'to']
CATEGORIES = ['FG%', 'FT%', '3PM', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'TO']


def normalize(name):
    text = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return ''.join(c for c in text if c.isalnum())


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


class Data:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.config = json.loads((self.root / 'league_config.json').read_text())
        self.keeper_rows = read_csv(self.root / 'keepers.csv')
        # A keeper row may be retained for provenance but marked not kept when the
        # league's completed board shows it was never kept (e.g. Yahoo 2026-10-19).
        self.keepers = [k for k in self.keeper_rows
                        if not (k.get('status') or '').strip().startswith('not_kept')]
        self.slots = read_csv(self.root / 'draft_slots.csv')
        self.exceptions = read_csv(self.root / 'keeper_cost_exceptions.csv')
        self.players = {}
        for row in read_csv(self.root / 'hashtag_basketball_2026_27_projections_430.csv'):
            pid = 'ht:' + row['player_id']
            if pid in self.players:
                raise ValueError('Duplicate projection ID: ' + pid)
            p = {'id': pid, 'name': row['player'], 'team': ALIASES.get(row['nba_team'], row['nba_team']),
                 'positions': row['positions'].split(','), 'rank': int(row['rank']),
                 'adp': float(row['adp']) if row['adp'] else None,
                 'gp': float(row['projected_gp']), 'mpg': float(row['mpg']),
                 'stats': [float(row[c]) for c in STATS], 'projected': True, 'keeper': None}
            if any(v < 0 for v in p['stats']) or not 0 <= p['gp'] <= 82:
                raise ValueError('Invalid projection for ' + p['name'])
            self.players[pid] = p
        names = {normalize(p['name']): p for p in self.players.values()}
        apply_market_estimates(list(self.players.values()))
        names['alexsarr'] = names.get('alexandresarr')
        counts = {}
        seen = set()
        for k in self.keepers:
            counts[k['team']] = counts.get(k['team'], 0) + 1
            p = names.get(normalize(k['player']))
            if p is None:
                raise ValueError('Keeper identity not matched: ' + k['player'])
            if p['id'] in seen:
                raise ValueError('Duplicate keeper: ' + k['player'])
            seen.add(p['id'])
            p['keeper'] = k['team']
            k['player_id'] = p['id']
        if len(counts) != 12 or any(not 1 <= n <= 3 for n in counts.values()):
            raise ValueError('Recommendations locked: validate keepers for all 12 teams (1–3 each).')
        if [int(s['overall_slot']) for s in self.slots] != list(range(1, 157)):
            raise ValueError('Draft slots must cover 1–156 in order.')
        self.teams = [s['original_team'] for s in self.slots[:12]]
        self.weekly = {}
        for r in read_csv(self.root / 'playoff_team_weekly_games.csv'):
            team = ALIASES.get(r['team_abbrev'], r['team_abbrev'])
            self.weekly[team] = [int(r[c]) for c in ('w18_mar01_07', 'w19_mar08_14', 'w20_mar15_21')]
        self.games = []
        self.schedule_metadata = None
        schedule_path = self.root / 'data' / 'nba_schedule.json'
        if schedule_path.exists():
            schedule = json.loads(schedule_path.read_text())
            self.games = schedule['games']
            self.schedule_metadata = schedule['metadata']
        # The active projection snapshot's hash is computed, never hardcoded, so the
        # app always reports the file it actually loaded. The capture date is not
        # embedded in the CSV; it comes from an activation-provenance sidecar written
        # by the projection-update workflow, so it cannot silently go stale.
        try:
            self.projection_sha256 = hashlib.sha256(
                (self.root / 'hashtag_basketball_2026_27_projections_430.csv').read_bytes()).hexdigest()
        except OSError:
            self.projection_sha256 = None
        self.projection_provenance = {}
        provenance_path = self.root / 'projection_provenance.json'
        if provenance_path.exists():
            try:
                self.projection_provenance = json.loads(provenance_path.read_text())
            except (OSError, ValueError):
                self.projection_provenance = {}
        source_date = self.projection_provenance.get('source_date')
        activated = self.projection_provenance.get('activated')
        if source_date and activated:
            self.projection_source_date = f'{source_date} export, activated {activated}'
        else:
            self.projection_source_date = 'capture date not embedded in CSV'
        self.warnings = [
            'Projection snapshot: supplied Hashtag export (' + (source_date or 'date not embedded in CSV') + '). '
            'Confirm currency with the exporter. The active file hash is shown in Data quality.',
            'Hashtag positions are provisional Yahoo eligibility. Verify in the draft room.',
            'Historical results inform optional opponent preferences, not fixed future category strength.',
            'Alex Sarr matched explicitly to Alexandre Sarr.',
        ]
        if not self.games:
            self.warnings.append('Daily schedule missing: weekly-count fallback; no lineup congestion or B2B calculations.')
        self.warnings.append(f"{sum(p['adp'] is None for p in self.players.values())} players lack ADP; availability estimates are uncertain.")
        self.history = {}
        history_path = self.root / 'data' / 'historical_categories.csv'
        if history_path.exists():
            for r in read_csv(history_path):
                self.history[r['manager']] = [float(r[c]) for c in CATEGORIES]
        self.history_package = None
        # Prefer the three-season package; fall back to the single-season one.
        for candidate in ('data/history3/profiles.json', 'data/history/profiles.json'):
            path = self.root / candidate
            if path.exists():
                self.history_package = json.loads(path.read_text())
                self.history_package['source_file'] = candidate
                break
        bio_path = self.root / 'data' / 'player_bios.json'
        self.bio_metadata = None
        if bio_path.exists():
            from .history import name_key, bio_features
            bios = json.loads(bio_path.read_text())
            lookup = {name_key(p['name']): p for p in bios['players']}
            self.bio_metadata = bios['metadata']
            for p in self.players.values():
                p['bio'] = bio_features(lookup.get(name_key(p['name'])), date(2026, 10, 1))

    def metadata(self):
        return {'players': len(self.players), 'keepers': len(self.keepers), 'warnings': self.warnings,
                'schedule': self.schedule_metadata, 'exceptions': self.exceptions,
                'projection_file': 'hashtag_basketball_2026_27_projections_430.csv',
                'projection_source_date': self.projection_source_date,
                'projection_source_file': self.projection_provenance.get('source_file'),
                'projection_sha256': self.projection_sha256,
                'projection_sha256_short': (self.projection_sha256 or '')[:12],
                'categories': CATEGORIES, 'teams': self.teams, 'config': self.config,
                'historical_profiles': self.history_package, 'bio_metadata': self.bio_metadata}
