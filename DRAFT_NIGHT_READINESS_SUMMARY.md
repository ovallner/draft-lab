# Draft-night readiness summary — 2026-10-15

## 1. Active code and data configuration

**Active projection snapshot** (what the running app loads and what the audit tested):

- File: `hashtag_basketball_2026_27_projections_430.csv`
- SHA-256: `b2a59ca7500edf108073d1a55a483893146f6af3523644bf1928f48f5f779a96`
- Origin: `hashtag_10-15-26.html` import (source date **2026-10-15**), activated **2026-10-15**.
- The app computes the hash itself and reads the source date from `projection_provenance.json` (written by
  the update workflow); `metadata.projection_source_date` and `projection_sha256` are therefore never hardcoded.
- Import/validation record: `PROJECTION_IMPORT_2026-10-15.md`. Only per-game changes affect **Kawhi Leonard**,
  **Kristaps Porziņģis** (GP only) and **Brandin Podziemski**; 168 ADP and 29 rank changes.

**Previous snapshots preserved**: `data/projections/archive/…2026-10-12.csv`
(SHA-256 `2363f158…`) and `…2026-10-11.csv` (SHA-256 `42dc1fcc…`). The JSON/Markdown opening playbook
and all saved mock sessions are retained.

**Engine code is unchanged** by this import; the projection update is a data change.

### Snapshot history (all reconciled)

- The full-policy audit was validated on the **2026-10-12** export (`2363f158…`), which was then activated
  over the earlier **2026-10-11** snapshot (`42dc1fcc…`).
- On **2026-10-15** a new Hashtag export was imported (`b2a59ca7…`) and is now active; the prior snapshots
  remain archived. Only per-game data changed for Kawhi Leonard, Kristaps Porziņģis (GP only) and
  Brandin Podziemski, plus 168 ADP and 29 rank changes — see `PROJECTION_IMPORT_2026-10-15.md`.

### Identity / coverage verification (active snapshot)

- 430 projected players; **0 unprojected**; every player has non-empty positions.
- **35 keepers** — every team 3 except Austin with 2 (Mathurin was not kept; see the reconciliation note); all 12 managers present.
- Ownership/keeper reconciliation: `uncertainty_barrier = None`; **13 assets per team**.
- **Completed-draft reconciliation (2026-10-19):** the final rosters were reconciled against the
  Yahoo completed board; 12/12 teams now match, 156 unique players, 35 keepers. Cause and audit trail:
  `local/reconcile_20261019/RECONCILIATION.md`.
- Your picks: **#6, #43, #54, #67, #78, #91, #102, #115, #126, #150**; keepers
  Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George.
- 187/430 players carry a real Yahoo ADP; the remaining 243 use the labelled source-rank
  interpolation (`market_adp` set for all players).
- Schedule/calendar re-validated on load; provisional Yahoo positions remain flagged.

**Cache invalidation:** the projection CSV and `app/data.py` are both in
`app/benchmark_jobs.INPUT_FILES`, so older benchmark resumes now refuse to resume (they will not mix
stale projection-dependent results). Live valuations recompute on reload. The app was restarted to
load the new snapshot.

**Backups of the live draft and saved sessions** (taken before activation):
`local/projection_reconcile_20261015/` contains `draft.sqlite3.bak`, `draft.sessions.json.bak`,
`draft_mocks.bak/`, and the outgoing Oct-11 CSV.

## 2. The three unconventional #6 choices (Ware ×2, Clingan ×1)

All three come from saved audit traces; in **every** case the displayed featured pick was the
backend top row (0 backend/featured divergences).

| Trace | Board | Chosen | Next best (engine) | Score gap | Availability |
|---|---|---|---:|---:|---|
| `primary.adp_stochastic.0047.production` | #6 | Kel’el Ware | Devin Booker 0.623 | **+0.040** | all 1.00 |
| `primary.validated.0047.production` | #6 | Kel’el Ware | Devin Booker 0.623 | **+0.040** | all 1.00 |
| `primary.validated.0054.production` | #6 | Donovan Clingan | Chet Holmgren 0.633 | **+0.047** | all 1.00 |

Why they ranked first (bounded reproduction of the saved boards):

