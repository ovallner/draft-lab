# Draft & Season Strategy Laboratory — Methodology Summary for External Review

**Purpose of this document.** This is a self-contained description of a local, offline
research tool that compares *draft strategies* for one specific 12-team Yahoo
head-to-head 9-category keeper league, by drafting the league many times and then
simulating full synthetic seasons. It is handed to a reviewer so they can assess the
**methodology**: what is modeled, what is assumed, what is measured, and where the
weaknesses are.

The tool is **advisory only** and its outputs are **not calibrated real-world
probabilities**. The whole point of this document is to make the assumptions visible
enough to attack.

---

## 1. The league being modeled

| Setting | Value |
|---|---|
| Platform | Yahoo, H2H, 9 categories, 12 teams |
| League | "It Begins" (Yahoo league id 8120) |
| Categories | FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO |
| Rosters | PG, SG, G, SF, PF, F, C, UTIL×3, BN×3, IL×3 (13 active + 3 IL) |
| Draft | 13 rounds, snake, live; user drafts from position **#6** |
| Keepers | 3 per team (36 kept players already removed from the pool) |
| Acquisitions | 4 per scoring period (8 for extended 14-day periods if enabled) |
| Playoffs | 8 teams, weeks 18–20 (2027-03-01 → 2027-03-21), fixed bracket, no reseeding |
| Objective | maximize probability of winning the playoff quarterfinal → semifinal → final |

The user's framing: this is the **last season with their best keeper (SGA)**, so the
objective is "championship or bust," but the measurement is deliberately
playoff-advancement-graded rather than a raw title flag (see §7).

## 2. Data inputs and provenance

| Input | Source / provenance | Trust level |
|---|---|---|
| Player projections (stats, GP, MPG, positions, rank) | `hashtag_basketball_2026_27_projections_430.csv`, 430 rows, captured 2026-10-11 (handoff; capture date not embedded in file) | Single unverified snapshot |
| Yahoo ADP | `adp` column of the same file; **243 / 430 players have no ADP** | Partial; measurement date unknown |
| Missing-ADP fallback | Monotone pooled-adjacent-violators smoothing of ADP vs source rank (`app/market.py`) | Labeled estimate, not observed Yahoo ADP |
| Keepers | `keepers.csv`, 3 per team, validated against projections | Verified user input |
| Fantasy matchup pairs | `fantasy_league_2026_27_schedule_with_dates/weekly_matchups.csv` (+ reciprocal schedule) | Verified from league screenshots |
| Scoring-week calendar | `fantasy_league_2026_27_schedule_with_dates/fantasy_week_calendar.csv`, 23 Yahoo weeks, dates verified from Yahoo "Important Game Dates" | Verified |
| Daily NBA fixtures | `data/nba_schedule.json` (fixturedownload.com), 1200 games; reconciled to user-supplied weekly counts | Third-party; official per-fixture cross-check pending |
| Playoff weekly game counts | `playoff_team_weekly_games.csv` (w18/w19/w20 per NBA team) | Used only by the draft heuristic's playoff weighting |
| Streaming/FAB activity priors | `data/streaming_activity_2025.csv`, manually transcribed from 5 user screenshots (Feb 24–Mar 22, 2026) | Weak ordinal signal, explicitly not a successful-add count |
| Manager personas | `data/history3/profiles.json` (3 seasons of draft history, 468 picks) | **Failed validation; not used** (§5) |

Non-standard calendar facts that are deliberately modeled rather than smoothed:
Week 1 is 6 days, and Weeks 7 (NBA Cup) and 17 (All-Star break) are 14-day calendar
periods containing only 6 and 8 NBA game-days respectively — so period length is
**not** a games-played proxy.

## 3. Pipeline (five stages, all paired/streamed)

1. **Freeze an immutable snapshot.** The current draft board + strategy list +
   opponent models + season assumptions + named asset scenarios are stored in
   `request.json` with SHA-256 hashes of code and data. A resume refuses to mix
   changed inputs (`app/benchmark_jobs.py`).
2. **Complete the draft** 12 teams × 13 rounds (`app/season_draft.py`). The user's
   picks use the chosen own strategy; every opponent picks from the selected opponent
   model. Keepers pre-populate specific slots.
