# Draft Lab — local fantasy basketball assistant

An offline, advisory draft assistant for Oscar's 2026–27 keeper league. No account,
subscription, package install, frontend build, or draft-time internet connection is
required. Yahoo is separate: **submit your actual selections in Yahoo**.

## Launch on your Mac

From this folder:

```sh
python3 run.py
```

Requires Python 3.9+ (3.12 recommended). Opens `http://127.0.0.1:8765`. Alternatively,
double-click `Start Draft Assistant.command`. Keep its Terminal window open during
the draft. Stop with Ctrl-C. Re-run the same command to resume exactly where you left off.

The server binds only to the laptop's loopback interface. All fonts, scripts, styles,
projections, and schedules are local. SQLite writes after every event with full
transaction durability; ranking work runs independently and cannot block pick saves.

## Draft-day workflow

**Historical personas and Monte Carlo survival are now integrated.** Open the
**Manager personas** tab for per-season observations, cross-season replication,
validation results, model controls, subjective adjustments, and named asset
scenarios. See `data/history3/README.md` for the full audited methodology and
limitations. **Three seasons of draft history are loaded, but they are not equal:**
2023-24 has no usable ADP, 2024-25 has a truncated pool, and only 2025-26 has a
complete market. The extra seasons strengthened the evidence rather than the model —
personas still did not beat the ADP baseline in leakage-free held-out testing or in
cross-season transfer, so Auto keeps the baseline.
The old category-history weight is now inactive and labeled accordingly; learned
draft tendencies and explicit manual adjustments live in Manager personas.

Recommendation cards and player search show simulation-derived survival estimates
for the upcoming turn and following turn if passed. They include sample counts and
Monte Carlo intervals. Later estimates are censored at unresolved owners/keeper
assets; no weighted average of hypothetical scenarios is invented. Standard runs
use 300 trials. Deep recalculation runs independently of pick entry and can take
several seconds; existing rankings stay visibly marked stale until updated.

1. Put Yahoo and Draft Lab side by side; use the Draft tab.
2. Type a player name, use arrows or Ctrl-J/K, and press Enter to record the current
   slot. Clicking search results or a recommendation also records the **current**
   slot, whether yours or an opponent's. The owner is always shown above search.
   Empty search uses **Yahoo ADP order**, not your personal recommendations. Missing
   ADP uses a labeled estimate derived from Hashtag source rank and the observed
   rank/ADP relationship. Both ADP and Hashtag rank are displayed; estimated values
   are never presented as actual Yahoo observations.
3. Confirmed keeper slots automatically skip. All 36 keeper identities are removed
   from availability regardless of unresolved round costs.
4. `/` focuses search outside a text field. Returning to the app window focuses
   search. Esc clears search/correction mode. Cmd/Ctrl-Z with empty search undoes
   the last draft action; text fields retain normal text undo when they contain text.
5. Use the board to resolve owners/keeper slots, clear a pick, or target an earlier
   slot for correction. A replacement requires confirmation. Every action remains
   in the append-only event history, including undo.
6. Batch entry accepts exact listed names, one per line. It validates names and slots
   before starting; commits each pick individually. If interrupted, saved picks stay
   saved and remaining names are preserved in the text box.
7. Unlisted players can be recorded. No projection is fabricated; forecasts warn
   that their contribution is missing. Provider IDs use `ht:`; they are not NBA/Yahoo IDs.

The timer is a **manual advisory timer**, not synchronized with Yahoo. Start/reset it
as needed. Watchlists are saved in browser storage; picks and assumptions are saved
in SQLite. Watchlists are not part of draft backup exports.

Under your roster, **Current strategy** distinguishes an explicitly locked punt
from an automatic, tentative direction. Strengths and needs reflect your actual
players' per-game category impacts; the suggested punt comes from completed draft
paths. **Your pick priorities** follow your personalized recommendation order. Clicking
a priority fills search but does not record a selection. The roster player list is
collapsible; at half-screen width it starts collapsed to leave room for strategy.

