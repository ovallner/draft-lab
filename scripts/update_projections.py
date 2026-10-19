#!/usr/bin/env python3
"""Lightweight projection-update workflow (diff + optional install).

Never changes the engine. Because `app/benchmark_jobs.INPUT_FILES` hashes the
projection CSV, any change automatically invalidates resumes of older, now-stale
simulations — cached results are never silently reused.

Usage:
    # 1) Diff a new Hashtag export against the current one (no changes made):
    python3 scripts/update_projections.py --new ~/Downloads/hashtag_new.csv

    # 2) Install it (archives the current file first), then rerun when convenient:
    python3 scripts/update_projections.py --new ~/Downloads/hashtag_new.csv --activate

Archived baselines live in data/projections/archive/.
"""
import argparse
import hashlib
import json
import re
import shutil
import statistics as st
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.data import read_csv

CANONICAL = Path('hashtag_basketball_2026_27_projections_430.csv')
ARCHIVE = Path('data/projections/archive')
CATS = ['FG%', 'FT%', '3PM', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'TO']
REQUIRED = ['player_id', 'player', 'rank', 'adp', 'positions', 'nba_team', 'projected_gp', 'mpg',
            'fg_pct', 'fgm_pg', 'fga_pg', 'ft_pct', 'ftm_pg', 'fta_pg', 'three_pm', 'pts', 'reb', 'ast', 'stl', 'blk', 'to']


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    rows = read_csv(path)
    missing = [c for c in REQUIRED if rows and c not in rows[0]]
    if missing:
        raise ValueError('Projection file missing columns: ' + ', '.join(missing))
    out = {}
    for r in rows:
        pid = 'ht:' + r['player_id']   # match app.data player ids (ht:<id>)
        if pid in out:
            raise ValueError('Duplicate player_id in file: ' + pid)
        out[pid] = r
    return out


def value_index(rows):
    """Per-player mean category z and per-category z, mirroring Engine.raw/z over the
    top-156 by rank (FG%/FT% as impact vs league reference)."""
    ordered = sorted(rows, key=lambda pid: int(rows[pid]['rank']))[:156]
    fga = sum(float(rows[pid]['fga_pg']) for pid in ordered) or 1
    fta = sum(float(rows[pid]['fta_pg']) for pid in ordered) or 1
    fg = sum(float(rows[pid]['fgm_pg']) for pid in ordered) / fga
    ft = sum(float(rows[pid]['ftm_pg']) for pid in ordered) / fta

    def raw(r):
        return [float(r['fgm_pg']) - fg * float(r['fga_pg']), float(r['ftm_pg']) - ft * float(r['fta_pg']),
                float(r['three_pm']), float(r['pts']), float(r['reb']), float(r['ast']),
                float(r['stl']), float(r['blk']), -float(r['to'])]

    raws = {pid: raw(r) for pid, r in rows.items()}
    means = [st.mean(raws[p][j] for p in ordered) for j in range(9)]
    devs = [max(.01, st.pstdev(raws[p][j] for p in ordered)) for j in range(9)]
    z = {pid: [(raws[pid][j] - means[j]) / devs[j] for j in range(9)] for pid in rows}
    return {pid: st.mean(z[pid]) for pid in rows}, z


