# Pick #6 — focused tradeoffs: KAT vs Mobley vs Sengün

Scope: the smallest practical head-to-head the review asked for, plus the requested
verification checks. No engine changes; the current held-out benchmark was not touched.
Pairing note: a paired head-to-head (KAT/Mobley/Sengün) is running on the same draft
seeds and season worlds as the deep Pick #6 run; its numbers are appended below.

## 1. Category math — verified correct (review item 3)

| Check | Result |
|---|---|
| FG% uses aggregate makes/attempts | `aggregate` returns `fgm/fga`; 4/10 → 0.40. ✓ |
| FG% comparison is ratio, not make-count | 4/10 (40%) vs 3/6 (50%) → **50% wins** (−1). ✓ |
| FT% same | 8/10 vs 6/10 → 8/10 wins (+1). ✓ |
| TO sign convention | TO 5 vs 3 → **fewer TO wins** (−1); `engine.raw` returns the TO column negated (−5 for a 5-TO line). ✓ |
| Zero-attempt ties | both 0 attempts → tie (0). ✓ |

So the make/attempt aggregation and the "lower TO is better" convention are correct
throughout `aggregate`, `compare_categories`, `engine.raw`, and the matchup sim.

## 2. Individual contribution ≠ completed-roster strength (review item 4)

The raw lab reports' "strengths/weaknesses" are computed over **one simulated 13-man
continuation roster** — they are *not* the player's contribution, and they vary run to run.
Use each player's **own per-game category z** here (reliable), and read the roster lines as
illustrative only.

| Player | FG% | FT% | 3PM | PTS | REB | AST | STL | BLK | TO |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **KAT** | +0.7 | +0.9 | −0.0 | +0.8 | **+2.3** | −0.2 | −0.4 | −0.2 | −0.8 |
| **Mobley** | **+1.3** | **−2.0** | −0.6 | +0.4 | +1.4 | −0.1 | −0.7 | **+2.1** | −0.2 |
| **Sengün** | +0.6 | −1.8 | −1.3 | +0.7 | +1.6 | **+0.9** | +0.5 | +0.5 | −1.4 |

Keeper core (SGA/Mitchell/George): strong FT% (+3.4), PTS (+3.8), STL (+3.2), 3PM (+2.1),
AST (+1.9); weak REB (−1.7), FG% (−0.5), BLK (−0.1).

- **KAT** is the only one of the three who adds **REB (+2.3)** *without* an FT% or 3PM
  penalty — a near-frictionless fit.
- **Mobley** adds the most **FG% (+1.3) and BLK (+2.1)**, but at **FT% −2.0** — a real cost to
  a core strength.
- **Sengün** adds **REB (+1.6), FG% (+0.6), AST (+0.9), STL/BLK (+0.5)** with **FT% −1.8** —
  the most *balanced* big, closest to Mobley's big-man value with extra playmaking.

**No punt is assumed.** The head-to-head lets the production engine choose balanced,
one-punt, and two-punt builds per draft and reports which it selected; the punt label is the
engine's *output*, not a constraint we imposed.

## 3. Playoff scheduling by week (review item 6)

Usable games matter most in **championship week (w20)**.

| Player | Team | w18 | w19 | **w20 (champ)** |
|---|---|---:|---:|---:|
| KAT | NY | 3 | 3 | **3** |
| Mobley | CLE | 3 | 4 | **3** |
| Sengün | HOU | 4 | 3 | **3** |
| Ausar Thompson | DET | 3 | 4 | **3** |

None of the three has a light championship week (all 3 games), so scheduling does not break
the tie. Full-roster weekly congestion (not just the candidate) still matters and is handled
inside the season simulation.

## 4. Ausar Thompson availability at #43 / #54 (review item 5)

From the **keeper-adjusted pool** (36 keepers removed), via the engine's survival Monte
Carlo (400 trials; model estimate):

| Horizon | P(available) | Wilson 95% |
|---|---:|---|
| #43 | 0.98 | [0.96, 0.99] |
| #54 | 0.98 | [0.95, 0.99] |

