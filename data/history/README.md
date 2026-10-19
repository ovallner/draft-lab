# Historical manager model — methodology and limits

> **Superseded.** This describes the original **single-season (2025-26)** package in
> `data/history/`. The application now prefers the **three-season** package in
> `data/history3/` (see `data/history3/README.md`). This pipeline and its artifacts
> are retained as a fallback and remain under test, but it is no longer the default.

## Reproduce

From the project root:

```sh
python3 scripts/fetch_player_bios.py  # optional online refresh of NBA biographies
python3 scripts/import_history.py   # entirely local once biographies are cached
python3 -m unittest discover -s tests -v
```

Restart the app after importing. Source CSVs in
`manager_persona_2025_adp_handoff/` remain unchanged. Their SHA-256 values, verified
aliases, keeper coverage, team-to-manager map, ownership departures, and identity
gaps are recorded in `profiles.json` → `report`.

Generated outputs:
- `draft_validated.csv`: all 156 original selections plus normalized identities,
  keeper status, actual selecting manager, age/rookie/draft facts, and deviations.
- `choice_sets.json`: reconstructible known-ADP alternatives for all 116 covered
  discretionary selections; namespaced RotoWire IDs and optional current-ID links.
- `profiles.json`: observed statistics, fitted parameters, provenance and validation.
- `validation.json`: forward-round choice tests, round bootstrap, and survival replay.

## Historical source

RotoWire: `https://www.rotowire.com/basketball/adp.php?season=2025`, JSON endpoint
`/basketball/tables/adp.php?pos=ALL&season=2025`, retrieved **October 11, 2026**.
Source season is **2025–26**; underlying ADP measurement date is **unknown**.
This is **not a verified October 2025 draft-day snapshot**, and Yahoo ADP combines
formats rather than uniquely representing this keeper H2H league.

The 1,344-record export has 200 Yahoo ADPs. The historical draft has 36 keepers,
120 discretionary picks, and 116 ADP-covered discretionary picks. Four live picks
lack Yahoo ADP and are retained in the audit, not given invented historical ADPs.
Nine explicit suffix aliases reconcile the source/draft names. The original
comparison/summary files are checked against recomputed results, not used to train.

## Keeper-aware measurements

All 36 keepers are removed from availability **before the first pick**. Their
forfeited slots remain in the timeline but are not discretionary observations.
Every other selected player is removed when its actual selection occurs. Ownership
is attributed to the recorded selecting manager; six departures from the original
snake pattern are audited, not reassigned to original owners.

- **Raw deviation:** overall slot minus historical Yahoo ADP; negative = early.
- **Keeper-adjusted deviation:** known-ADP discretionary index minus the player's
  rank in the initial keeper-depleted known-ADP pool. Negative = early. This is an
  **ordinal** measure, not another numeric Yahoo ADP. Missing-ADP picks do not advance
  the known-market clock; the all-discretionary clock is stored separately.
- **Available rank:** one plus the number of remaining alternatives with strictly
  better ADP; ties use minimum rank. Rank 1 means best remaining ADP.
- **Gap to best:** selected ADP minus best available ADP; positive = bypassing a
  better-market option. This has a different sign convention from timing deviation.

The historical choice universe is the known-ADP players plus observed missing-ADP
selections—not all retired/free-agent names in the 1,344-row table. True historical
Yahoo eligibility is not completely reconstructed. This is an explicit limitation.

## Biographical features

`data/player_bios.json` stores verified official NBA public player-page
`CommonPlayerInfo` fields. The nba_api registry is used only to locate NBA IDs;
requested IDs and names are checked against the official page. Explicit aliases
avoid confusing fathers with sons. Current NBA teams, displayed ages, season
experience and scoring statistics are **not imported** into historical training.

Birthdates are evaluated at **October 1, 2025**. Rookie status uses the first
regular-season entry in official NBA season records, not draft year alone. Missing
first-season information remains unknown. Season indexes may reflect availability
of records rather than proof of minutes played; these are derived historical features,
not archived preseason pages. Birthdates/draft years and source hashes are retained.
All 206 historical candidate records have verified birth/draft source matches.
One current projection identity (Oscar Tshiebwe) has an unavailable official-page
payload and remains a logged biography error, not a guessed match.

