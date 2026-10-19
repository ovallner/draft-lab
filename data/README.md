# Local input provenance

- `nba_schedule.json`: normalized full known-season Fixture Download JSON feed.
  `metadata` records exact retrieval timestamp, source URL, SHA-256, reconciliation,
  and verification limits. Original feed is `nba_schedule_source.json`.
- All 90 playoff team/week counts reconcile with the original
  `playoff_team_weekly_games.csv`. Official NBA per-fixture cross-check is pending.
- `historical_categories.csv`: manually transcribed from the user's previous-season
  category win/loss screenshot in this session. Each number is
  `(wins + 0.5 × ties) / (wins + losses + ties)`, rounded to three decimals. Managers
  were mapped using the supplied manager screenshot; no emails were retained.
  Different teams have different matchup counts. This is a weak opponent preference
  prior, not a current-season strength forecast or calibrated weekly distribution.
- Main 430-player projection CSV remains at the project root unchanged. Its column
  values overlap exactly with the earlier October 11 export; capture timestamp and
  filter configuration are not embedded in the newer file and require confirmation.