3. **Project** a post-draft baseline: expected category totals using healthy
   `projected_gp/82` availability, no acquisitions, daily lineups over weeks 1–17.
   This yields the "**projected rank**" columns.
4. **Simulate full seasons.** Each draft plays `seasons_per_draft` independent
   synthetic seasons (daily lineups, injuries, IL, FAB/waivers, streaming, fixed
   playoffs).
5. **Summarize + recommend** (per case, no cross-case averaging).

Every stage-4 world (a single realization of all player health and box scores for the
whole season) is generated **once per (draft-index, season-index) and shared across
all strategies, opponent models, and asset scenarios** in that replicate. This is the
core pairing device: strategy differences are not confounded with a lucky/unlucky
season draw.

## 4. Draft model

### 4.1 Opponent conditional-choice model

Opponent picks are drawn from a single shared model (`app/draft_model.py`):

- Players are ordered by `market_key` = (Yahoo `adp`, else smoothed estimate; then
  source rank; then id).
- Weight for the *i*-th player in the available pool: `w_i ∝ i^(-α) · fixed_i · dynamic_i`.
- `α` (adherence) is set by a round-phase coefficient: **early ≈ 1.54, middle ≈ 1.08,
  late ≈ 0.69** (fit on 226 pooled 2024-25 + 2025-26 choice sets).
- `fixed_i` includes optional youth/rookie/position terms plus per-manager target
  overrides; `dynamic_i` includes modest positional-need and missing-center/forward
  bonuses.
- A per-pick uniform draw selects from the categorical distribution.

Two important implementation facts a reviewer should check:

1. **The baseline "ADP" path has essentially zero fitted preference betas.** The
   shrunk-to-zero `baseline_phases` coefficients on youth/rookie/guard/forward/center
   are ~1e-9. So when `requested='adp'`, the model is *pure ADP adherence* with a
   power-law slope, plus sampled uncertainty in the slope only (`N(mean, sd)`, sd ≈
   0.07–0.09, clamped).
2. **The `validated` model is the same ADP coefficients plus a modest *prospective*
   roster-fit tilt** (`+0.12·value_proxy + 0.015·age·(round−8)` and needs bonuses).
   Those fit terms are explicitly "prospective assumptions," **not fitted** to data
   (§5). So the two opponent models differ only by that modest tilt.

### 4.2 The user's own draft strategies (the thing being compared)

`app/season_draft.py` implements transparent greedy one-step policies:

- **`adp_stochastic` — "Pure ADP baseline"** (added last): the user drafts as a pooled
  ADP-driven manager, i.e. drawn from the *same* conditional-choice model the
  opponents use, with no roster-fit or playoff reasoning. This is the "what if I just
  followed ADP" baseline, deliberately stochastic rather than a zero-variance bot.
- **`adp`** — deterministic best-available ADP (zero variance); stylised control.
- **`playoff`** (a.k.a. "balanced") — greedy score over the top 10 (or 16 after 7
  picks) available by ADP:
  `production = (category_z_mean + 2)·health·playoff_factor − 2`, plus a positional
  `need_bonus`, minus a small market-rank cost. `health = 1 − risk·(1 − gp/82)`;
  `playoff_factor = 1 + playoff_weight·(weekly_playoff_games/10.5 − 1)`.
  Category weights decay as categories saturate (`exp(−0.08·sum_z)`).
- **`fit`** — same but without the playoff factor.
- **`auto_punt`** — adaptively punts up to two categories whose summed z is < −0.75.

**Critical caveat for translation:** these own-strategy policies are *not* the live,
expensive recommendation engine used during the real draft (which does paired-path
bracket evaluation, survival Monte Carlo, wait-plan analysis). They are fast proxies
chosen so a 72-season batch finishes in ~minutes. **Benchmark results therefore measure
these proxies, not the live tool's advice.** A reviewer should treat "strategy A beats
B" as a statement about these heuristics.

Also note the heuristic can never select a player outside the top 10/16 available by
ADP (a hard window), and it ignores opponent behavior and pick survival entirely.

## 5. Manager personas — a negative result (important)

