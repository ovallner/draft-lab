# Benchmark hardening — audit, plan, and progress

Companion to `BENCHMARK_METHODOLOGY_SUMMARY.md`. This records the independent
reviews, what the code already does, and the prioritized plan.

Status legend: ✅ done · 🟡 partial · ❌ missing · ⛔ cannot fully validate before the draft.

Guiding objective: a **reliable decision-support tool** that can make the default
recommendation for most picks, explain itself, and **say "inconclusive" when it cannot
distinguish two options**. We optimize for defensible, robust decisions — not for
favourable synthetic championship numbers.

---

## Part A — P0 (DONE)

1. **Championship probability is the primary metric.** `recommendation.metric()` ranks on
   unconditional title rate; advancement → conditional title → qualification are
   supporting. Added `conditional_title_rate`. Paired comparisons test a championship
   difference; `paired_comparisons.supported_improvement` is title-based.
2. **Decisive-outcomes guard.** `MIN_DECISIVE_CLUSTERS = 3`; a lead carried by fewer than
   three decisive draft clusters can only be `lean`. (Note: this is a *floor*, not
   sufficient evidence — see Part G.)
3. **Structural regression tests** (tests/test_season.py): 10 active / 3 bench / 3 IL;
   82-game representation; keeper-forfeiture reconciliation + fail-closed; per-period
   acquisition caps; IL delay + eligibility + capacity; playoff tiebreaks; deterministic
   standings; championship-primary and decisive-cluster recommendation tests.
4. **NBA Cup shortfall represented** (interim): `SeasonInputs` records 80 observed /
   2 unresolved per team and adds the shortfall as seeded extra appearances on existing
   off-days. Also fixed: initial-season injury episodes are now recorded in `world.events`.

Tests: 67 pass (was 59). Browser checks pass. Server verified. Item 4 is explicitly
**interim** and is superseded by the constraint-based generator in Part E.

---

## Part B — Request triage (independent-review refinements)

### P1 — Benchmark the actual live engine
| Request | Status | Evidence / gap |
|---|---|---|
| 1. Headless policy calling `engine.recommend()` | ❌ | `SeasonDraft.pick()` is a greedy proxy; never calls `recommend`. |
| 2. Benchmark and live share selection logic | ❌ | Same as above. |
| 3. Quantify whether pruning/caching changes recommendations | ❌ | No pruning/caching layer exists; no fidelity comparison. |
| 4. Fidelity tests across ≥100 states (early/mid/late) | ❌ | No state corpus or harness. |
| 5. Agreement + utility differences on disagreement | ❌ | — |
| 6. Keepers, unavailable players, traded picks, roster needs | 🟡 | Keepers + drafted are handled in `state`; `traded_flag` exists in `draft_slots.csv`; `need_bonus` covers roster needs. No benchmark-level test of these fixtures. |

### P1 — Competent baseline
| Request | Status | Evidence / gap |
|---|---|---|
| ADP + 9-cat value + positions + balance, no playoff/lookahead | 🟡 | `policy:'fit'` already does ADP-window + category fit + need, with the playoff factor suppressed. Not exposed as a named default. |

### P1 — Decision-level benchmarking
| Request | Status | Evidence / gap |
|---|---|---|
| Regret vs best alternative; stability; suboptimal frequency; survival calibration; candidate-difference uncertainty | ❌ | Nothing exists. Reuses paired-world + `cluster_interval` machinery. |

### P1 — Statistical confidence & design
| Request | Status | Evidence / gap |
|---|---|---|
| Paired championship differences + intervals | ✅ | `_metric_blocks` + `_bootstrap`. |
| Draft-cluster bootstrap | ✅ | `cluster_interval` / `_bootstrap`. |
| ~100 drafts (→500) | 🟡 | `drafts` allows 1–30/batch; runs used 3. |
| Separate tuning vs evaluation seeds | ❌ | Single seed stream. |
| Multiplicity / winner's curse control | ❌ | Point-estimate selection, no correction. |
| MC sampling vs model uncertainty split | 🟡 | Wilson = MC; bootstrap = model-conditional. Not separated/reported as such. |
| Explicit inconclusive | ✅/🟡 | `inconclusive` status exists; "statistically indistinguishable" not yet expressed as a paired-equivalence test. |

