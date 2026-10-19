# Local Fantasy Basketball Draft Assistant — coding handoff v1

## Mission
Build a local-first, responsive live draft assistant for Oscar’s 12-team Yahoo H2H nine-category keeper league. User drafts #6 on Oct 18, 2026; only purple-highlighted cells in original keeper sheet count as keepers, maximum 3 per team. **Do not treat all roster names as kept.** Keepers occupy / forfeit specified draft rounds. Oscar keeps Donovan Mitchell (R2), Shai Gilgeous-Alexander (R3), Kyshawn George (R12). Primary objective: win three weekly playoff matchups March 1–21, 2027. Keep realistic minimum regular season strength to reach 8-team playoffs. 45-second live draft timer.

## Supplied inputs
- `league_config.json` — user-confirmed league configuration and preferences.
- `draft_slots.csv` — all 156 sequential draft slots, exact snake order, initial ownership; **three green traded cells marked, owners not validated**. Single, unambiguous keeper forfeits marked; ambiguous duplicate round costs separately flagged.
- `keepers.csv` — all 36 keeper names and keeper-row round costs transcribed from the connected keeper sheet; double-cost rounds have unresolved exact pick assignments.
- `opponent_keeper_validation_TEMPLATE.csv` — convenient way to complete exactly 3 keepers per other team.
- `players_projections_TEMPLATE.csv` — data-import schema, no fabricated projections.
- `playoff_team_weekly_games.csv` — user-supplied Hashtag Yahoo W18–W20 playoff game counts by NBA team (30 teams); see `PLAYOFF_SCHEDULE_README.md`.
- `nba_games_TEMPLATE.csv` — authoritative game dates must still be filled, daily granularity essential.
- `player_availability_overrides_TEMPLATE.csv` — subjective injury, rest and B2B assumptions with provenance.
- `draft_events_TEMPLATE.csv` — manual draft events or Yahoo events adapter.

## MVP required screens
1. Setup & import validation (CSV ingestion, missing keeper warnings, team identification, season and playoff dates, projection freshness).
2. Live draft board (12×13 picks, keeper forfeits, traded picks, selected players, undo last pick; persist after every event; clock).
3. Recommendations at each **actual available pick**: top 10 candidates, draft now/target later, ADP reach, categories gained/lost, playoff games, risk, reasons and alternatives.
4. Team/category build: 9-cat forecast, percentile/z score, multiple punt scenarios rather than pre-locking a punt, rest-of-draft needs.
5. Playoffs: daily schedule/usable starts for each week, projected appearances, weekly 5–4/6–3 probability, semifinal/championship probabilities; streaming optional.
6. Assumptions controls: aggressiveness on playoff prioritization, injury/load-management risk, playoff week weights, punts, regular-season safety floor, keeper future upside.

