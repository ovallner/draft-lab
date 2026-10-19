# Fantasy draft assistant handoff — refreshed October 11, 2026

Read-only ingestion from **2026 Keeper List** Google Sheet: https://docs.google.com/spreadsheets/d/1eK4b1Q6JcSjMDoOuMSRHa1GZ3t-nyxkw12ecTfpiYxc/edit

- `keepers.csv`: all **36 explicit `>> ... <<` keepers** across 12 teams, with source keeper-row round cost. 3 per team. Other non-highlighted players are NOT keepers.
- `keeper_summary.csv`: human-friendly team overview.
- `draft_slots.csv`: all 156 draft positions (12-team snake); 3 traded source slots #106, #113, #123 remain unassigned unless proven. Single unambiguous untraded keeper costs are marked. **Do not derive current pick ownership from original team.**
- `keeper_cost_exceptions.csv`: overlapping round charges and traded slot overlap requiring reconciliation. A row's round cost is not sufficient to identify which exact asset was surrendered when there are multiple keepers with the same cost.
- `league_config.json`: known settings and preferences.
- Templates: projection, NBA game schedule, and live events inputs.

## Transaction facts from user-supplied Discord excerpt
Nick traded his original 10th-round pick (#113) to acquire a 9th-round pick; subsequently traded the acquired 9th-round pick (#106, originally Samet's), **not his own #104**, for an 11th-round pick. Counterparties and final acquired 11th-round slot remain unconfirmed. Independently, green draft-order #123 (Raul original) is marked traded; final owner unknown.

## Important modeling guardrails

- `keepers.csv` is confirmed for identity and **sheet round labels**, not complete payment/ownership mechanics. Nick lists Ace Bailey and Jabari Smith Jr. both in round 11, and Samet lists both VJ Edgecombe and Dylan Harper charged against round 10 (Dylan was undrafted). These **cannot** both consume the same original pick; reconcile exact forfeitures in Yahoo before treating all 36 costs as resolved.
- Players kept by other teams never appear in the available pool.
- User keeps Donovan Mitchell R2, Shai Gilgeous-Alexander R3, Kyshawn George R12 and picks #6, #43, #54 etc as in draft slots.
- **No modifications were made to the Google Sheet.** This package is a local derivative only.

To start the coding session, hand the complete ZIP to the coding agent and direct them to `SPEC.md`. Validate keeper/pick constraints first; build playable manual draft UI even if projection import is pending.

## Hashtag projections import (2026-10-11)

`players_projections.csv` contains the latest recovered player projection rows (consult `PROJECTIONS_IMPORT_README.md` for exact coverage) from the uploaded Hashtag HTML page (with FG/FT makes and attempts); `keeper_projection_coverage.csv` audits keeper matching. Read `PROJECTIONS_IMPORT_README.md` for provenance, per-game semantics and cautions. Use source rank only as a reference, calculate equal-category and playoff-weighted player values separately.


## Updated projections capture (2026-10-11)

The current CSV has 347 player records. The browser DOM extraction was partial. Missing rank numbers: [244, 245, 265, 266, 278, 279, 317, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355, 356, 357, 358, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 399, 400]. See PROJECTIONS_IMPORT_README.md.


## Playoff week schedules
`playoff_team_weekly_games.csv` provides all 30 NBA teams’ 3-week scheduled game counts from the user-supplied Hashtag screenshot. See `PLAYOFF_SCHEDULE_README.md`. These are weekly counts, not daily fixtures. Use `nba_games_TEMPLATE.csv` for later detailed game-date import.