### P0/P1 — NBA Cup scheduling
| Request | Status | Evidence / gap |
|---|---|---|
| Constraint-based generator matching the real 8-QF structure | ❌ | Current interim = arbitrary 2 appearances/team. |
| 1230 games / 82 per team / 30 unresolved / no championship game | 🟡 | 82/team achieved; structure, dates, pairing rules, scenario sampling missing. |
| Replace hypothetical with confirmed when announced | ❌ | Not supported. |

### P2 — Simulation realism
| Request | Status | Evidence / gap |
|---|---|---|
| Dynamic (not frozen) protected core | ❌ | Frozen top-8 at draft time (`season_sim` L110). |
| Injury/rest/shutdown sensitivity incl. March | 🟡 | `injury_scale`, `mean_injury_days` exist; no shutdown model, no sweep, no March focus. |
| Streaming/waiver sensitivity incl. FAB aggression | 🟡 | Knobs exist; not swept. |
| Model-uncertainty reporting | ❌ | — |
| Validate vs historical observations | ❌/🟡 | Opponent selection validated; availability/churn not. |

### P2 — Opponent-model stress testing
| Request | Status | Evidence / gap |
|---|---|---|
| Strongly-ADP / category-aware / reach-prone / keeper-upside environments as sensitivities | 🟡 | `adp_stochastic`, `validated`, `fit`, `adp_deterministic` exist; no explicit reach/keeper-upside knobs; not framed as opponent environments. |

---

## Part C — Effort and compute estimates

Measured baseline: **`engine.recommend()` ≈ 9 s/call** on a fresh state (46 punt builds
screened, 24 candidates, 2 market orders, survival MC). This dominates all live-engine work.

| Workstream | Effort | Compute | Draft-night value |
|---|---|---|---|
| Headless `live` policy + state threading | M (2–3 d) | ~10 calls × 9–30 s ≈ **1.5–5 min per draft** | **High** |
| Shared-logic guarantee + policy=engine equality test | S (0.5 d) | negligible | High |
| Pruning/caching + fidelity quantification | M (1–2 d) | corpus runs | High |
| ≥100-state fidelity harness (early/mid/late) | M (1–2 d) | ~100 recommends × 2 impls ≈ 30–60 min | High |
| Competent baseline (`fit` surfaced/strengthened) | S (0.5 d) | cheap | High |
| Decision-level benchmark | L (3–5 d) | states × candidates × paired drafts | High |
| 100 drafts + seed separation + multiplicity + MC/model split | M (2–3 d) | live: **100 drafts × ~2.5 min ≈ 4 h** single-thread; proxies far cheaper | High |
| NBA Cup constraint-based generator + validation | M–L (2–4 d) | trivial runtime | Medium |
| Dynamic protected core | M (1–2 d) | modest sim overhead | Medium–High |
| Injury/rest/streaming/opponent-env sensitivity | M (2–3 d) | 1–2× sim per scenario | Medium |
| Empirical validation/calibration | L, ongoing | external data | Medium |

Compute reality: full-season simulation with the **live** policy is minutes/draft, not
seconds. 100 drafts is an overnight job; 500 is a background multi-night job. Proxies
stay cheap and are used for breadth; the live policy is used for the headline comparison.

---

## Part D — Smallest sequence to reliable draft-night recommendations

**Step 1 (critical path) — Live policy, competent baseline, fidelity.**
1. Add a benchmark own-policy `live` that maintains a working draft `state` and calls
   `engine.recommend(state)`, taking the top recommendation (falls back to the `fit`
   baseline if recommend returns nothing).
2. Assert **shared selection logic**: a test that the `live` policy's chosen player equals
   `engine.recommend(same_state)['recommendations'][0]['player']`.
3. Time recommend across round phases; if needed, add candidate pruning / per-state
   caching **behind a flag**, and quantify top-1 agreement and utility delta vs the
   unpruned call on the state corpus.
4. Build the ≥100-state corpus (early/mid/late, keeper-heavy, post-run, positional-need)
   and the fidelity harness (top-1/top-5 agreement, score deltas, disagreement utility).
5. Surface `fit` as a named default **competent baseline**; keep `adp_stochastic` too.
6. Compare live vs both baselines on paired drafts/seasons, championship-primary.

**Step 2 — Decision-level benchmarking + statistical confidence.**
7. New decision-level module: for representative states, live pick + credible
   alternatives → paired remaining-draft completions → paired season sims → expected
   regret, stability across assumptions, suboptimal frequency, survival calibration,
   candidate-difference intervals.