Middle recommendation cards show Yahoo ADP explicitly. Missing ADP is labeled as
unavailable, with the estimated market value shown separately. **Targets for later
picks** separates good roster fits from picks worth spending your current asset on.
The details show a paired **now vs wait** plan and where passed-over premium players
land in the modeled opponent rosters. These allocations are forecasts, not facts.

## Built-in mock drafts

- Click **Start mock draft**. A fresh isolated practice database starts with all
  keepers, your current slot corrections, and recommendation assumptions—but no live
  selections. The mode badge clearly says **MOCK DRAFT · PRACTICE**.
- **Simulate next opponent** records one guessed opponent pick. **Run to my pick**
  advances opponents until your turn; you always choose your own picks.
- Open **Opponent guesses & mock settings** to see the top alternatives and their
  reasoning. Default: mostly Yahoo ADP, with modest adjustments for missing positional
  coverage, current roster category needs, and historical preferences. Select **ADP
  only** or change draft variation for different rehearsal styles. The historical
  preference slider in Assumptions also controls the mock's historical adjustment.
- The displayed weights are practice-generator weights, **not calibrated forecasts
  of what a particular manager will do**. Variation is seeded per run; resetting
  generates a new seed. Undo/replay within a run remains deterministic.
- **Reset mock** creates another fresh run and preserves the old one. Use the session
  dropdown to revisit old mocks or return to **Live draft**. There is no live-reset
  or live-autopick operation.
- Simulation pauses on unknown pick ownership or a full roster with unresolved
  keeper costs. Resolve the slot on the board; it never assumes the original owner.
- Live and mock databases survive app restarts. The last active session is restored.
  Session selection is shared across app windows; requests from a stale window are
  rejected rather than accidentally recording into a different draft.

Practice data lives in `local/draft_mocks/`; the session index is
`local/draft.sessions.json` (derived from the `--db` filename). Reset never deletes or
overwrites those runs. Backup exports identify live versus practice; a practice
backup is refused in live mode. Restore still requires a database with no events;
if copied setup/settings already created events, use a new empty `--db` path, then
start a clean mock there before restoring a practice backup.

**Complete mock · auto** records every remaining mock pick in one click: your picks
use the current punt build and the opponents use strict ADP. It refuses to run until
owners and keeper assets are reconciled, or you save exactly one explicit named asset
hypothesis. Live drafts are never auto-completed.

## Season strategy laboratory

The **Season lab** tab drafts the league under several of your strategies and plays
out several full synthetic seasons per draft, so you can compare builds before draft
day. It runs in a separate process, never blocks pick entry, and never modifies your
live or saved mock drafts. See `SEASON_SIMULATION_README.md` for the full methodology
and limitations. Results show **projected post-draft ranks** next to **simulated
outcomes**, and end with a single **strategy recommendation** graded on playoff
advancement. The recommendation is made on the `adp_stochastic` primary model and
required to be stable across the other selected models — opponent models are never
averaged. Strict-ADP opponents remain available as a compressed-variance baseline.

## Rehearse without touching your actual draft

```sh
python3 run.py --db local/rehearsal.sqlite3 --port 8766
```

Disable Wi-Fi after launching; enter picks, correct one, undo it, close/reopen the
browser, stop/restart the server, and verify everything recovers. Test the UI at
half-screen width on your laptop. The backup button exports portable JSON.

To restore, start with an **unused** database path, then import the backup on the
Assumptions & Data tab:

```sh
python3 run.py --db local/restored.sqlite3
```

Restore validates the complete event stream before installing it atomically. It
refuses to overwrite a database with existing events. Back up before travel.

## Recommendations: what is and isn't implemented

Implemented:
- Recomputed equal nine-category per-game z-scores, attempt-weighted shooting impact,
  correctly aggregated roster percentages, and negative turnover direction.
- Balanced, one-punt, and two-punt strategy screening; detailed comparison of three
  baseline finalist draft paths (balanced is retained as a control), plus candidate-
  specific one/two-category punt paths. Up to two punts can be locked in the controls.
