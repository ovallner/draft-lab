# Season strategy laboratory

A background batch job that drafts the league under several of **your** strategies,
then plays out several full synthetic seasons per draft. Its purpose is to compare
draft strategies before draft day — not to produce real championship odds.

Launch it from the **Season lab** tab. It runs in a separate process so live pick
recording is never blocked. Reproduce or resume any saved run from the command line:

```sh
python3 scripts/run_benchmark.py local/draft_benchmarks/<run_id>
```

## What it does, in order

1. **Freezes an immutable snapshot** of the current draft setup plus your strategy
   list, opponent models, season assumptions, and named asset scenarios. Input file
   hashes (code and data) are recorded. A resume refuses to mix changed inputs.
2. **Drafts** the league 12 teams × 13 rounds. Your picks use a transparent bounded
   heuristic (adaptive punt detection, marginal category value, GP/playoff weighting,
   positional need). Opponents use the selected model. Strict ADP is deterministic.
   Your own strategies may also use non-heuristic policies:
   - **`adp_stochastic` — the performance baseline.** You draft as a *pooled
     ADP-driven manager*: picks are drawn from the same conditional-choice model the
     opponents use, with no roster-fit or playoff reasoning. It is the honest
     "what if I just followed ADP" comparison, and it is deliberately stochastic
     rather than a zero-variance always-best-ADP bot.
   - **`adp`** — deterministic best-available ADP (zero variance), useful as a
     stylised control but not a realistic opponent or self model.
   - **`fit`, `playoff`, `auto_punt`** — the optimizing heuristics above.
   A per-manager override may also name `adp_stochastic`, in which case that manager
   is drawn from the same model rather than the heuristic.
3. **Projects** post-draft strength: expected category totals from healthy
   `projected_gp/82` availability with no acquisitions. This is the "projected rank."
4. **Plays seasons.** Each draft gets `seasons_per_draft` independent synthetic
   seasons. Health and performance "worlds" are paired across every strategy and
   scenario, so differences reflect strategy rather than random luck.

## Projected vs simulated

The **Projected rank** column is the post-draft baseline (assumes healthy rosters,
no moves). The **Simulated** columns are the realized outcomes of the simulated
season, where synthetic injuries, waiver/streaming competition, and daily lineup
decisions drive the result. The gap between them is the interesting part.

## Season mechanics modeled

- **Daily lineups** with real NBA game dates; blocked bench games are counted.
- **Injuries** as synthetic Markov episodes calibrated to `projected_gp/82`, plus
  isolated rest/absence days. 75% of the expected missed-game burden is attributed
  to injury episodes (scaled down for low-minutes role players), the rest to rest.
  A configurable delay gates IL eligibility for multi-week episodes.
- **Three IL slots** per team; healthy players must be activated into an open slot
  or dropped. Ineligible/locked managers do not release players into the pool.
- **Shared free-agent competition.** Managers bid against one another for the same
  players. Dropped players wait a configurable number of days (default two). Bids
  use FAB; unsuccessful bids consume neither acquisition nor budget. A seeded
  initial rolling waiver order is used for ties.
- **Four acquisitions per scoring period** (eight for long periods if enabled).
- **Streaming behavior** comes from your strategy (aggressive/observed/injury-only/off)
  and from shrunk observed activity priors transcribed from last season's
  transaction screenshots, with separate championship vs placement context.
- **Performance** uses coherent sampled shooting counts with shared minute/weekly-form
  variability, so ratio categories stay internally consistent.
- **Fixed playoffs:** 8 teams, weeks 18–20, no reseeding, deterministic 1–8/4–5/2–7/3–6
  bracket. Category ties fall back to regular-season head-to-head, then higher seed.
- **Standings tiebreaks:** category win percentage, then head-to-head category
  percentage, then last-period percentage, then a seeded lottery.

## Opponent draft models

`adp_stochastic` (**recommended primary** — pooled learned ADP adherence, sampled),
`validated` (that plus a modest roster-fit tilt; sensitivity), `fit`, and
`persona_experimental` (n=1 season, may overfit; sensitivity). Individual managers can
be overridden with a model name or a full strategy object.

`adp_deterministic` (strict ADP) is retained only as a labeled **compressed-variance
baseline**. It is structurally wrong for season simulation: it has zero draft-to-draft
variance, so it roughly halves the spread of team strength and leaves a thinner
free-agent pool — which biases comparisons *against* streaming and variance-exploiting
strategies. Use it to confirm a result is not an artifact of draft randomness, not as
the headline model.