def focus_ids(lab_path):
    ids = set()
    if Path(lab_path).exists():
        lab = json.loads(Path(lab_path).read_text())
        ids |= {c['id'] for c in lab.get('candidates', [])}
        ids |= {c['id'] for c in lab.get('candidates', []) if c.get('id')}
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--new', required=True)
    ap.add_argument('--baseline', default=str(CANONICAL))
    ap.add_argument('--activate', action='store_true')
    ap.add_argument('--html', default=None, help='optional source HTML file, recorded for provenance')
    ap.add_argument('--lab', default='local/pick6_lab_deep.json')
    ap.add_argument('--material-value', type=float, default=0.15)
    ap.add_argument('--material-rank', type=int, default=5)
    ap.add_argument('--material-gp', type=int, default=5)
    ap.add_argument('--out', default='PROJECTION_UPDATE.md')
    ap.add_argument('--json', default='local/projection_update.json')
    args = ap.parse_args()

    if not Path(args.new).exists():
        raise SystemExit('New export not found: ' + args.new)
    if Path(args.new).resolve() == Path(args.baseline).resolve():
        raise SystemExit('--new and --baseline are the same file.')

    old = load(args.baseline); new = load(args.new)
    old_val, old_z = value_index(old); new_val, new_z = value_index(new)
    old_ids, new_ids = set(old), set(new)
    added, removed = sorted(new_ids - old_ids), sorted(old_ids - new_ids)

    keepers = set()
    if Path('keepers.csv').exists():
        name_to_id = {r['player'].lower(): pid for pid, r in new.items()}
        for k in read_csv(Path('keepers.csv')):
            pid = name_to_id.get(k['player'].lower())
            if pid:
                keepers.add(pid)
    lab = focus_ids(args.lab)

    def row_diff(pid):
        o, n = old.get(pid), new.get(pid)
        if o is None or n is None:
            return None
        d = {'id': pid, 'name': n['player'], 'rank_old': int(o['rank']), 'rank_new': int(n['rank']),
             'd_rank': int(n['rank']) - int(o['rank']),
             'gp_old': float(o['projected_gp']), 'gp_new': float(n['projected_gp']),
             'd_gp': float(n['projected_gp']) - float(o['projected_gp']),
             'mpg_old': float(o['mpg']), 'mpg_new': float(n['mpg']), 'd_mpg': float(n['mpg']) - float(o['mpg']),
             'val_old': old_val.get(pid), 'val_new': new_val.get(pid),
             'd_val': (new_val.get(pid, 0) - old_val.get(pid, 0)) if pid in old_val and pid in new_val else None,
             'd_cat': {CATS[j]: (new_z[pid][j] - old_z[pid][j]) for j in range(9)}}
        d['material'] = (abs(d['d_val'] or 0) >= args.material_value or abs(d['d_rank']) >= args.material_rank
                         or abs(d['d_gp']) >= args.material_gp)
        return d

    focus = sorted((keepers | lab) & (old_ids & new_ids))
    changes = [row_diff(p) for p in focus]
    changes = [c for c in changes if c]

    report = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'baseline_sha256': sha256(args.baseline), 'new_sha256': sha256(args.new),
              'players_old': len(old), 'players_new': len(new), 'added': len(added), 'removed': len(removed),
              'material_changes': [c for c in changes if c['material']], 'focus': changes,
              'thresholds': {'value': args.material_value, 'rank': args.material_rank, 'gp': args.material_gp}}

    lines = ['# Projection update diff', '',
             f"Baseline: `{args.baseline}` (sha256 {report['baseline_sha256'][:12]})",
             f"New: `{args.new}` (sha256 {report['new_sha256'][:12]})",
             f"Players: {len(old)} -> {len(new)} | added {len(added)}, removed {len(removed)}", '']
    if added or removed:
        lines += ['## Added / removed players', '']
        if added:
            lines.append('- Added: ' + ', '.join(new[i]['player'] for i in added[:40]))
        if removed:
            lines.append('- Removed: ' + ', '.join(old[i]['player'] for i in removed[:40]))
        lines.append('')
    lines += ['## Focus players (keepers + #6 candidates) — material moves first', '',
              '| Player | Rank | Δrank | GP | ΔGP | MPG | ΔMPG | Value | ΔValue | Material |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|']
    for c in sorted(changes, key=lambda c: -abs(c['d_val'] or 0)):
        lines.append('| %s | %d→%d | %+d | %.0f→%.0f | %+.0f | %.1f→%.1f | %+.1f | %+.3f→%+.3f | %+.3f | %s |' % (
            c['name'], c['rank_old'], c['rank_new'], c['d_rank'], c['gp_old'], c['gp_new'], c['d_gp'],
            c['mpg_old'], c['mpg_new'], c['d_mpg'], c['val_old'], c['val_new'], c['d_val'],
            'YES' if c['material'] else ''))
    mat = report['material_changes']
    lines += ['', '## Does the #6 plan change?', '']
    if not mat:
        lines.append('- **No material changes** to your keepers or the leading #6 candidates. '
                     'The existing shortlist and #43/#54 guidance remain valid; no lab rerun needed.')
    else:
        lines.append('- **Material changes detected** in ' + str(len(mat)) + ' focus player(s):')
        for c in sorted(mat, key=lambda c: c['d_val'] or 0):
            lines.append('  - %s: Δrank %+d, ΔGP %+.0f, Δvalue %+.3f' % (c['name'], c['d_rank'], c['d_gp'], c['d_val']))
        lines.append('- **Recommended:** rerun the Pick #6 lab with the SAME seeds so old/new are comparable '
                     'with less random noise:')
        lines.append('  `python3 scripts/run_pick6_lab.py --broad 12 --broad-drafts 2 --deep-top 6 '
                     '--deep-drafts 4 --deep-seasons 4 --models adp_stochastic,validated`')
    lines += ['', '## Cache / validation', '',
              'The projection CSV is part of `app/benchmark_jobs.INPUT_FILES`, so changing it changes the '
              'input-hash manifest and **older benchmark runs will refuse to resume** rather than mix '
              'stale projection-dependent results. Live engine valuations recompute automatically on reload.',
              '', '## Install', '',
              ('Activated: the baseline was archived under `data/projections/archive/` and the new export '
               'was installed as the canonical file. Restart the app to use it.' if args.activate else
               'Dry run only — nothing changed. Re-run with `--activate` to archive the current file and '
               'install the new one.')]
    Path(args.out).write_text('\n'.join(lines) + '\n')
    Path(args.json).write_text(json.dumps(report, indent=1))

    if args.activate:
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        stamp = date.today().isoformat()
        dest = ARCHIVE / f'hashtag_basketball_2026_27_projections_{stamp}.csv'
        if not dest.exists():
            shutil.copy2(args.baseline, dest)
        shutil.copy2(args.new, CANONICAL)
        # Record activation provenance next to the canonical file so the app can
        # report the snapshot date without a hardcoded string that can go stale.
        source_date = None
        match = re.search(r'(\d{4}-\d{2}-\d{2})', Path(args.new).name)
        if match:
            source_date = match.group(1)
        Path('projection_provenance.json').write_text(json.dumps({
            'source_file': Path(args.new).name, 'source_date': source_date,
            'activated': stamp, 'sha256': sha256(args.new),
            'baseline_archived': str(dest), 'html_source': args.html or None}, indent=2))
        print('Wrote projection_provenance.json')
        print('Archived baseline ->', dest)
        print('Installed new export ->', CANONICAL)
    print('Wrote', args.out, 'and', args.json)
    print('material focus changes:', len(mat), '/', len(changes))


if __name__ == '__main__':
    main()