- Unique-player hypothetical full-league draft completions using keeper-filtered
  Yahoo-first market order with source-rank fallback and small pick-preference windows. Historical preferences
  are optional, weak priors from user-supplied category record screenshots.
- Each shortlisted candidate is rechecked in two market orders. Ranking averages
  the results with a small fragility penalty; scenario spreads are not confidence
  intervals. Projected roster/matchup tables show the primary scenario.
- Daily position/start-slot matching for all three playoff weeks. Season GP/82
  serves as an explicit availability proxy, adjustable with the caution control.
- Fixed hypothetical playoff brackets across three seed orders, no reseeding.
- Common seed fields and category dispersion held fixed across candidate actions
  within each market scenario. The user is included in all fields, conditional on
  qualifying; taking a stronger player cannot benefit a rival through an artificial
  candidate-specific bracket reshuffle.
- Path index: 80% fixed-field bracket proxy, 20% all-opponent matchup proxy to
  acknowledge field uncertainty. Giving another manager Giannis changes that
  manager's projected roster and matchup strength; taking him removes that option.
  There is no fabricated separate "denial bonus."
- Explicit two-pick counterfactuals: take the candidate now versus take one of up to
  three evaluated premium alternatives now and try to acquire the candidate at the
  next owned live pick. Wait branches leave the target available to opponents.
  Failed waits use another available player; preferred wait plans are separated
  from draft-now priorities. Future selections are greedy approximations, not an
  exhaustive search.
- A two-index-point near-tie band uses market scarcity to avoid justifying large
  reaches with insignificant proxy differences. This is a conservative heuristic,
  **not** a statistical confidence interval. A wait plan within 0.5 index points
  is preferred when it actually obtains the target in at least one modeled draft.
- No-streaming and conservative streaming comparison. Streaming rotates one
  replaceable slot, considers at most four same-day free-agent adds, discounts the
  improvement 50%, and gives opponents the same capability. Removed player starts
  are subtracted before adding replacement contributions.
- Estimated next-pick and later-pick survival, with wider uncertainty for missing
  ADP. These are heuristics, not calibrated probabilities.

**Path indices and matchup percentages are uncalibrated model proxies—not actual
championship odds.** Independent category normal approximations do not capture
category covariance, rare exact ties, correlated injuries, or actual future opponents.
Historical percentages cannot calibrate these uncertainties. Don't interpret tiny
index differences as meaningful evidence.

Not implemented yet:
- Official per-fixture schedule cross-check; verified Yahoo position eligibility.
- Player-specific injury news, B2B rest probabilities, March role/team-incentive
  forecasts, covariance-aware Monte Carlo, calibrated qualification probabilities,
  actual seeded bracket forecasts, or exact Yahoo playoff tiebreak handling.
- True future keeper upside. The keeper slider is a small late-round production
  tie-breaker only; no youth/next-year production is invented. Round-1 eligibility,
  drop/re-add costs, keeper clocks, and collision mechanics need confirmation.
- Live Yahoo integration, automatic picks, global OS shortcuts, or waiver bidding.
- Perfect streaming competition simulation. Future free-agent access is uncertain.

The baseline uses the top 156 source-ranked players for per-game z-score distributions.
Hashtag rank/ADP influences hypothetical market order, **not** the recomputed player
category values. The source's rounded makes/attempts limit ratio precision.
Missing-ADP market estimates use a monotone smoothed rank-to-ADP curve fitted to
observed players. This is an uncertain fallback, not newly obtained Yahoo data.

## Validate before October 18

- Resolve traded owners for slots **106, 113, 123** in Yahoo/with the commissioner.
  Do not infer current ownership from original owner.
- Assign Nick's Ace Bailey/Jabari Smith Jr. and Samet's VJ Edgecombe/Dylan Harper
  to their exact surrendered assets. Currently only 32 keeper slots are mapped.
  The board supports these corrections; recommendations warn and cap simulated
  opponent rosters at 13 while timing remains uncertain.