Current projections are read only for **identity crosswalks** in this pipeline.
No 2026 production is used to explain 2025 picks. Coarse exported G/F/C positions
are explicitly not verified 2025 Yahoo eligibility. Future keeper intent and
player-specific loyalty cannot be identified from one season.

## Profiles and validation

A ridge conditional-choice model operates over actual known-ADP alternatives:
ADP rank slope, age association, rookie association, and coarse position associations.
Manager parameters shrink strongly toward a pooled prior. Stages with fewer than
four observations stay at the manager prior. Uncertainty displayed for parameters
is a diagonal curvature approximation; correlations are not represented and the
ranges are **not calibrated confidence intervals**.

Validation uses training through rounds 4, 7, and 10 and later held-out rounds.
Oscar is excluded from persona training. Hyperparameters are fixed before testing.
Choice metrics use 69 held-out picks. Paired log-loss differences are bootstrapped
by held-out round, not by treating individual selections as independent.

Survival replay uses 18 eligible held-out horizons and 189 candidate outcomes:
after an observed selection, predict availability at that manager's next live turn.
Fixed available-rank strata select candidates without examining who is chosen
later. Intervening picks are simulated; horizons crossing missing-ADP live picks
are censored. Candidate outcomes share horizons and are not independent samples.

Current results (lower is better except top-five accuracy):

| Metric | ADP baseline | Persona |
|---|---:|---:|
| Choice log loss | 4.4918 | 4.6089 |
| Mean selected-player rank | 23.67 | 23.88 |
| Top-five accuracy | 20.29% | 20.29% |
| Multiclass choice Brier | 1.0880 | 1.1065 |
| Survival Brier | 0.16985 | 0.17687 |

Persona-minus-baseline log loss: **+0.1171**; round-block bootstrap 95% interval
approximately **[+0.0186, +0.2383]**. Personas have not improved held-out predictions.
**Auto therefore uses the fitted ADP baseline.** Experimental personas and subjective
overrides are opt-in and labeled separately. These results do not establish
real-world 2026 calibration given one season and an undated ADP snapshot.

## Live Monte Carlo and unresolved assets

The same conditional-choice weights drive mock picks, paired value-path opponent
choices, and survival simulation. Prospective value, category needs, position
coverage and late-round youth adjustments are small explicit assumptions, not
historically fitted fantasy-value coefficients. User overrides are separate events.

Standard survival uses 300 trials per scenario, adjustable from 50 to 1,000.
Manager/phase coefficient uncertainty is sampled using ridge approximations.
Missing current ADP is rank-derived and perturbed with an assumed 0.25 log-scale
spread per trial; this is not observed market data. Wilson intervals report
**Monte Carlo sampling error**, not all real-world/model uncertainty.

Two horizons are distinct: reaching the upcoming turn, and reaching the following
turn **conditional on reaching the upcoming turn and being passed on**. If the
proxy policy drafts a target for Oscar, that trial is rerun excluding the target
from Oscar's choices only. Opponents can still select it. No target is reserved.

Unknown ownership at 106/113/123 and unassigned Nick/Samet keeper assets are never
resolved automatically. Predictions stop at the earliest source-round uncertainty.
If that round has already been reached while still unresolved, forecasts stay
censored. Confirmed earlier picks are assumed unaffected by those later source-round
cost labels; unknown cross-round payment mechanics remain a limitation.

Named JSON scenarios can supply exact owners/keeper assets without editing live
facts. They are **not weighted or averaged**. Incomplete or unbalanced scenarios
stay censored. Fully reconciled scenarios also generate 16 complete remaining-draft
samples, respecting all owners and 36 forfeitures. The board remains the mechanism
for committing confirmed ownership and exact keeper asset corrections.

Playoff value is still the existing nine-category/usable-starts/streaming proxy,
not an ADP objective. Expensive candidate comparisons use two paired league paths
with player-indexed Gumbel common noise to avoid inverse-CDF allocation cascades.
These paths are explicitly partial while assets are unresolved. A single named
scenario is used explicitly in valuation; multiple scenarios are not silently averaged.
Hundreds of survival trials do **not** calibrate the playoff index. Monte Carlo
scarcity breaks near-equal-value ties and gates waiting plans; scarcity alone cannot
promote a poor-fit player. Covariance-aware playoff simulation remains future work.