A three-season draft-history pipeline (`app/history3.py`, `data/history3/`) was built
to test whether individual managers have exploitable, replicable preferences.

- 2025-26 is the only complete ADP market; 2024-25 has ADP only for players actually
  taken (truncated pool, understating late-round reach by ~26 slots); 2023-24 has no
  usable ADP at all (the supplied export duplicates 2024). Slopes are fit per season,
  never pooled.
- **Descriptive traits are real and replicate** (e.g. Adam/Jipples/Samet/Shiven draft
  younger; Austin/Nick/Oscar older; Jipples takes more rookies; Raul favors forwards).
- **They add no predictive power.** Held-out choice log loss: baseline 4.0081 vs
  persona 4.0078; the paired round-bootstrap interval [−0.039, +0.034] spans zero; and
  **0/2 cross-season transfers favor the persona** (2024→2025 and 2025→2024).
- **Decision: `persona_enabled_by_default = false` → Auto keeps the ADP baseline.**

Consequence: opponent behavior is modeled as **ADP-driven, not personality-driven**,
and the recommendation is explicitly built so it does not depend on guessing individual
manager quirks. `persona_experimental` remains selectable as a labeled sensitivity.

## 6. Season simulator (`app/season_sim.py`, `app/season_world.py`)

Modeled per day over 20 league weeks (weeks 21–23 are post-league and never simulated):

- **Health:** synthetic per-player injury process. A season-long "burden"
  `= (1 − gp/82)·injury_scale` is split 75% into injury episodes (scaled down for
  low-MPG role players) and the remainder into isolated rest/absence days. Injury
  durations are Exp(mean = `mean_injury_days`, default 12). Severity is short/medium/long
  by duration; medium/long become IL-eligible after `il_delay_days` (default 2).
  Rest probability is boosted on back-to-backs.
- **Performance:** per-game shooting counts sampled coherently from a Poisson/binomial
  process scaled by a minute factor = (lognormal game draw)·(player role)·(weekly form),
  so FG%/FT% stay internally consistent. **Not calibrated player covariance.**
- **Lineups:** daily maximum-weight start selection (`engine.lineup`) on the real NBA
  game calendar; blocked bench games are counted.
- **IL:** 3 slots; returning players need an open active slot or a drop; locked/eliminated
  managers do not release players into the pool.
- **Waivers/FAB:** shared free-agent pool; dropped players wait `waiver_days` (default 2);
  claims compete on bid then rolling waiver priority; unsuccessful bids consume neither
  an add nor budget. Starting FAB 100, min bid 0.
- **Streaming:** own behavior comes from the strategy (`aggressive` adds to the cap every
  period); opponents use shrunk, transcribed activity priors with separate regular-season
  vs championship vs placement context. Own `aggressive` is applied equally to **all**
  own strategies, so it is not the thing being compared.
- **Policies never see the future:** they see projections, published schedules, current
  health, and *past* box scores only. Recent production enters a per-player exponential
  trend factor used in later valuations.
- **Standings tiebreaks:** category win %, then head-to-head category %, then last-period
  %, then a seeded lottery. **Playoff tiebreaks:** head-to-head category %, then higher
  seed. *These are approximations; exact Yahoo fallbacks are unverified.*

## 7. Grading metrics

- **Projected rank** — post-draft expected category strength, no injuries, no moves.
- **Simulated regular rank / finish** — realized.
- **Advancement (0–4)** — the primary graded target:
  `qualified + semifinal + final + champion`, so 0 = missed playoffs, 1 = lost the
  quarterfinal, 2 = lost the semifinal, 3 = lost the final, 4 = champion. Strictly
  playoff-first but smoother than the binary title flag; the reported value is the mean
  over seasons.
- **Title rate**, **qualification rate**, **mean adds/starts/blocked games/IL player-days/
  FAB spent** — process diagnostics.
- **Paired differences** vs the first strategy in the same group, over identical drafts
  and worlds.
- **Intervals**: 1000-replicate **draft-cluster** bootstrap (resamples whole drafts, since
  seasons within a draft are dependent), percentile [24, 974]. With <3 draft clusters the
  interval is intentionally uninformative. Degenerate bootstrap is widened with a Wilson
  bound (binary metrics) or the cluster standard error (0–4 advancement).
