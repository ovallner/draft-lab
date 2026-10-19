# Pick #6 Decision Lab + draft-night preparation — implementation plan

Companion to `BENCHMARK_ACTION_PLAN.md`. Goal: maximize confidence in the **#6 pick**,
then use the long gap before **#43** productively — while reusing the production engine
and never contaminating the held-out 100-draft benchmark.

Context (12-team snake, we draft **#6**; keepers forfeit **R2, R3, R12**):
owned live picks are **#6, #43, #54, #67, #78, #91, #102, #115, #126, #150** (10 picks)
plus 3 keepers. After #6 we wait 36 opponent picks until #43, then #54.

## 1. Reuse audit (build almost nothing new)

| Need | Reuse | Notes |
|---|---|---|
| Production recommendation | `engine.recommend(state)` | Canonical. Do **not** write a second selector. |
| Availability forecast | `draft_model.survival` (used inside `recommend`) | Already MC-based; expose directly. |
| Force a candidate then continue | `SeasonDraft.complete(..., first_pick=...)` | Already added in Step 2; forces our pick, then continues with any policy (incl. `live`). |
| Candidate evaluation | `app/decision.py` `candidates()/evaluate_state()/survival_check()` | Paired completions, shared worlds, cluster bootstrap. Extend to a **fixed candidate list**. |
| Paired season worlds | `SeasonWorld` + `SeasonSimulator` | Worlds are board-independent → cacheable and reusable across candidates. |
| Separated seeds | `app/seeds.py` | Add a `production-lab` namespace, disjoint from `exploration`/`evaluation`. |
| Statistics | `benchmark._bootstrap`, `_season_bootstrap`, equivalence margin, decisive clusters | Championship-primary, multiplicity-adjusted. |
| Background jobs | `app/benchmark_jobs.py` (subprocess, `cancel.request`, resume, input hashes) | Same pattern for #43 prep. |
| Live board / persistence | `app/store.py` | Board hash for cache keys. |

**Genuinely new (small):** a fixed-candidate lab runner, a cache layer, a #43 background
job, and UI panels. No new recommendation algorithm.

## 2. Computational cost (measured)

- `engine.recommend()` ≈ **10 s/call** (≈25–30 candidates, ~46 builds).
- Our #6 lab forces #6 and continues with the live engine: **≈ 9 further calls ≈ 90–120 s
  per candidate-evaluation** (one continuation draft). Season sims add ~1 s each and share worlds.
- Cost scales as `candidates × opponent_models × paired_drafts` (season worlds are shared).

Proposed budget (well inside 6 days):

| Stage | Scope | Continuations | Wall time |
|---|---|---|---|
| Broad | ~12 candidates × 1 model × 4 paired drafts | 48 | ~1.5 h |
| Deep | top ~5 × 3 models × 8 paired drafts | 120 | ~3.5 h |
| Contingency | 2–3 fall-elite × 3 models × 8 | ~60 | ~2 h |

Run as an overnight background job; **adaptive allocation** (broad first, concentrate on
close/promising candidates). Season worlds generated once and reused.

## 3. Cache design

Two namespaces, because some work is board-independent:

- **`model_key`** = sha256(projections sha256 + keepers + asset scenario + calendar sha256
  + `input_hashes` of code). Board-**independent**. Changing projections/keepers/scenario/
  code invalidates everything.
- **`board_key`** = sha256(canonical drafted set + our keepers + current slot + punt/risk
  settings). Board-**dependent**.

Cache artifacts (`local/decision_cache/`):
- **Worlds** `(model_key, world_seed)` → reusable where `model_key` holds; independent of the board.
- **Continuations** `(model_key, board_key, candidate_id, opponent_mode, continuation, seed)` → rosters.
- **Season outcomes** `(continuation_key, world_key)`.
- **Aggregates** `(model_key, board_key, candidate set, assumptions)`.

Rules: a `model_key` change **invalidates all**; a `board_key` change invalidates
availability/opportunity-cost/continuations but **keeps worlds**. Every artifact records
`model_key`, `board_key`, `created_at`, and is tagged **precomputed vs fresh** in the UI.
Never reuse an artifact whose key changed.

## 4. Background preparation for #43 / #54

- **Trigger:** when our #6 pick is recorded (board event).
- **Job:** reuse the `benchmark_jobs` subprocess pattern — cancellable, **low priority**
  (`nice`), never blocks or slows the server.
- **Produces:** availability forecast at #43 on the actual board; #43 candidate
  evaluations conditioned on our real #6; wait-to-#54 opportunity cost; promising
  #43/#54 combinations; how the preferred category build changes with who survives.
- **Incremental:** each opponent pick updates the cheap availability forecast
  immediately; heavy continuations are recomputed only when the board change invalidates
  their `board_key`. Cancellation + resume supported.
- **At #43:** the **authoritative** `engine.recommend(actual board)` runs live; cached
  research **supplements** (explains, compares), never overrides fresh info.

## 5. Draft-night presentation

- **#6 shortlist**: ranked candidates with paired championship rate + interval, category
  build implications, the assumptions that could flip the order, and a **contingency** row
  for an unexpected elite fall (Jokic / Wembanyama / Dončić etc.).
- **Evolving #43 shortlist** with likely #54 follow-ups and the tradeoff of waiting.
- **Precomputed vs live** badges on every row.
- **Equivalence-aware wording**: when the interval sits inside the ±5-point margin, show
  "statistically equivalent" and the tradeoffs, not a false ranking.

## 6. Validation and limits

- The lab is **decision support, not calibrated odds**; state it on every panel.
- Don't name a #6 winner when candidates are within model uncertainty.
- Sensitivity: opponent behavior (ADP-driven / category-aware / reach-prone),
  projection snapshot, March availability.
- Fall-elite contingency is preserved, not dismissed.

## 7. Interaction with the held-out benchmark

- Use a **`production-lab` seed namespace** disjoint from `evaluation`. Decision-lab
  outputs are **never** used to tune the engine and never feed claims of validated
  improvement. The 100-draft holdout continues untouched.

## 8. Sequenced plan (given ~6 days to Oct 18)

1. **Must** — fixed-candidate lab runner reusing `decision.py` + `SeasonDraft(first_pick=…)`
   + `seeds` + `SeasonWorld`; broad→deep; emits shortlist JSON. (~1 day)
2. **Must** — #6 shortlist report/panel with category builds + contingency. (~0.5 day)
3. **Should** — cache layer (worlds first; then continuations/aggregates). (~1 day)
4. **Nice** — #43 background prep job + evolving panel. (~1 day)
5. **Nice** — presentation polish (badges, tradeoff wording).

Everything is additive; the production engine and the held-out evaluation are untouched.
