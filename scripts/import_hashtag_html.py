#!/usr/bin/env python3
"""Import a saved Hashtag projections HTML page into the canonical CSV schema.

Read-only with respect to live state; writes a CSV only with --write. The parser is
strict and fails closed: any row that cannot be parsed into the existing 22-column
schema raises instead of silently emitting a placeholder.

    # dry run + validation summary
    python3 scripts/import_hashtag_html.py --html ~/Downloads/hashtag_10-15-26.html
    # write the converted snapshot
    python3 scripts/import_hashtag_html.py --html ... --out data/projections/incoming/...csv --write
"""
import argparse
import csv
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import read_csv

COLUMNS = ['rank','player_id','player','adp','positions','nba_team','projected_gp','mpg','fg_pct','fgm_pg','fga_pg',
           'ft_pct','ftm_pg','fta_pg','three_pm','pts','reb','ast','stl','blk','to','hashtag_total']
SOURCE_HEADERS = ['R#','PLAYER','ADP','POS','TEAM','GP','MPG','FG%','FT%','3PM','PTS','TREB','AST','STL','BLK','TO','TOTAL']
STAT_COLUMNS = ['three_pm','pts','reb','ast','stl','blk','to']


def _text(fragment):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment)).strip()


def _pct_pair(cell, label, player):
    match = re.match(r'^([0-9]*\.?[0-9]+)\s*\(\s*([0-9]*\.?[0-9]+)\s*/\s*([0-9]*\.?[0-9]+)\s*\)$', cell)
    if not match:
        raise ValueError(f'{player}: unparseable {label} cell {cell!r}')
    return match.groups()