- The engine’s index is a **projected playoff-path score**, not equal-weight 9-cat value or ADP.
  Ware led with `score 0.663` / `baseline 0.724` / `streamed 0.670`; Clingan led with
  `score 0.680` / `baseline 0.744` / `streamed 0.684` — both highest, not tie-broken.
- Their **equal-weight value is low** (Ware 0.18, Clingan 0.08) and their Δ usable starts are
  ordinary (+8.1 / +9.9). The lead comes from the completion/bracket index, i.e. category fit,
  scarcity and how the roster completes afterwards.
- **Availability/wait was not the driver:** `availability_at_next ≈ 1.00` for every candidate, and
  no preferred “target later” plan overrode the pick (Clingan, Ware always `preferred = False` in
  the selected row’s wait comparison).
- **Not stale data:** the audit board matched the session/revision, and `recommend()` returned
  `valuation_barrier = None`.

Correctness checks for the “surprising” look:

- **No candidate pruning.** Cade Cunningham and Giannis Antetokounmpo *were* evaluated on the
  Clingan board and simply ranked below the 15-row display cap (`recommendations[:15]`); on the
  Ware board Cade had already been drafted by an opponent. The market elites were considered.
- **No scoring inconsistency.** The pick equals the displayed first row; the RNG-free ordering is
  the engine’s own.
- **No stale or candidate-pruning defect.** Classification: **unusual but defensible under the
  model**, not a reproducible problem. No player bans or first-round caps were added.

The audit’s paired outcomes support this: production (A) was statistically indistinguishable from
the competent fit baseline in both models (title 28.4% vs 28.4% ADP-stochastic, 27.9% vs 23.9%
validated), so these conspicuous C-only big picks were not shown to be costly. When following the
live engine, the featured list will occasionally show a big like Clingan/Ware/Kessler early if the
board falls that way — expected behaviour, not an error.

## 3. Changes made and how they were verified

| Change | Reason | Verification |
|---|---|---|
| Activated the 2026-10-12 projection CSV (archived the Oct-11 file) | The app was loading a different snapshot than the audit tested | Identity/keeper/ownership/coverage checks; app reports the new hash |
| `app/data.py`: compute projection SHA-256; read activation date from `projection_provenance.json` | The app displayed a hardcoded capture date that went stale | 104 unit tests pass; app metadata shows date + hash |
| Imported the 2026-10-15 HTML export and activated it (archived the Oct-12 file) | Newer source snapshot | `PROJECTION_IMPORT_2026-10-15.md`: 0-mismatch independent re-derivation, app round-trip, 104 tests |

No engine, policy, model or scoring change was made; the audit’s frozen source still verifies
hash-for-hash. The audit readiness verdict is unaffected.

## 4. Draft-night browser rehearsal

Disposable mock on a throwaway database; the real live draft and saved mocks were never used.
Observed **end-to-end** times (from clicking “Run to my pick”/turning to you, through fresh
recommendations being displayed, to the pick being recorded):

| Slot | End-to-end | Backend compute |
|---|---:|---:|
| #6 (early) | 11.4 s | 10.5 s |
| #43 | 9.5 s | 9.0 s |
| #54 | 17.5 s | 8.8 s |
| #67 (middle) | 18.0 s | 9.0 s |
| #78 (middle) | 16.4 s | 8.2 s |
| #91 (middle) | 15.0 s | 7.2 s |
| #102 (late) | 13.0 s | 6.4 s |
| #115 (late) | 10.9 s | 5.2 s |
| #126 (late) | 10.9 s | 5.2 s |
| #150 (last) | 3.3 s | 2.0 s |

- **Worst end-to-end observed ≈ 18.0 s** (middle round), mean ≈ 16.5 s middle / 9.5 s late,
  comfortably inside the 45-second clock.
- Loaded session/owner/revision/snapshot verified correct; the displayed first recommendation
  **matched** the intended production policy on all 10 picks (0 mismatches).
- Recommendations updated after opponent picks and after removing a preferred target.
- **Stale** (old revision) and **wrong-session** submissions were **refused (HTTP 400)**; the
  Record buttons were disabled while stale.
- Recording, undo/re-record, and switching to Live and back mid-mock all worked and preserved picks.
- Refresh restored the saved mock; the disposable live board stayed empty.