Consistent with his **ADP 81** (he is typically taken ~81st, i.e. *after* #43), so he is
likely still there at #43/#54. **But do not treat him as guaranteed:** the engine modestly
**over-predicts survival** (survival-calibration bias ≈ −0.19), so the real availability is
somewhat lower than 0.98. Treat him as a strong, not certain, #43 target.

## 5. Tradeoff summary (deterministic)

- **KAT** — cleanest fit (REB + FG% with no FT%/3PM cost); lowest downside. Fits any
  construction; **directionally favored** (a directional read, not an established edge — see §6).
- **Sengün** — balanced big: REB/FG/BLK plus AST; costs FT%. Best if you want interior value
  without fully committing to a FT% punt.
- **Mobley** — highest ceiling on FG%/BLK but the largest FT% cost; makes most sense if you
  deliberately soft-punt FT% (or pair him with high-FT% guards later).

Which is best depends on the **later-round pool** you actually face — the head-to-head below
lets the engine choose the construction rather than assuming a punt up front.

## 6. Paired head-to-head (corrected run — completed)

4 drafts × 2 opponent models × 3 seasons per candidate, **distinct season worlds per draft**,
plus a **confirmation pass on fresh worlds**; paired differences clustered by draft. Smallest
non-zero step ≈ 8 points (4 clusters × 3 seasons), so intervals are coarse.

Championship rate by model:

| Model | KAT | Mobley | Sengün |
|---|---:|---:|---:|
| adp_stochastic | 17% | 17% | 0% |
| validated | 25% | 17% | 17% |

Paired differences (A − B), **primary → confirmation**:

| Pair | adp_stochastic | validated |
|---|---|---|
| KAT − Mobley | +0.0 [−25,+25] → +16.7 [+0,+33] | +8.3 [+0,+25] → +16.7 [+0,+33] |
| KAT − Sengün | +16.7 [+0,+33] → +16.7 [+0,+50] | +8.3 [+0,+25] → +16.7 [−17,+33] |
| Mobley − Sengün | +16.7 [+0,+50] → +0.0 [−25,+25] | +0.0 [+0,+0] → +0.0 [−25,+25] |

Engine-chosen builds varied across drafts (no punt assumed): KAT {3PM, AST, FG%, balanced},
Mobley {3PM, AST, BLK, FT%, PTS, REB, balanced}, Sengün {3PM, AST, REB, balanced}.

**Reading (honest):**

- **KAT is directionally favored:** it is never behind Mobley or Sengün in any of the 8
  model × pass comparisons (every paired delta ≥ 0), and its point estimate leads the
  `validated` model (25% vs 17%). A *directional* read — not an established edge.
- **Mobley vs Sengün goes from positive to tied** — positive on the `adp_stochastic` primary
  pass, then tied in all three other passes. It does **not** reverse sign.
- **The confirmation pass re-uses the same four draft completions per model** and only draws
  **fresh season worlds**; it does **not** add independent draft clusters. It checks
  season-luck robustness, not sampling power.
- **Nothing here is statistically decisive.** Every interval touches or includes zero. A
  `[+0, +0]` interval means the compared candidates produced **identical sampled outcomes**;
  it is **not** evidence of equivalence. With 4 independent draft clusters the tool cannot
  resolve differences this small.
- Aligns with the deterministic fit (Section 2): KAT adds REB (+2.3) and FG% **without** the
  FT% penalty Mobley (−2.0) and Sengün (−1.8) carry, and the engine's later builds adapt.
- **Practical:** treat **KAT as directionally favored**; Mobley is the higher-ceiling FG%/BLK
  alternative if you accept the FT% cost; Sengün is a close Mobley substitute. Decide on
  FT%-punt tolerance — the sims do not separate them.

(These corrected numbers supersede the earlier pooled/deep comparison for these three players,
which shared one set of season worlds across drafts and pooled opponent models.)

## 7. Draft-night guidance (#43 / #54)

One representative completion per candidate (same seed as the head-to-head primary), **adaptive
punts**. Treat one completion as an *illustration*, not the plan — availability and the actual
board drive the pick.

### Why the "engine punt" differs from the per-target punt labels

Three different things share the word "punt":

- **Plan-table punt** = the build at the **last** recommendation of that completion (KAT balanced,
  Mobley FT%, Şengün AST).
- **Head-to-head punt set** = the builds chosen across **4 drafts × 2 opponent models**
  (KAT {3PM, AST, FG%, balanced}; Mobley {3PM, AST, BLK, FT%, PTS, REB, balanced};
  Şengün {3PM, AST, REB, balanced}).
- **Per-target punt label** (e.g. Clingan "STL", Markkanen "FG%") = the build the engine chose
  when evaluating **that specific candidate** at that pick.

They differ because the punt is selected **per candidate and per board**, not fixed — which is
precisely why you should not lock one.

### What the completed rosters project (week-18 totals + opponent context)

These are **single-path matchup proxies** from the completed rosters — a different metric from
the head-to-head **championship** results in §6, and one completion each. Do not read them as
championship probabilities.

| After #6 | FG% | FT% | 3PM | PTS | REB | AST | STL | BLK | TO | Mean win proxy | Weakest vs opponents |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| KAT | .496 | .824 | 69 | 631 | **233** | 132 | 39 | **26** | 62 | 0.89 | BLK, AST, TO |
| Mobley | .487 | .808 | 77 | 685 | 243 | 120 | 42 | 30 | 69 | 0.91 | FG%, AST, TO |
| Şengün | .480 | .802 | 63 | 666 | **270** | 137 | 45 | 32 | 75 | 0.91 | FG%, FT%, TO |

Roster z (vs the reference pool) explains each "weak" claim:

- **KAT:** REB −0.2, BLK −0.9 — genuinely **at/below** reference. His own +2.3 REB is offset
  because the balanced build spent later picks on guards/wings (Bane, Pritchard, Jerome), so the
  *aggregate* stays thin.
- **Mobley:** REB +1.0, FG% +0.4, BLK +2.2 — **not weak**. The earlier "weak REB/FG%" was a
  mislabel: they are only the lowest of a strong set. Real soft spot is **AST (−4.2)**, and vs
  opponents FG%/TO.
- **Şengün:** REB +2.7, BLK +1.6 — strong interior; the genuine weakness is **FG% (−1.9)**, and
  FT%/TO vs opponents.

### Ausar Thompson — evaluated, but ranked low at #43

He **was on the board at #43** in all three paths, and the engine **evaluated him**: he ranked
**outside the engine's top 15 at #43** (so his score gap to #1 is large — outside the top six
alone would not settle it, but he is well below the leading group). In these three paths an
opponent took him at **#51** — an **observation from these paths, not evidence about his typical
draft slot** (three paths is a tiny sample; judge his #54 risk from the market, ADP ≈ 81). So he
is **not** a #43 priority for this core, and there is a plausible risk he is gone by #54.
(The earlier "target Ausar at #43" came from *forcing* him at #6, not from his #43 valuation.)

### Priority rules (availability-driven) and three live alternatives

- **KAT →** #43: the best available **rebound/block big or shooter**; #54: the complement.
  - **Donovan Clingan** — STL/block big: fixes BLK/REB, low scoring.
  - **Michael Porter Jr.** — scoring wing: adds 3PM/PTS, no REB/BLK help.
  - **Lauri Markkanen** — FG%/3PM big: helps FG%+shooting, soft REB.
- **Mobley →** #43: a **shooting big or interior anchor**; #54: a guard (FT% punt optional).
  - **Lauri Markkanen** — FG%/3PM; keeps the FT% punt viable.
  - **Joel Embiid** (if it lasts) — REB/BLK/points; costs FT% and GP risk.
  - **Jaren Jackson Jr.** — BLK/3PM; natural in a FT%-punt build.
- **Şengün →** #43: **shooting (Markkanen) or a REB/BLK big (Clingan)**; #54: the other.
  - **Lauri Markkanen** — adds the 3PM/FG% the build lacks.
  - **Donovan Clingan** — doubles down on REB/BLK; worsens 3PM.
  - **Desmond Bane** — balanced guard; PTS/3PM without wrecking FG%.

Rule of thumb: take the highest-value player among {a big who fixes the weakest category, the best
available shooter}; **keep the punt unlocked** and let the board decide.

**Ausar fallback:** the alternatives above are the fallback set; do not plan around Ausar (he was
outside the engine's top 15 at #43 in these paths).

### Live-tool planning card (what you see each turn)

- **Your needs / roster strengths** recomputed from your **actual recorded roster** — not a punt label.
- Each candidate shows:
  - **Helps address: …**, or **Addresses: …** when the *recalculated* roster-with-him no longer lists that need — never a bare "Fills".
  - **Costs: …** = categories his **own** profile hurts.
  - **Tested build: punts …** — a separate label, never conflated with what he helps.
  - **Position: role (positions) · starts at `<slot>` · UTIL-dependent? · Δ usable starts / Δ blocked games** — C-only vs multi-position bigs distinguished, **no centre cap**, and positions flagged as **provisional Yahoo eligibility (verify in the draft room)**.
  - **After adding: needs …** from the **recalculated** roster (not the needs minus his positives).
- **Lower-survival alternatives** sit in a separate, always-inspectable section; the <50% cut is a **display heuristic**, not a rule.

### Timed rehearsal

`tests/plan_check.cjs` removes the top preferred target twice during a mock and re-checks
coherence: recalculated in **10.0 s / 11.5 s**, stayed coherent, and finished inside the 45 s
clock.

## 8. Caveats

- Small number of independent draft clusters → wide intervals; paired differences are
  reported, but overlapping intervals are not a ranking.
- Not calibrated odds; opponent behavior is ADP-driven; projections are a single snapshot.
- The **same-round keeper-cost rule remains an UNVERIFIED assumption** (two keepers payable
  in a round where the team holds two picks). Flagged until the commissioner confirms.