8. Raise default drafts toward **100**; add **tuning vs evaluation seed separation**;
   multiplicity/winner's-curse control; MC-vs-model uncertainty split; paired-equivalence
   "indistinguishable" outcome.

**Step 3 — NBA Cup constraint-based scheduling** (Part E) — take it now because it is
bounded and independent, and the current interim approximates daily congestion,
**but only after Step 1**.

**Step 4 — P2 realism:** dynamic protected core; injury/rest/shutdown + streaming/waiver
sensitivity with a March focus; opponent-environment stress scenarios; model-uncertainty
reporting.

**Step 5 — Empirical validation/calibration** (ongoing).

Calendar note: draft is **Oct 18**. Steps 1–2 are the realistic critical path; Steps 3–5
are improvements that may land partially. Treat Step 1 as must-have and Step 2 as
strongly-desired; do not let Step 3+ delay them.

---

## Part E — NBA Cup scheduling spec (Step 3)

Replace the interim 2-appearances/team with a **constraint-based generator**.

Facts (2024/2025 structure, 2026 dates):
- Initial schedule: 80 games/team. Two games/team unassigned (30 total).
- 8 quarterfinalists; 22 non-qualifiers get their 2 games as normal regular-season games.
- 4 QF losers get a replacement game; 4 semifinalists get their 2 via QF/SF.
- **Championship game is excluded** from regular-season/fantasy stats.
- Cup window: group play ends Nov 27; QF Dec 4–5; SF Dec 8–9; final Dec 11 — all inside
  the 14-day Yahoo **Week 7**.

Generator requirements:
1. Preserve the 1,200 confirmed fixtures unchanged.
2. Generate exactly **30** additional two-team matchups.
3. Eight-team QF structure; 22 non-qualifiers get 2 games; QF losers get 1 replacement;
   QF/SF count as regular-season.
4. Exclude the championship game.
5. Confine added games to plausible dates in the Dec 4–10 window.
6. No team twice on one day; no self-matches; no duplicates; existing fixtures respected.
7. Prefer conference/group pairing, back-to-back avoidance, and home/away balance.
8. Deterministic given a seed; **sample multiple valid scenarios** across simulations
   (schedule uncertainty becomes an explicit scenario axis).
9. Label every generated fixture as **hypothetical**, and allow confirmed NBA fixtures to
   replace hypothetical ones when announced.

Validation (fail-closed):
- Exactly **1,230** regular-season games; exactly **82** per team; exactly **30**
  unresolved represented; no duplicate/impossible/self-matched games; no championship
  game in fantasy production.

Priority note from the review: all missing games fall in one extended December week, so
**weekly volume and plausible daily congestion** matter more than predicting which teams
reach the semifinals. Keep the generator simple and labelled.

---

## Part F — Decision-level benchmark spec (Step 2)

For representative intermediate states:
1. Live top recommendation.
2. Credible alternatives (next-k by live score + ADP-adjacent + need-filling).
3. From each candidate, complete the remaining draft under **paired** random scenarios
   (same seeds/worlds across candidates).
4. Evaluate resulting rosters with comparable season simulations.
5. Expected opportunity cost (regret) = primary-metric difference vs the strongest tested
   alternative.

Report: estimated regret vs best alternative; recommendation stability across plausible
assumptions; frequency of materially suboptimal selections; **calibration of player
survival probabilities**; uncertainty in candidate differences. Explicitly do **not** reuse
the same evaluation results to tune a strategy and then claim independent validation
(seed separation, Part G).

---

## Part G — Statistical design spec (Step 2)

- Keep paired simulations + draft-cluster bootstrap.
- **≥100 independent drafts** as the initial target, toward 500 if conclusions stay
  ambiguous and compute allows. Treat these as targets, not power guarantees.
- **Separate tuning and evaluation seeds**; freeze evaluation seeds before final runs.
- Paired **championship-rate** differences + intervals (advancement/qualification/cond.
  title supporting).
- **Multiple-comparison / winner's-curse control** across the strategy set (e.g. max-stat
  paired bootstrap or step-down/Bonferroni-style adjustment), so "best of N" is not read
  as reliable on the raw point estimate.
- Report **Monte-Carlo sampling error** separately from **model/assumption uncertainty**.
- Explicit **inconclusive / statistically indistinguishable** verdict via a paired
  equivalence check, not just a missed interval.
- The 3-decisive-cluster rule is a **floor**, not sufficient evidence.

---

