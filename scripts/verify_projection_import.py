#!/usr/bin/env python3
"""Independent verification of a converted Hashtag CSV.

Re-derives the table from the HTML with a streaming HTMLParser (a different code
path than the importer's regex), then compares every field to the produced CSV and
round-trips the file through the app's own Data loader.

    python3 scripts/verify_projection_import.py --html X.html --csv Y.csv
"""
import argparse
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import read_csv


class TableRows(HTMLParser):
    """Collect <tr> rows of the FIRST <table> as (cell_texts, [(href,text)])."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.table_depth = 0; self.in_table = False; self.done = False
        self.rows = []; self.row = None; self.cell = None; self.cell_anchors = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and not self.in_table and not self.done:
            self.in_table = True; return
        if not self.in_table: return
        if tag == 'tr': self.row = []; self.cell_anchors = []
        elif tag == 'td' and self.row is not None: self.cell = []
        elif tag == 'a' and self.cell is not None and attrs.get('href'):
            self.cell.append(('ANCHOR', attrs['href']))

    def handle_endtag(self, tag):
        if tag == 'table' and self.in_table: self.in_table = False; self.done = True; return
        if not self.in_table and not self.done: return
        if tag == 'td' and self.cell is not None:
            self.row.append((''.join(t for k, t in self.cell if k == 'T'), [a for k, a in self.cell if k == 'ANCHOR']))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row = None

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(('T', data))


def derive(html_path):
    parser = TableRows(); parser.feed(Path(html_path).read_text(encoding='utf-8', errors='replace'))
    # The streaming parser cannot split the two <a> texts cleanly; take full names from a
    # targeted regex over the same document (independent of the importer's row regex).
    raw = Path(html_path).read_text(encoding='utf-8', errors='replace')
    names = {}
    anchor_re = re.compile(r'<a\b([^>]*?)href="/(\d+)/player"([^>]*)>([^<]+)</a>')
    for m in anchor_re.finditer(raw):
        attrs = m.group(1) + m.group(3)
        # the full-name anchor is styled d-none d-sm-inline; the short one is d-inline d-sm-none
        if 'd-sm-inline' in attrs and 'd-sm-none' not in attrs:
            names.setdefault(m.group(2), m.group(4).strip())
    rows = {}
    for row in parser.rows:
        if len(row) != 17: continue
        texts = [re.sub(r'\s+', ' ', t).strip() for t, _ in row]
        pid = None
        for _, hrefs in row:
            for h in hrefs:
                m = re.search(r'/(\d+)/player', h)
                if m: pid = m.group(1); break
            if pid: break
        if not pid: continue
        fg = re.match(r'^([0-9.]+)\s*\(\s*([0-9.]+)/([0-9.]+)\s*\)$', texts[7])
        ft = re.match(r'^([0-9.]+)\s*\(\s*([0-9.]+)/([0-9.]+)\s*\)$', texts[8])
        rows[pid] = {'rank': str(int(re.match(r'(\d+)', texts[0]).group(1))), 'player': names.get(pid, ''),
                     'adp': texts[2], 'positions': texts[3].replace(' ', ''), 'nba_team': texts[4],
                     'projected_gp': texts[5], 'mpg': texts[6], 'fg_pct': fg.group(1), 'fgm_pg': fg.group(2),
                     'fga_pg': fg.group(3), 'ft_pct': ft.group(1), 'ftm_pg': ft.group(2), 'fta_pg': ft.group(3),
                     'three_pm': texts[9], 'pts': texts[10], 'reb': texts[11], 'ast': texts[12],
                     'stl': texts[13], 'blk': texts[14], 'to': texts[15], 'hashtag_total': texts[16]}
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--csv', required=True)
    args = ap.parse_args()
    derived = derive(args.html)
    csv_rows = {r['player_id']: r for r in read_csv(args.csv)}
    problems = []
    if set(derived) != set(csv_rows):
        problems.append(f'ID mismatch: html={len(derived)} csv={len(csv_rows)}')
    for pid, d in derived.items():
        c = csv_rows.get(pid)
        if not c: continue
        for col, val in d.items():
            if col == 'player':
                same = c['player'] == val
            elif col in ('fg_pct', 'ft_pct'):
                same = abs(float(c[col]) - float(val)) < 1e-9
            else:
                same = str(c[col]) == str(val)
            if not same:
                problems.append(f"{d['player']} [{pid}] {col}: html={val!r} csv={c[col]!r}")
    print(f'independent re-derivation compared {len(derived)} players; mismatches: {len(problems)}')
    for p in problems[:20]: print('  ', p)

    # app-level round trip
    from app.data import Data
    from app.draft_model import uncertainty_barrier
    from app.engine import Engine
    from app.store import Store
    import tempfile, shutil, os
    tmp = tempfile.mkdtemp()
    try:
        shutil.copy(args.csv, Path(tmp) / 'hashtag_basketball_2026_27_projections_430.csv')
        for name in ('league_config.json', 'keepers.csv', 'draft_slots.csv', 'keeper_cost_exceptions.csv',
                     'playoff_team_weekly_games.csv'):
            shutil.copy(Path('.').resolve() / name, Path(tmp) / name)
        shutil.copytree(Path('.').resolve() / 'data', Path(tmp) / 'data', dirs_exist_ok=True)
        d = Data(root=tmp)
        engine = Engine(d)
        store = Store(':memory:', d)
        state = store.state()
        barrier = uncertainty_barrier(state, d)
        print('app loader: players', len(d.players), '| keepers', sum(1 for p in d.players.values() if p['keeper']),
              '| assets/team', sorted({sum(1 for s in state["slots"] if s["current_team"] == t) for t in d.teams}),
              '| barrier', barrier)
        print('keepers matched:', sorted(p['name'] for p in engine.rosters(state)['Oscar']))
        for name in ("Kawhi Leonard", 'Kristaps Porzingis', 'Brandin Podziemski'):
            p = next(p for p in d.players.values() if p['name'] == name)
            print(f"  {name}: rank {p['rank']} gp {p['gp']} mpg {p['mpg']} adp {p['adp']} market_adp {p['market_adp']}")
        store.db.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        raise SystemExit('Verification FAILED')
    print('Verification PASSED')


if __name__ == '__main__':
    main()