- **Model separation**: mean shared-roster share across compared opponent models; if
  ≥85% the models are near-duplicates and "agreement" between them is discounted.
- **Variance split**: draft-to-draft vs season-to-season share of outcome variance.

## 8. Recommendation logic (deliberately conservative)

Per asset scenario, on the **primary** model (`adp_stochastic` preferred), pick the
strategy maximizing the tuple (mean advancement, title rate, qualification rate). Then
stress-test for **agreement** across the other selected opponent models. Models are
**never averaged or weighted** (their relative realism is unvalidated); robustness is
established by agreement, and agreement only counts when the models genuinely differ.

Statuses:

- **strong** — leads primary, paired gap interval excludes zero, models genuinely
  differ, and the same strategy wins on every selected model.
- **lean** — leads primary but flips on another model, or the interval spans zero, or
  models were near-duplicates.
- **inconclusive** — winner differs by asset scenario, or <3 drafts per case.
- **baseline** — only one strategy tested.

## 9. Actual saved runs (real output, verbatim numbers)

Three completed runs exist under `local/draft_benchmarks/`. All used **3 drafts × 3
seasons = 9 season outcomes per case**, seed 20261018, the same illustrative (unverified)
asset scenario (`106 Raul / 113 Samet / 123 Nick`), `injury_scale=1`,
`mean_injury_days=12`, `il_delay_days=2`, `starting_fab=100`, `waiver_days=2`,
`eligibility=placement`, `streaming_model=observed`, `extended_adds=same`,
`protected_core=8`, `start_mode=keepers`.

### Run A — `1304452824fb46f5b2a547aa8e359e39` (session "Mock 4", rev 36)
Calendar: **UNVERIFIED hypothesis** (pre-dates the verified Yahoo calendar).
Models: `adp_deterministic` + `validated`. Strategies: 3 (no ADP baseline).
**No recommendation block** (schema predates it).

| Model | Strategy | proj rank | sim reg rank | adv(0–4) | qual | SF | F | title | adds | starts | IL days | distinct rosters |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| adp_deterministic | Balanced playoff fit | 1.0 | 3.89 | 1.89 | 1.00 | .56 | .22 | .11 | 67.1 | 850.0 | 158.6 | **1** |
| adp_deterministic | Punt TO | 1.0 | 2.89 | 2.22 | 1.00 | .67 | .33 | .22 | 70.7 | 854.8 | 176.8 | **1** |
| adp_deterministic | Auto punt exploration | 1.0 | 3.44 | 2.33 | 1.00 | .56 | .56 | .22 | 70.3 | 846.8 | 172.7 | **1** |
| validated | Balanced playoff fit | 1.0 | 1.11 | 2.00 | 1.00 | .44 | .33 | .22 | 69.3 | 856.2 | 130.7 | 3 |
| validated | Punt TO | 1.0 | 1.11 | 3.33 | 1.00 | .89 | .78 | .67 | 71.2 | 856.2 | 173.2 | 3 |
| validated | Auto punt exploration | 1.0 | 2.33 | 2.56 | .89 | .67 | .67 | .22 | 70.1 | 845.9 | 168.7 | 3 |

Paired vs Balanced: on `adp_deterministic`, Punt TO title +0.111 (not supported); on
`validated`, Punt TO title +0.444, `supported_improvement=True` (advancement intervals
were still the old all-zero placeholder in this schema). Note the **distinct own
rosters = 1** under `adp_deterministic`: strict-ADP opponents make every draft identical,
so only seasons add information — exactly the degenerate case the tool warns about.

### Run B — `65a3ed9704f84374847fb5b3559077c6` (session "Mock 5", rev 0)
Calendar: **verified Yahoo**. Models: `adp_stochastic` + `validated`. 3 strategies.