def parse_html(path):
    """Return (rows, source_header) where rows are canonical-schema dicts sorted by rank."""
    html = Path(path).read_text(encoding='utf-8', errors='replace')
    start = html.find('<table')
    end = html.find('</table>', start)
    if start < 0 or end < 0:
        raise ValueError('No projections table found in the supplied HTML.')
    table = html[start:end]
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.S):
        link = re.search(r'href="/(\d+)/player"[^>]*>([^<]+)</a>', tr)
        if not link:
            continue
        player_id, player = link.group(1), link.group(2).strip()
        cells = [_text(c) for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(cells) != len(SOURCE_HEADERS):
            raise ValueError(f'{player}: expected {len(SOURCE_HEADERS)} cells, found {len(cells)}')
        rank_match = re.match(r'^(\d+)', cells[0])
        if not rank_match:
            raise ValueError(f'{player}: unparseable rank cell {cells[0]!r}')
        fg_pct, fgm, fga = _pct_pair(cells[7], 'FG%', player)
        ft_pct, ftm, fta = _pct_pair(cells[8], 'FT%', player)
        positions = cells[3].replace(' ', '')
        if not positions:
            raise ValueError(f'{player}: missing positions')
        row = {'rank': str(int(rank_match.group(1))), 'player_id': player_id, 'player': player,
               'adp': cells[2].strip(), 'positions': positions, 'nba_team': cells[4],
               'projected_gp': cells[5], 'mpg': cells[6], 'fg_pct': fg_pct, 'fgm_pg': fgm, 'fga_pg': fga,
               'ft_pct': ft_pct, 'ftm_pg': ftm, 'fta_pg': fta,
               'three_pm': cells[9], 'pts': cells[10], 'reb': cells[11], 'ast': cells[12],
               'stl': cells[13], 'blk': cells[14], 'to': cells[15], 'hashtag_total': cells[16]}
        rows.append(row)
    if not rows:
        raise ValueError('No player rows parsed.')
    if len({r['player_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate player IDs parsed.')
    rows.sort(key=lambda r: (int(r['rank']), r['player_id']))
    return rows, SOURCE_HEADERS


def validate(rows, template_path):
    """Independent structural + numeric validation against the current template."""
    template = {r['player_id']: r for r in read_csv(template_path)}
    ids = {r['player_id'] for r in rows}
    added = sorted(ids - set(template)); removed = sorted(set(template) - ids)
    ranks = sorted(int(r['rank']) for r in rows)
    problems = []
    if added or removed:
        problems.append(f'ID set differs: added={added} removed={removed}')
    if ranks != list(range(1, len(rows) + 1)):
        problems.append('ranks are not a permutation of 1..N')
    for r in rows:
        gp = float(r['projected_gp']); mpg = float(r['mpg'])
        if not 0 <= gp <= 82: problems.append(f"{r['player']}: GP {gp}")
        if not 0 <= mpg <= 48.1: problems.append(f"{r['player']}: MPG {mpg}")
        fgm, fga = float(r['fgm_pg']), float(r['fga_pg'])
        ftm, fta = float(r['ftm_pg']), float(r['fta_pg'])
        if fga > 0 and abs(fgm / fga - float(r['fg_pct'])) > 0.05 / fga + 0.05 * fgm / fga ** 2 + 0.0006:
            problems.append(f"{r['player']}: FG% inconsistent with makes/attempts")
        if fta > 0 and abs(ftm / fta - float(r['ft_pct'])) > 0.05 / fta + 0.05 * ftm / fta ** 2 + 0.0006:
            problems.append(f"{r['player']}: FT% inconsistent with makes/attempts")
        for col in STAT_COLUMNS:
            if float(r[col]) < 0: problems.append(f"{r['player']}: negative {col}")
        if r['positions'] != template.get(r['player_id'], {}).get('positions', r['positions']):
            problems.append(f"{r['player']}: positions changed unexpectedly")
    return template, added, removed, problems


def changed_fields(rows, template):
    """Field-level diff vs the template for the import report."""
    counts = {c: 0 for c in COLUMNS}
    changed_players = []
    for r in rows:
        o = template[r['player_id']]
        fields = []
        for col in COLUMNS:
            if col in ('fg_pct', 'ft_pct'):
                same = abs(float(r[col]) - float(o[col])) < 1e-9
            else:
                same = str(r[col]) == str(o[col])
            if not same:
                counts[col] += 1; fields.append(col)
        if fields:
            changed_players.append((r['player'], fields))
    return counts, changed_players


def to_csv_bytes(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator='\r\n', quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return b'\xef\xbb\xbf' + buffer.getvalue().encode('utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--template', default='hashtag_basketball_2026_27_projections_430.csv')
    ap.add_argument('--out')
    ap.add_argument('--write', action='store_true')
    args = ap.parse_args()

    rows, header = parse_html(args.html)
    template, added, removed, problems = validate(rows, args.template)
    counts, changed_players = changed_fields(rows, template)
    print(f'parsed {len(rows)} players | unique IDs {len({r["player_id"] for r in rows})}')
    print(f'added {len(added)}, removed {len(removed)} | validation problems: {len(problems)}')
    for p in problems[:20]:
        print('  PROBLEM:', p)
    print('field changes vs template:', {k: v for k, v in counts.items() if v})
    substantive = [(n, [c for c in f if c not in ('rank', 'adp', 'hashtag_total')]) for n, f in changed_players]
    substantive = [(n, f) for n, f in substantive if f]
    print('players with non-rank/adp/total changes:', substantive)
    if problems:
        raise SystemExit('Refusing to write: validation problems found.')
    if args.write:
        if not args.out:
            raise SystemExit('--write requires --out')
        data = to_csv_bytes(rows)
        Path(args.out).write_bytes(data)
        # idempotence: re-parsing the file we just wrote must round-trip
        reread = {r['player_id']: r for r in read_csv(args.out)}
        if len(reread) != len(rows):
            raise SystemExit('Round-trip check failed (row count).')
        print('wrote', args.out, f'({len(data)} bytes)')
    else:
        print('dry run: no file written (pass --write --out PATH)')


if __name__ == '__main__':
    main()