**Latest reliability pass (2026-10-18, disposable DB)** — `tests/reliability_rehearsal.cjs`, 11/11 checks:
the wrong-slot regression (recording from the recommendation list while correction #7 was open landed
on #6 and left #7 empty, clearing correction mode), normal opponent entry, deliberate correction +
undo, stale/wrong-session rejection, session switch/refresh/restart persistence, and the ADP fallback.
Fresh recommendations arrived in **10.5 s at #6** and **20.1 s at #43**, both inside the 45 s window
including computation. `tests/stale_analysis_check.cjs` separately confirms a null-analysis payload
clears matchups and shows an unavailable state, and that switching drafts never shows the old draft’s
matchups. `tests/test_app.py` asserts the server returns `analysis: null` **and** an `analysis_error`
when team analysis fails.

**Remaining clock risk / confusing interactions**

1. **Yahoo’s 45 s clock starts when your turn begins — not when the tool finishes thinking.**
   The first recommendation after load takes ~10–14 s and each pick’s recalculation ~7–18 s, and that
   computation consumes your clock. Start the 45 s timer the moment your turn begins, keep watching
   the `engine-status` line, and if a fresh result is not ready in time use the ADP fallback (step 6).
2. **Recording in Draft Lab never submits your pick in Yahoo.** Draft Lab only saves your local board so
   it can advise you. You must still make the selection in the Yahoo draft room before the clock expires.
3. A brief CSP console notice about inline styles appears during rendering; it is cosmetic and
   does not block functionality.
4. The featured list applies the “≥50% survival to your next pick” filter; it can therefore start
   below the backend’s absolute first row. If that happens, follow the displayed first row (that is
   what the policy was validated with).
5. Model uncertainty remains: championship differences in the audit mostly spanned zero, which is
   **not** proof of equivalence.

## 5. Launch instructions and checklist

Start the app (from the project directory), keeping the machine awake:

```sh
cd /Users/oval/Development/fantasy-basketball-helper
caffeinate -is python3 run.py
```

It prints `Draft assistant: http://127.0.0.1:8765` and opens the browser. `caffeinate` prevents
idle/system sleep for the app’s lifetime (plug in, keep the lid open; `caffeinate` cannot defeat
lid-close sleep). If a restart is needed, rerun the same command — the draft survives restarts.

Draft-night checklist:

1. Confirm the draft is the **Live** session (session selector), not a saved mock.
2. Confirm **Data quality** shows 430 projections, **35 keepers** (Austin 2), and the 2026-10-15 hash `b2a59ca7500e`.
3. When your turn begins, **start the 45 s timer immediately** — Yahoo’s clock is already running and the
   tool’s computation (≈7–18 s) comes out of it. A fresh result is shown when `engine-status` reads
   “N candidates · Xs” rather than “Updating · stale”.
4. Follow the **first displayed featured** player, unless a full legal board changes your read.
5. Record via the **Record → #slot Oscar** button (it always writes to your current pick, even if a
   correction is open elsewhere). Use the search box (Enter) only for opponents or corrections; Enter
   records the top available ADP player for the current owner.
6. **Enter your pick in Yahoo yourself** — Draft Lab recording does **not** submit it. Keep the Yahoo
   draft room as the system of record and submit before the clock expires.
7. If recommendations stall near the limit, use the search-box fallback: its first row is the best
   available ADP player — select that in Yahoo and record it locally to continue.
8. Never record on a stale banner; press **Undo** to correct a mistake (corrections use the same
   slot, marked CORRECTION).
9. `Ctrl-C` stops the server safely; the draft is saved after every pick.

Reference-only: the earlier `FIRST_THREE_PICKS_PLAYBOOK.md` (KAT-first chain) is retained as
background but is **not** applied over the live engine.

## 6. Deferred post-draft issues (tracked, not fixed in this pass)

These affect the completed-draft **evaluation** workflow only — they never touch in-draft pick
recording — so they are deferred until after the draft:

1. **Evaluation reuse ignores the requested season count / settings** — a repeat evaluation of the same
   session/revision returns the earlier result even if a different `seasons` value was requested.
2. **Saved evaluation history is not restored at startup** — evaluation jobs are held in memory; after
   a server restart the history list is empty until re-run (on-disk results are not surfaced).
3. **Zero observed championships can show a misleading 0–0 % interval** — with no title in the sampled
   worlds the reported interval can collapse to [0 %, 0 %] instead of reflecting sampling uncertainty.
