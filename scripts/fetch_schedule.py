#!/usr/bin/env python3
"""Explicit pre-draft refresh only. Runtime draft use never requires the network."""
import argparse
import csv
import hashlib
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import ROOT, TEAMS, ALIASES, read_csv

URL = 'https://fixturedownload.com/feed/json/nba-2026'


def normalize_schedule(rows):
    games = []
    counts = Counter()
    for r in rows:
        if r['HomeTeam'] not in TEAMS or r['AwayTeam'] not in TEAMS:
            # Known NBA Cup placeholders are not invented fixtures.
            if 'To be announced' in (r['HomeTeam'], r['AwayTeam']):
                continue
            raise ValueError('Unknown team in source: ' + repr(r))
        dt = datetime.fromisoformat(r['DateUtc'].replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('Source timestamp lacks timezone')
        et = dt.astimezone(ZoneInfo('America/New_York'))
        game = {'id': 'fixture:' + str(r['MatchNumber']), 'date': et.date().isoformat(),
                'tipoff_eastern': et.isoformat(), 'tipoff_utc': dt.astimezone(timezone.utc).isoformat(),
                'home': TEAMS[r['HomeTeam']], 'away': TEAMS[r['AwayTeam']]}
        games.append(game)
        if date(2027, 3, 1) <= et.date() <= date(2027, 3, 21):
            for team in (game['home'], game['away']):
                counts[team, (et.day - 1) // 7] += 1
    if len({g['id'] for g in games}) != len(games) or len({(g['date'], g['home'], g['away']) for g in games}) != len(games):
        raise ValueError('Duplicate fixtures')
    mismatches = []
    for r in read_csv(ROOT / 'playoff_team_weekly_games.csv'):
        team = ALIASES.get(r['team_abbrev'], r['team_abbrev'])
        actual = [counts[team, w] for w in range(3)]
        expected = [int(r[c]) for c in ('w18_mar01_07', 'w19_mar08_14', 'w20_mar15_21')]
        if actual != expected:
            mismatches.append({'team': team, 'expected': expected, 'actual': actual})
    if mismatches:
        raise ValueError('Weekly schedule reconciliation failed: ' + json.dumps(mismatches))
    return sorted(games, key=lambda g: g['tipoff_utc']), counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, help='Use a locally downloaded JSON feed instead of internet')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'nba_schedule.json')
    args = parser.parse_args()
    if args.input:
        raw = args.input.read_bytes()
    else:
        request = urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0 FantasyDraftAssistant/1.0'})
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
    rows = json.loads(raw)
    games, counts = normalize_schedule(rows)
    now = datetime.now(timezone.utc).isoformat()
    output = {'metadata': {'source': URL, 'retrieved_at': now, 'sha256': hashlib.sha256(raw).hexdigest(),
        'weekly_counts_match': True, 'official_fixture_crosscheck': False,
        'official_reference': 'https://pr.nba.com/2026-27-nba-regular-season-schedule/',
        'playoff_games': sum(counts.values()) // 2, 'known_full_season_games': len(games),
        'notes': 'Third-party daily fixtures reconciled to user-supplied Hashtag weekly counts. Official per-fixture cross-check pending. NBA Cup placeholders excluded.'}, 'games': games}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve source independently and replace only after all validation succeeds.
    (args.output.parent / 'nba_schedule_source.json').write_bytes(raw)
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(output, indent=2))
    temp.replace(args.output)
    print(f"Saved {len(games)} known fixtures; {output['metadata']['playoff_games']} playoff games; all 90 weekly team counts match.")


if __name__ == '__main__':
    main()