## Part H — Assumptions that cannot be validated before Oct 18 (⛔)

- Injury onset/severity/duration calibration and March availability.
- Rest/shutdown behavior and late-season role changes.
- FAB bidding aggression and waiver-processing timing.
- Exact Yahoo tiebreak, lock, and eligibility mechanics.
- Yahoo ADP measurement date and the 243/430 missing-ADP fallback.
- Actual NBA Cup participants and the 30 remaining fixtures.
- True opponent draft behavior (personas failed; environments remain hypotheses).
- Successful-acquisition counts and ending FAB balances (only weak ordinal priors).
- Whether the single 2026-10-11 projection snapshot matches draft-day reality.

These are labeled and stress-tested, **not** resolved. Decisions should stay robust when
they are varied (Step 4).

---

## Part I — Step 1 progress (live engine, competent baseline, fidelity)

**DONE**

- **Headless `live` policy** (`SeasonDraft.pick_live` + `complete`): maintains a working
  copy of the board and drafts by calling **`engine.recommend()`** on each of our turns.
  Benchmark and live share one implementation by construction — there is no second
  selector to drift. It records the punt build the engine actually chose.
- **Competent baseline** surfaced as a default named strategy: `policy:'fit'`
  (ADP market window + nine-category value + positions/balance, no playoff optimization,
  no lookahead). Default comparison set is now:
  `Live recommendation engine`, `Competent ADP+fit baseline`, `Pure ADP baseline`,
  `Balanced playoff fit`.
- **Shared-logic + fail-closed test**: the `live` policy's pick must equal a direct
  `engine.recommend()` call on the same board; `recommend` must be deterministic on a
  fixed board; unresolved keeper/draft assets still raise `Cannot complete`, never
  invented. (Passing.)
- **Timing harness** `scripts/benchmark_fidelity.py` (read-only).
- **Determinism confirmed**: `engine.recommend()` is deterministic given a board
  (survival MC is seeded from a hash of the state).

**Measured timing** (unpruned, authoritative `engine.recommend()`, ~46 punt builds /
~25–30 candidates / 2 market orders):

| Phase | n | recommend() median | range |
|---|---:|---:|---|
| Early (R1–5) | 3 | 10.9 s | 10.8–12.5 s |
| Middle (R6–10) | 5 | 9.6 s | 8.1–9.8 s |
| Late (R11–13) | 2 | 5.1 s | 3.0–7.3 s |
| Overall | 10 | 9.7 s | — |

Projected **live-arm draft cost ≈ 1.5 min/draft** (≈10 owned picks). Therefore:
- **No pruning is required** for the 100-state corpus (~16 min) or a ~100-draft live arm
  (~2.5 h, overnight). The optional pruned path is **not** wired/was not needed.
- Pruning becomes worthwhile only for 500-draft-scale live runs; defer unless needed
  (and, if added, gate behind a flag and re-run this harness for top-1/utility fidelity).

**100-state corpus** (12 independent drafts × user slots, early/middle/late, keeper
boards; unpruned authoritative `engine.recommend()`):

| Phase | n | median | min–max |
|---|---:|---:|---|
| Early (R1–5) | 30 | 13.4 s | 11.2–20.3 s |
| Middle (R6–10) | 50 | 11.1 s | 6.7–14.9 s |
| Late (R11–13) | 20 | 6.1 s | 2.8–12.1 s |
| **Overall** | **100** | **11.4 s** (mean 10.8 s) | total 18.1 min |

Builds ≈ 46 and candidates ≈ 28–30 per call in every phase. Shared-logic and
determinism checks passed. Implied live arm ≈ **1.8 min/draft → ~100 drafts ≈ 3 h**.

**Caveat:** the corpus ran concurrently with other CPU work (a full live draft + the
test suite), so these timings are an upper bound; a clean single-draft probe gave ~9.7 s
median. Either way the conclusion holds.

**Conclusion for Step 1:** the authoritative engine is affordable at the 100-draft target
with **no pruning**; keep the full engine as reference. Pruning is deferred to a possible
500-draft live arm, and any pruning must be flag-gated and re-checked here for top-1
agreement and utility loss (especially on high-leverage early picks).

**Limitations (carried forward)**

- Late-round `recommend()` is cheaper but still seconds; a large **mixed** batch (live +
  3 baselines × 2 models) is dominated by the live arm.
- `recommend()`'s internal lookahead uses its own opponent model (default `fit`), which
  is not forced to equal the benchmark's `opponent_mode`. This matches "what the live
  tool would do," but the two are deliberately independent — flagged for Step 2.