- Confirm the CSV's October 11 capture/projection configuration and Yahoo positions.
  All 430 ranks are present; Alex Sarr explicitly aliases Alexandre Sarr. 243 rows
  have missing ADP. Original source files remain unchanged.
- The league settings screenshot confirms same-day lineups, four adds, two-day FAB
  waivers, and March 1–21 playoffs. No weekly games cap is assumed. Yahoo's disabled
  pick-trade setting does not resolve commissioner-arranged pick exchanges.

## Schedule refresh (before—not during—the draft)

The bundled JSON has 154 playoff fixtures reconciled against every supplied weekly
team count. Full known-season fixtures retain surrounding dates. Third-party source:
<https://fixturedownload.com/feed/json/nba-2026>.

```sh
python3 scripts/fetch_schedule.py
```

Or import a downloaded JSON feed without internet:

```sh
python3 scripts/fetch_schedule.py --input /path/to/downloaded-feed.json
```

The importer preserves the raw feed, records SHA-256/retrieval time, converts UTC to
`America/New_York` with DST, rejects duplicates/unknown teams, skips explicit NBA Cup
placeholders, and refuses to publish weekly-count mismatches. Investigate schedule
revisions rather than silently overwriting the supplied reference counts. Restart the
server after refreshing schedule data. Official reference:
<https://pr.nba.com/2026-27-nba-regular-season-schedule/>.

## Tests

```sh
python3 -m unittest discover -s tests -v
node --check web/app.js
```

Optional real-browser smoke test (requires separately installed Playwright and Chromium):

```sh
NODE_PATH=/path/to/playwright/node_modules node tests/browser.cjs
```

This creates its own rehearsal database, launches/stops a separate local server,
checks keyboard picks, undo, reload recovery, keeper filtering, owner overrides,
assumptions, unlisted picks, ADP ordering, strategy/priorities, mock progression and
reset, live-draft isolation, half-screen layout, and absence of external requests.

The Python tests cover data validation, keeper exclusions, schedule reconciliation,
shooting aggregation, TO direction, position congestion, strategy sensitivity,
unique simulated rosters, streaming limits, undo/correction, persistence, atomic
backup restore, concurrent-window revisions, and local API security. Node is optional
and only needed for the JavaScript syntax check.
Regression tests also cover the pick-6 Edey example, fixed seeded fields that always
include the user, and the effect of handing stronger production to an opponent.

Historical-persona tests (`tests/test_history.py`) cover the active three-season
package (ADP tiers, season-correct age/rookie, leakage-free validation, cross-season
transfer, preference replication), the retained single-season fallback, and Monte
Carlo reproducibility/censoring. Season tests
(`tests/test_season.py`) cover schedule validation, verified-calendar loading, strict
ADP reproducibility, health/shooting invariants, roster and acquisition limits,
waiver delays, playoff structure, failure-injection planners, cancel/resume, and the
small-sample interval guard.

## Files

- `app/`: data ingestion, recommendation engine, event store, loopback server.
- `web/`: dependency-free interface; no external assets.
- `data/`: normalized schedule, raw source, three-season personas (`history3/`), the
  single-season fallback (`history/`), streaming activity, and verified biographies.
- `manager_persona_three_season_history/`: combined 2023-24..2025-26 draft history
  with its ADP caveats (2023 unusable, 2024 truncated).
- `app/season_*.py`, `app/benchmark*.py`: the season simulation and benchmark pipeline.
- `fantasy_league_2026_27_schedule_with_dates/`: user-supplied head-to-head matchup
  pairs and reciprocal team schedules, plus the verified Yahoo 23-week scoring
  calendar (Weeks 1–20 simulated).
- `local/`: private SQLite and benchmark files created at launch. Do not share them
  unintentionally.
- Existing handoff CSVs/Markdown are retained unchanged as source material.

This is a working first version, not a fully calibrated fantasy forecasting system.
