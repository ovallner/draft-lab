# 2026–27 Yahoo fantasy league schedule with dates

Updated calendar dates from Yahoo official Important Game Dates: https://basketball.fantasysports.yahoo.com/nba/gamedates

- `fantasy_week_calendar.csv`: all 23 Yahoo fantasy weeks, with start/end dates and custom league phase assignments. Week 1 has six days; Weeks 7 and 17 have fourteen days each.
- `weekly_matchups.csv`: original 102 confirmed head-to-head pairings (Weeks 1–17), now with dates.
- `weekly_team_schedule.csv`: original 204 team-week records (Weeks 1–17), now with dates.
- `teams.csv`: unchanged original identifiers.
- `validation.json`: updated validation summary.

Custom league playoffs: Weeks 18–20 (2027-03-01 through 2027-03-21), *not* Yahoo's default Weeks 20–22. The 23-week calendar includes later NBA weeks as `post_league_playoffs` solely to make date mapping complete; there are no known head-to-head fantasy matchups for those weeks.

**Data provenance:** matchup opponents come from the user's 12 Yahoo League Members screenshots; dates come from Yahoo's official calendar. Dates inclusive, interpreted in Yahoo fantasy game-week calendar. No fantasy scores or outcomes have been invented.

The NBA Cup championship game does not count in fantasy H2H per RotoWire/Yahoo reporting. Separately import actual NBA games for game-count modeling.