## Ranking engine (implement modularly)
- Normalize per-game projections, using **FGM/FGA and FTM/FTA aggregated as ratios**, not naive averages of player shooting percentages. Add projected category totals using expected games, not per-game averages alone. Negative turnover contribution; expose equal-weight standard 9cat *and* customizable weighting.
- Build league baseline and category distribution (projected 12 team rosters; uncertainty-aware when opponents are incomplete). Explore punt-one and punt-two builds; apply punt only if modeled matchup win probability improves enough.
- Player selection objective: **marginal increase in expected probability of winning the playoff bracket** after adding player, conditional on estimated playoff qualification. Evaluate quarterfinal, semifinal, final sequentially; emphasize championship without discounting survival. Monte Carlo with category covariance and player-minute/game uncertainty is ideal; use deterministic z-score proxy as initial fallback.
- For every week, forecast **usable games** accounting for exact game dates, start slots/position eligibility, 3 bench slots, 4 adds per week, and high-volume nights; don't count blocked bench games as starts.
- Expected starts ≈ scheduled games × probability available × lineup feasibility; adjust for B2B rest, injury, workload, changing March team incentives, and projection/role risk. Do NOT substitute speculative rest assumptions for fact; defaults conservative, clearly labeled.
- Keeper value: optional future value to be modeled as surplus draft-round cost vs projected next-year production / keeper expiration; do not let speculative future values dominate current playoff odds unless user changes slider.
- For pick #6, calculate category and playoff fit to confirmed Shai, Mitchell, George and compare to alternative builds; do not force a big man or TO punt by narrative alone.
- Model opportunity cost of waiting: expected player availability at future real picks (#43, #54, etc.) based on keeper-filtered pool, other drafters and ADP.

## Import and licensing
Hashtag premium is $2.50/month as of Oct 2026; it provides projections and Yahoo draft tools. **CSV/export functionality is NOT verified.** Support import of user-authorized CSV / copied table exports without promising a specific button or scraping behind a login. Respect site terms; fallback to another permitted projection source if export not available. Keep exact export column mapping editable. Never hardcode premium content in repo.

## Live draft state
Draft event types: `pick`, `keeper`, `undo`, `correction`, `trade_owner_override`. Keep an append-only history and persisted normalized current state. Never mark keepers as real live draft selections twice. Map Yahoo identity carefully; names may contain punctuation/diacritics. Support manual click-to-draft as offline fallback, quick search, and resume from saved JSON. Yahoo API integration is optional and must confirm auth/access before implementation.

## Suggested stack
Python 3.12 + Streamlit for fastest local MVP, SQLite for event log/storage, pandas/numpy/scipy for stats, Plotly for charts; optional FastAPI + React only if desired. CLI import scripts and unit tests. Local `localhost` no external server required. Keep data contracts file-based and exportable.

## Tests / acceptance criteria
- Oscar has only 10 live picks at slots 6,43,54,67,78,91,102,115,126,150, while slots 19,30,139 are keeper forfeits.
- No rank includes a keeper from any team in the available pool. Must FAIL CLOSED until 36 keepers (or explicit confirmed fewer) are validated.
- All 156 slots are sorted correctly; traded pick ownership unresolved flagged, not assigned presumptively.
- Shooting% aggregation and TO are correct. Different punt toggles change ranking meaningfully.
- A 4-game week is not necessarily four usable games; injury and lineup-cap sensitivity works.
- Backtesting scenario: adding a 3-game player vs 4-game player can win if category impact/availability dictates.
- Pick undo restores availability, category forecast, and draft board exactly.
- Rankings recalc quickly enough for 45-second timer (<2 seconds on ordinary laptop after initial load).
- Source of every input and last refreshed time visible; never silently infer missing player stats or schedule.

## Data collection tasks before draft
1. Fetch original editable keeper sheet or a CSV preserving purple-cell keeper indicators and parse exactly all keepers and round forfeits. All 36 keeper names and source round labels now read directly from Google Sheet. Resolve duplicated keeper costs before asserting individual forfeited assets.
2. Verify ownership of highlighted traded picks 106, 113, 123 with actual trade ledger (green cells only show changed picks).
3. Import Hashtag or approved projection data through compliant download/copy workflow; confirm stats are rest-of-season versus full-season and update as needed.
4. Import official **daily** NBA 2026–27 schedule and compute March 1–21 per-team weekly games (avoid using publisher default playoff weeks without verifying dates).
5. Confirm Yahoo roster position eligibility and whether playoff week assignment precisely matches March 1–7, 8–14, 15–21.
6. Validate all 13-round keeper mechanics, trades, actual draft order with Yahoo pre-draft room.

## Important caution
Earlier discussion asserted specific playoff game totals from a third-party schedule without producing a verified machine-readable March 1–21 schedule. Treat those as *unverified*; regenerate from daily games and reconcile against multiple sources before optimizing.

## Read-only source ingestion update (2026-10-11)
All 36 marked keepers are captured in `keepers.csv`, exactly three per team. For ambiguous round-cost overlaps, see `keeper_cost_exceptions.csv`: Nick has Ace Bailey + Jabari Smith Jr. both marked R11; Samet has VJ Edgecombe + Dylan Harper (undrafted free agency = R10) both marked R10. Asset resolution must not assume both forfeit the same pick. Nick's transaction was #113 -> an acquired 9th (confirmed #106) -> an acquired 11th (identity TBD). Treat underlying keeper sheet as read-only.

## Data source added: Hashtag projections

`players_projections.csv` contains the latest recovered player projection rows (consult `PROJECTIONS_IMPORT_README.md` for exact coverage) from the uploaded Hashtag HTML page (with FG/FT makes and attempts); `keeper_projection_coverage.csv` audits keeper matching. Read `PROJECTIONS_IMPORT_README.md` for provenance, per-game semantics and cautions. Use source rank only as a reference, calculate equal-category and playoff-weighted player values separately.


## Projection data completeness warning (2026-10-11)
The HTML copied from the visible 400-player table contains only 347 parseable player rows. Missing source ranks: [244, 245, 265, 266, 278, 279, 317, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355, 356, 357, 358, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 399, 400]. `players_projections.csv` is an expanded but incomplete data set. Do not mark absent players as taken or unavailable.


## Verified playoff-week counts from user screenshot (2026-10-11)
`playoff_team_weekly_games.csv` contains 30 team rows for March 1–7, 8–14, 15–21. This verifies weekly *team game counts* as shown on Hashtag, **not** the daily fixture list. Load those counts now for a provisional weekly-game weighting model, but gate back-to-back/rest, usable starts, and lineup congestion on acquisition of an official daily schedule. See `PLAYOFF_SCHEDULE_README.md`.