| Model | Strategy | proj rank | sim reg rank | adv | qual | SF | F | title | distinct rosters |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| adp_stochastic | Balanced playoff fit | 1.0 | 1.56 | 2.67 | 1.00 | .67 | .56 | .44 | 3 |
| adp_stochastic | Punt TO | 1.0 | 1.11 | **2.89** | 1.00 | .78 | .56 | .56 | 3 |
| adp_stochastic | Auto punt exploration | 1.0 | 2.22 | 2.67 | 1.00 | .67 | .56 | .44 | 3 |
| validated | Balanced playoff fit | 1.0 | 1.22 | **3.11** | 1.00 | .89 | .78 | .44 | 3 |
| validated | Punt TO | 1.0 | 1.78 | 2.00 | 1.00 | .56 | .33 | .11 | 3 |
| validated | Auto punt exploration | 1.0 | 1.44 | 2.22 | 1.00 | .56 | .33 | .33 | 3 |

Paired vs Balanced: `adp_stochastic` → Punt TO adv +0.222, interval [−0.67, +0.67],
not supported; Auto 0.000. `validated` → Punt TO adv −1.111 [−1.67, 0.00]; Auto −0.889.
**Recommendation: `lean`** — "Punt TO leads the primary model, but the ranking flips on
another opponent model, so it is not robust." Gap −0.67…+0.67 (includes zero).

### Run C — `e25bea7c53f44b3fa3d75bfb9c1de0a6` (session "Mock 5", rev 0)
Calendar: **verified Yahoo**. Models: `adp_stochastic` + `validated`. 4 strategies
(now including **Pure ADP baseline**). 72 seasons total.

| Model | Strategy | proj rank | sim reg rank | adv | qual | SF | F | title | adds | starts | IL days | rosters |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| adp_stochastic | **Pure ADP baseline** | **4.3** | 3.78 | 2.00 | .78 | .67 | .44 | .11 | 67.9 | 809.7 | 171.6 | 3 |
| adp_stochastic | Balanced playoff fit | 1.0 | 1.00 | 2.89 | 1.00 | .78 | .67 | .44 | 69.8 | 855.7 | 153.6 | 3 |
| adp_stochastic | Punt TO | 1.0 | 1.22 | 2.89 | 1.00 | .78 | .67 | .44 | 71.1 | 858.2 | 163.0 | 3 |
| adp_stochastic | Auto punt exploration | 1.0 | 1.11 | **3.00** | 1.00 | .89 | .67 | .44 | 71.9 | 858.6 | 174.9 | 3 |
| validated | **Pure ADP baseline** | **4.3** | 4.33 | 2.11 | .78 | .67 | .56 | .11 | 66.9 | 808.0 | 184.7 | 3 |
| validated | Balanced playoff fit | 1.0 | 1.11 | 2.78 | 1.00 | .67 | .56 | .56 | 70.8 | 858.0 | 149.9 | 3 |
| validated | Punt TO | 1.0 | 1.11 | 2.33 | 1.00 | .67 | .33 | .33 | 73.1 | 857.7 | 179.6 | 3 |
| validated | Auto punt exploration | 1.0 | 1.44 | 2.44 | 1.00 | .56 | .56 | .33 | 71.1 | 851.8 | 165.7 | 3 |

Paired vs **Pure ADP baseline** (the reference now):

| Model | Compare | Δadv | adv 95% interval | supported |
|---|---|---:|---|---|
| adp_stochastic | → Balanced | +0.889 | [−0.33, +1.67] | no |
| adp_stochastic | → Punt TO | +0.889 | [+0.33, +2.00] | **yes** |
| adp_stochastic | → Auto punt | +1.000 | [+0.33, +2.33] | **yes** |
| validated | → Balanced | +0.667 | [−0.33, +2.67] | no |
| validated | → Punt TO | +0.222 | [−1.33, +2.00] | no |
| validated | → Auto punt | +0.333 | [−0.67, +1.67] | no |