- The `live` policy ignores per-strategy `punts`/`risk`/`playoff_weight`; those knobs
  apply only to the heuristic baselines.
- Corpus timing is from the confirmed-asset hypothesis scenario; the four unresolved
  assets are exercised only through the fail-closed path.

## Part J — Guardrails


- Never present a strategy as a reliable winner from a few outcomes; prefer `inconclusive`
  and show tradeoffs when candidates are indistinguishable.
- Do not tune and validate on the same results.
- Do not optimize for favourable synthetic championships; the test is whether the live
  engine makes defensible, robust decisions that beat realistic alternatives.
- Keep every hypothetical (generated fixtures, distributions, environments) clearly
  labelled and replaceable when real data arrives.

---

## Step 2 progress (seed separation, decision-level, statistics)

**Implemented**

- **Separated seed blocks** (`app/seeds.py`): `exploration` vs held-out `evaluation`,
  with a `holdout` version. Draft and world seeds derive from the block, so competing
  strategies and candidate selections stay paired inside a block, and evaluation seeds
  never overlap exploration. Recorded in run metadata. If a holdout result later informs
  code changes, bump `holdout` before any new claim (documented in the module).
- **Statistics**: paired intervals are now **multiplicity-adjusted** (widened by the
  number of challengers compared to the winner). Reported uncertainty is split into a
  **draft-cluster (model/draft) interval** and a **season-level (Monte-Carlo) interval**.
  A new **`indistinguishable`** verdict returns `inconclusive` when the winner's paired
  interval sits inside ±5 title-rate points, instead of implying precision.
- **Decision-level benchmark** (`app/decision.py`, `scripts/run_decision_benchmark.py`):
  a 50/50 `fit`/`live` trajectory corpus stratified by phase, with stress flags
  (`deep_round`, `no_center`, `unexpected_availability`). Each state evaluates the
  engine's top pick and alternatives by **paired completions** (a common continuation
  policy) on **shared season worlds**, clustered by source draft. It reports regret,
  stability, material-suboptimal frequency and **survival calibration** via an
  independent completion path.
- **`first_pick`** counterfactual support in `SeasonDraft.complete`; fail-closed retained.

**Decision-level results** (49 states, 5 source-draft clusters, 3 candidates each,
4 seasons/candidate, `fit` continuation, `adp_stochastic` opponents; compute build
204 s + eval 2612 s, contended):

| Quantity | Value | 95% cluster interval |
|---|---:|---|
| Regret vs best-tested (upper bound, biased) | 0.158 | [0.120, 0.220] |
| **Chosen − mean(alternatives)** (unbiased) | **−0.010** | **[−0.059, +0.031]** |
| Chosen − #2 | −0.020 | [−0.075, +0.036] |

The naive "best of the tested alternatives" regret (0.158) is almost entirely
**selection bias**: the unbiased paired read says the engine's top pick is
**statistically indistinguishable from its own alternatives**. 40.8% of states have the
chosen behind the alternatives' average, but the interval spans zero. By phase, naive
regret is larger early (0.20) than late (0.075). **Conclusion: at the decision level the
engine's top few options are near-equivalent — it should (and now does) say so rather
than imply precision.**

**Survival calibration** (independent completion path): mean bias −0.19, mean absolute
error 0.22 — the engine **moderately over-predicts** survival-to-next-pick. Worst bin:
predicted 0.8–1.0 → observed 0.72; predicted 0–0.2 → observed 0.00 (conservative there).

**Compute / production window**: `engine.recommend()` ≈ 10 s per call uncontended (this
run contended), comfortably inside the 45 s live selection window.

**Headline (main question) status**: the 100-draft **held-out evaluation-block** run of
`live` vs the competent ADP+fit baseline (and pure-ADP / balanced) is running in the
background; its paired championship-rate result is appended when it completes.

**Limitations carried forward**

- Regret's "best tested" is upward-biased by selection; always read the unbiased
  chosen-vs-alternatives interval alongside it.
- Only 5 source-draft clusters here; adequate to show *indistinguishability*, not to
  resolve small differences (expand drafts/clusters).
- Decisions use a `fit` continuation; live-continuation and opponent-environment
  sensitivity are the next arms.
- One explicitly-resolved asset scenario only; additional keeper configurations need
  additional named, internally-consistent scenarios (never invented).