## Recommendation

Every run ends with one transparent call. It is chosen on the **primary model**
(`adp_stochastic`, or the most preferred model you selected) and then **stress-tested
for agreement** on the other selected models. Models are **never averaged or weighted**:
their relative realism is unvalidated, so robustness is established by agreement
instead — **but agreement only counts when the models genuinely differ.** The
recommendation measures the shared-roster share between the compared models; at
~50% (what `adp_stochastic` vs `validated` actually produce) agreement is meaningful,
and if the models are near-duplicates the verdict is capped at `lean` with an
instruction to add a structurally different model.

Strategies are graded on **unconditional championship probability** — the primary
objective. Advancement (0 missed → 1 quarterfinal → 2 semifinal → 3 final → 4
champion), conditional title probability (titles ÷ qualifications) and qualification
rate are reported as **supporting** metrics. The status is deliberately conservative:

- **strong** — leads the primary model on championship probability, the paired title
  gap's draft-cluster interval excludes zero, the lead is carried by at least three
  decisive draft clusters, the models genuinely differ, and the same strategy wins on
  every selected opponent model.
- **lean** — leads on the primary model but flips on another model, has a paired
  interval that still includes zero, rests on fewer than three decisive draft clusters
  (a lead driven by one or two simulated titles), or was only checked against
  near-duplicate models.
- **inconclusive** — the best strategy differs by asset scenario, or fewer than three
  drafts per case.
- **baseline** — only one strategy was tested.

Each run also reports a **variance split** (draft-to-draft vs season-to-season). Since
manager personas failed validation, outcome spread now comes from draft and season
luck rather than opponent identity; the split says which dominates. Note that adding
**drafts** always shrinks both variance components while adding **seasons per draft**
shrinks only one, so drafts are the more efficient way to tighten a comparison.

Confidence in the recommendation is not confidence in the number: it only means the
point ranking is stable, the models genuinely differ, and the interval excludes zero —
not that the strategy is truly best.

## Reading the output

- Rows are separate **asset-scenario × opponent-model** groups. They are **not**
  weighted or averaged together.
- **Paired differences** compare each strategy against the first strategy in the
  same group, over identical worlds.
- Intervals resample whole **drafts** (not independent seasons). With fewer than
  three drafts the interval is deliberately uninformative. `supported_improvement`
  requires a strictly positive lower bound.
- The `distinct own rosters` count warns when strict-ADP opponents make every draft
  identical (then only `seasons_per_draft` adds information).
- Per-season detail files in the run folder retain every team's transactions and
  simulated injuries.

## Hard requirements and fail-closed behavior

- The daily NBA schedule, the fantasy matchup pairs, and full asset reconciliation
  are required. The daily fixture feed omits NBA Cup "to be announced" placeholders
  (80 games/team); the per-team shortfall is represented **explicitly** as extra
  appearances on existing regular-season league game-days (seeded per team, no
  matchups invented), so the full 82-game slate is modeled rather than silently
  understated. Unresolved owners at **#106 / #113 / #123** or unassigned Nick/Samet
  keeper assets stop the run with a clear message. Supply a complete, explicitly
  named hypothetical scenario, or correct the board — nothing is guessed.
- The scoring **calendar dates are verified** from Yahoo official Important Game
  Dates (`fantasy_league_2026_27_schedule_with_dates/fantasy_week_calendar.csv`) and
  cross-checked against every matchup row. Weeks 1–20 are simulated; Weeks 21–23 are
  post-league. You may override the dates, but an override needs its own provenance
  string. W1 is 6 days; W7 (NBA Cup) and W17 (All-Star break) are 14-day periods
  holding only 6 and 8 NBA game-days — long periods are not more games.
- The population is restricted to imported projections. Unprojected players cannot
  be invented.

## Known limitations (do not over-read the numbers)

- **Not calibrated.** Injury rates, durations, FAB behavior, waiver processing
  clock, and lock interpretation are assumptions. Simulated title frequencies are
  not real-world probabilities. Use sensitivity runs.
- No fantasy/NBA trades, no schedule revisions, no injury-driven teammate role
  promotion, no speculative injured-FA stashing, fixed NBA teams.
- Small batches cannot determine a robust best strategy. Treat "best" only when a
  paired interval excludes zero across several drafts.
