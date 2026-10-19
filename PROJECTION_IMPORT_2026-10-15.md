# Projection import — Hashtag 2026-10-15

## Source and conversion

- Source page: `/Users/oval/Downloads/hashtag_10-15-26.html`
  SHA-256 `27f4b2f87feae4a3e00cd6041629707c46e319c2dfe2a7d55a3987fad27c3d83` (430 players, 17-column table).
- Converter: `scripts/import_hashtag_html.py` (strict, fails closed).
- Output: `data/projections/incoming/hashtag_basketball_2026_27_projections_2026-10-15.csv`
  SHA-256 `b2a59ca7500edf108073d1a55a483893146f6af3523644bf1928f48f5f779a96`.
- Schema: the existing 22-column CSV — `rank,player_id,player,adp,positions,nba_team,projected_gp,mpg,fg_pct,fgm_pg,fga_pg,
  ft_pct,ftm_pg,fta_pg,three_pm,pts,reb,ast,stl,blk,to,hashtag_total`; UTF-8 with BOM, CRLF line endings,
  minimal quoting (positions contain commas). Player IDs come from each row’s `href="/NNNN/player"`.
  FG%/FT% are split from the page’s `pct (made/attempted)` cells.

## Independent validation

- `scripts/verify_projection_import.py` re-derives the table with a streaming `HTMLParser` (a different
  code path than the importer), then compares every field to the produced CSV:
  **430 players compared, 0 mismatches.**
- Structural checks: IDs exactly match the previous snapshot (0 added / 0 removed); ranks are a
  permutation of 1..430; GP ∈ [0,82]; MPG ∈ [0,48]; FG%/FT% consistent with makes/attempts under
  the page’s one-decimal rounding; no negative counting stats; positions unchanged.
- App loader round-trip (`app.data.Data` + `Engine` + `Store`): 430 players, 36 keepers,
  13 assets/team, `uncertainty_barrier = None`, Oscar keepers matched.
- **Deterministic**: re-running the converter reproduces the identical file hash.

## Changes vs the Oct-12 snapshot (2363f158)

| Area | Change |
|---|---|
| IDs / teams / positions | none (430 ↔ 430) |
| Ranks | 29 players |
| ADP | 168 players; **Ben Simmons** gains an ADP (blank → 112.6) |
| Projected GP | **Kawhi Leonard 58→50**, **Kristaps Porziņģis 42→30** |
| Per-game stats | **Kawhi** (FG%/FT%, PTS 23.7→24.7, REB, AST, STL, TO), **Brandin Podziemski** (PTS 14.5→15.1, 3PM, REB, AST, STL, FT%) |
| `hashtag_total` | 247 players differ by ±0.01 — Hashtag’s display rounding; this column is unused by the engine |

Engine value impact is small outside Kawhi (focus value +0.403→+0.390). Other focus players drift
by ~0.001 only because the z-score reference league is the top-156 by rank, and 29 ranks changed.

## Activation and caches

- Outgoing snapshot archived to `data/projections/archive/hashtag_basketball_2026_27_projections_2026-10-12.csv`
  (the Oct-11 snapshot remains there too). Activation used the normal `scripts/update_projections.py --activate`,
  which now also writes `projection_provenance.json` (source date/file, activation date, hash, HTML hash,
  archived baseline). `PROJECTION_UPDATE.md` records the diff.
- The projection CSV, `app/data.py` and `projection_provenance.json` feed `app/benchmark_jobs.INPUT_FILES`,
  so affected benchmark resumes are refused (`benchmark.py`/`benchmark_jobs.py` raise on hash mismatch).
  5 of 7 stored runs already differ; all projection-dependent ones now do.
- The app was restarted and reports `2026-10-15 export, activated 2026-10-15`, hash `b2a59ca7500e`.
  The live board’s #6 recommendation computes cleanly (21 candidates, no errors, no non-finite values).

## Tests and preserved state

- **104 unit tests pass.** One data-dependent regression test
  (`test_pick_six_regression_wait_for_edey_and_opponent_denial`) was re-baselined: under the new
  snapshot the remaining #6 board is a near-tie and the engine’s documented ≤0.02 scarcity safeguard
  selects **Evan Mobley** instead of Kevin Durant. The test now also asserts the tie-break is active.
- Preserved: the live draft (revision 15, 0 picks, 36 keepers), **11 saved mock sessions**, and the
  full-policy audit’s frozen source (verified hash-for-hash, 80 files).
- The audit’s readiness verdict concerns policy/operational behaviour and is not invalidated by this
  small update, but its numbers were computed on the Oct-12 snapshot; the specific #6 landscape shifted.
  No broad rerun was performed, per instruction.