**Recommendation: `lean`** — Auto punts leads the primary model but the ranking flips on
`validated` (where Balanced leads); gap +0.111, interval [−1.00, +0.67], includes zero.
Model separation: **shared roster share 0.524 → informative**. Variance split:
**draft-to-draft 6.7%, season-to-season 93.3%** ("Most of the spread is season luck
(injuries/waivers), so draft-day differences are second-order").

### Cross-run reading

- The ADP-only opponents (`adp_deterministic`, Run A) collapse draft variance and
  systematically change results — the tool recommends against using them as a headline.
- The optimizing heuristics beat the Pure ADP baseline on **projected rank** by a large
  margin (1.0 vs 4.3) and on advancement (≈2.9 vs ≈2.0), but the *paired* intervals are
  wide and only sometimes exclude zero.
- The winner flips between opponent models in every run with ≥2 models → `lean`, never
  `strong`. This is the honest state: **no strategy has been shown robustly best.**
- The ADP baseline's rosters produce ~45 fewer simulated starts (≈810 vs ≈856),
  consistent with ADP not pricing projected GP/availability.

## 10. Documented assumptions and unknowns

- **Not calibrated.** Injury rates/durations, FAB behavior, waiver clock, lock
  interpretation, role drift, and scoring tiebreaks are assumptions; title frequencies
  are not real-world odds.
- No fantasy/NBA trades, no schedule revisions, no injury-driven teammate role
  promotion, no speculative injured-FA stashing, fixed NBA teams.
- Population restricted to imported projections; unprojected players cannot be invented.
- The scoring calendar is verified, but **streaming activity, ending FAB balances, and
  the "Moves" totals are transcribed and explicitly weak signals.**
- Missing-ADP players use a rank-derived estimate with assumed 0.25 log-scale noise.

## 11. Candidate strengths (for the reviewer to confirm)

1. **Paired design**: same draft, same health/performance world across strategies —
   strategy differences are not confounded with season luck.
2. **Dependent-structure-aware uncertainty**: resamples whole draft clusters, not
   independent seasons; refuses uninformative intervals below 3 clusters.
3. **Honest negative result**: personas were built, tested leak-free, and *rejected*
   instead of shipped.
4. **No model averaging**: opponent models treated as robustness checks; agreement is
   measured, not assumed (shared-roster share), and discounted if models are near-dupes.
5. **Fail-closed reconciliation**: unresolved owners/keepers or unprojected players stop
   the run rather than being silently guessed.
6. **Variance split** explicitly tells the user whether the bottleneck is drafting or
   luck, and which knob (drafts vs seasons) is the efficient way to tighten a comparison.
7. **A true ADP baseline** to anchor effect sizes.

## 12. Candidate weaknesses / open challenges (highest-value review targets)

1. **Very small samples.** Every run used only 3 drafts. The tool's own gate calls <3
   drafts "inconclusive," and the 9 seasons per case are dependent. A `lean` verdict on
   9 correlated outcomes is fragile; the point rankings are likely dominated by noise.
2. **Multiple comparisons / winner's curse.** The recommendation selects the best point
   estimate among 3–4 strategies × 2 models. There is no correction for selecting the
   max; the conservative status gate mitigates but does not remove this.
3. **The own-strategy policies are crude proxies** (greedy, top-10/16 window, no
   survival, no opponent modeling, no lookahead), and are **not the live recommendation
   engine**. Conclusions may not transfer to actual draft-day advice.
4. **Opponent models are weakly grounded.** The fitted preference betas are ~0 after
   shrinkage, so "ADP adherence" is the only learned component; the `validated` model's
   fit terms are *prospective* (authored), not fitted. Both models may therefore be
   mis-specified in the same direction, and their 52% roster overlap may not reflect
   true divergence.
5. **The `adp_deterministic` full-season use is structurally wrong** (zero draft
   variance → thinner FA pool, biases against streaming) — acknowledged and labeled, but
   it is included in Run A.
6. **Health/performance model is uncalibrated and has not been validated against real
   injury incidence or box-score distributions.** The injury generator is a heuristic
   onset-per-day process; the 75%/25% injury-vs-rest split and the back-to-back rest
   booster are assumptions that could materially move outcomes.
7. **Waiver/FAB behavior is heuristic** and partly circular: opponents' willingness to
   bid and their streaming cadence are derived from the same screenshots used to define
   the priors, and own `aggressive` streaming may not be a realistic counterfactual.
8. **`protected_core` (top 8 by *initial* value) is frozen all season**, which can block
   legitimate drops and may advantage/disadvantage strategies unevenly.
9. **Single asset scenario.** All runs use one *unverified* hypothetical keeper/owner
   scenario (106/113/123). The recommendation logic treats scenario disagreement as
   `inconclusive`, but no sensitivity across scenarios was actually run, and the current
   scenario is not confirmed.
10. **Projection snapshot risk.** A single 2026-10-11 Hashtag capture drives everything;
    243/430 players lack ADP; capture date is not embedded in the file.
11. **The `projected rank` baseline and the simulated seasons use different schedule
    machinery** (weekly-vs-daily, and the heuristic's playoff factor uses a separate
    playoff-week CSV). The large proj-rank vs sim-rank gap (1.0 → 3.9 in Run A) is partly
    this mismatch plus injury compression; it should not be read as a clean "value lost."
12. **Tiebreaks, IL delay, eligibility-locking, and round-1 keeper/drop-re-add mechanics
    are unverified against Yahoo's actual rules.**
13. **No convergence diagnostics** reported (e.g., MC standard error on the reported
    means beyond the bootstrap interval), and intervals are assumption-conditional.

## 13. Specific questions the reviewer is invited to answer

1. Is the paired, cluster-bootstrap design the right way to compare draft strategies
   here, and is the `strong/lean/inconclusive` gate appropriately calibrated?
2. Given ~9 dependent seasons per case, is reporting a point-estimate "winner" at all
   defensible, or should the tool report only intervals / ranks with explicit ties?
3. How much does the conclusion depend on the (uncalibrated) injury and waiver models?
   What minimal calibration checks would you demand first?
4. Are the two opponent models meaningfully different, or is the 52% shared-roster figure
   misleading because both reduce to "ADP + small tilt"?
5. Is the 0–4 advancement metric better than title rate for this sample size, or does it
   introduce its own distortions?
6. Is the `adp_stochastic` self-baseline a fair "just follow ADP" counterfactual?
7. What is the cheapest change that would most increase confidence in the ranking? (The
   tool's own answer: more **drafts**, not more seasons per draft.)
8. Where are the most likely silent biases — e.g., own `aggressive` streaming applied to
   all strategies, `protected_core`, eligibility locking, or the ADP window cap in the
   heuristic?

## 14. Reproducing / deep-diving

```sh
# Re-run or resume a saved benchmark (regenerates results.json unless cached):
python3 scripts/run_benchmark.py local/draft_benchmarks/<run_id>

# Full test suite (59 tests) and browser checks:
python3 -m unittest discover -s tests

# Persona pipeline (optional online bio refresh first):
python3 scripts/fetch_player_bios.py   # online, optional
python3 scripts/import_history3.py     # local
```

Key source files:

| Concern | File |
|---|---|
| Batch orchestration, paired worlds, summaries, intervals, recommendation | `app/benchmark.py` |
| Job lifecycle, input hashing, resume guard | `app/benchmark_jobs.py` |
| Config validation, calendar, strategy schema, defaults | `app/season_inputs.py` |
| Own draft policies + opponent model routing | `app/season_draft.py` |
| Shared stochastic opponent model, survival MC | `app/draft_model.py` |
| Daily season simulation | `app/season_sim.py` |
| Health/performance world generation | `app/season_world.py` |
| Live valuation, bracket proxy, streaming proxy, recommendation engine | `app/engine.py` |
| ADP-first ordering + missing-ADP fallback | `app/market.py` |
| Three-season persona pipeline | `app/history3.py`, `data/history3/` |
| Data ingestion | `app/data.py` |
| Saved runs | `local/draft_benchmarks/<run_id>/results.json`, `request.json`, `status.json`, `case-*-draft-*-season-*.json` |
| Methodology prose | `SEASON_SIMULATION_README.md`, `data/history3/README.md`, `PLAYOFF_SCHEDULE_README.md`, `SPEC.md` |

**Bottom line for the reviewer.** The tool is carefully built to *avoid* overclaiming —
paired worlds, cluster-aware intervals, an explicit ADP baseline, a measured
model-divergence check, a rejected persona model, and a conservative verdict gate. The
main risks are small samples, uncalibrated injury/FAB mechanics, crude own-strategy
proxies, and weakly-grounded opponent models. The most useful critique would separate
"the design is sound but under-sampled" from "the design has a structural flaw."
