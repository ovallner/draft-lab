#!/usr/bin/env python3
"""Pre-build NBA biographical cache; no draft-time network dependency.

The nba_api static registry resolves NBA IDs only. Birthdates, draft years and
season records are validated against the official NBA public player-page JSON.
Current age, team, positions and scoring statistics are deliberately not imported.
"""
import argparse
import ast
import hashlib
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import ROOT, read_csv, normalize

REGISTRY = 'https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/stats/library/data.py'
REGISTRY_ALIASES = {'Jabari Smith': 'Jabari Smith Jr.', 'Jaren Jackson': 'Jaren Jackson Jr.',
                    'Kevin Porter': 'Kevin Porter Jr.', 'Nicolas Claxton': 'Nic Claxton',
                    'Ron Holland II': 'Ronald Holland II'}


def name_key(name):
    name = re.sub(r'\s+(Jr\.?|II|III|IV)$', '', name, flags=re.I)
    key = normalize(name)
    return {'alexsarr': 'alexandresarr', 'nicolasclaxton': 'nicclaxton', 'ronholland': 'ronaldholland'}.get(key, key)


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def parse_bio(raw, expected_id):
    html = raw.decode('utf-8')
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise ValueError('Missing official page data')
    info = json.loads(match.group(1))['props']['pageProps']['player']['info']
    if str(info['PERSON_ID']) != str(expected_id):
        raise ValueError('NBA player ID differs from requested ID')
    seasons = sorted({int(s[1:]) for s in info.get('SEASONS', []) if s.startswith('2') and len(s) == 5})
    return {'nba_id': str(info['PERSON_ID']), 'name': info['DISPLAY_FIRST_LAST'],
            'birthdate': info['BIRTHDATE'][:10], 'draft_year': info['DRAFT_YEAR'],
            'first_regular_season': seasons[0] if seasons else None,
            'regular_seasons': seasons, 'from_year': info['FROM_YEAR'],
            'info_sha256': hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'player_bios.json')
    args = parser.parse_args()
    raw = get(REGISTRY)
    tree = ast.parse(raw.decode())
    registry = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'players' for t in n.targets))
    names = {}
    exact = {}
    for row in registry:
        names.setdefault(name_key(row[3]), []).append(row)
        exact.setdefault(normalize(row[3]), []).append(row)
    wanted = {r['player'] for r in read_csv(ROOT / 'manager_persona_2025_adp_handoff' / 'rotowire_2025_adp.csv') if r['yahoo_adp_2025']}
    wanted.update(r['player'] for r in read_csv(ROOT / 'manager_persona_2025_adp_handoff' / 'draft_2025_results.csv'))
    wanted.update(r['player'] for r in read_csv(ROOT / 'hashtag_basketball_2026_27_projections_430.csv'))
    previous = json.loads(args.output.read_text()) if args.output.exists() else {'players': [], 'errors': []}
    cached = {p['nba_id']: p for p in previous['players']}
    errors, jobs = [], {}
    for name in sorted(wanted):
        canonical = REGISTRY_ALIASES.get(name, name)
        matches = exact.get(normalize(canonical), []) or names.get(name_key(canonical), [])
        if len(matches) != 1:
            errors.append({'name': name, 'error': 'Registry match missing/ambiguous', 'ids': [str(r[0]) for r in matches]})
            continue
        pid = str(matches[0][0])
        if pid not in cached:
            slug = re.sub(r'[^a-z0-9]+', '-', normalize_slug(matches[0][3])).strip('-')
            jobs[pid] = ('https://www.nba.com/player/' + pid + '/' + slug, name)
    def fetch(pid, job):
        url, name = job
        bio = parse_bio(get(url), pid)
        if name_key(bio['name']) != name_key(name):
            raise ValueError('Official player name differs from registry/source')
        bio.update(source=url, retrieved_at=datetime.now(timezone.utc).isoformat())
        return bio
    with ThreadPoolExecutor(max_workers=max(1, min(4, args.workers))) as pool:
        futures = {pool.submit(fetch, pid, job): (pid, job) for pid, job in jobs.items()}
        for future in as_completed(futures):
            pid, job = futures[future]
            try:
                cached[pid] = future.result()
            except Exception as exc:
                errors.append({'name': job[1], 'nba_id': pid, 'source': job[0], 'error': str(exc)})
    output = {'metadata': {'source': 'Official NBA player-page CommonPlayerInfo JSON',
              'registry_source': REGISTRY, 'registry_sha256': hashlib.sha256(raw).hexdigest(),
              'explicit_registry_aliases': REGISTRY_ALIASES,
              'historical_age_date': '2025-10-01', 'current_age_date': '2026-10-01',
              'rookie_method': 'First regular-season entry in official NBA SEASONS; no inference from draft year alone. Missing debut records remain unknown.',
              'limitations': 'Retrieved biographies are not archived 2025 pages. Only stable birth/draft facts and season-index history are used; no current scoring, team, age or position imported.'},
              'players': sorted(cached.values(), key=lambda p: p['nba_id']), 'errors': errors}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix('.tmp')
    temp.write_text(json.dumps(output, indent=2)); temp.replace(args.output)
    print(f'Saved {len(cached)} verified biographies; {len(errors)} unresolved requests/matches.', flush=True)


def normalize_slug(name):
    import unicodedata
    return unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()


if __name__ == '__main__':
    main()
