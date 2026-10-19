# Pick #6 comparison — leading candidates

**Status:** deterministic category/roster analysis is reliable; the championship
percentages below are **preliminary** (2 paired drafts, 1 opponent model) and are **not**
a ranking. The deeper run (top 6, 2 models, 4 paired drafts, 4 seasons) is still running
and will replace the numbers; the qualitative read here is what to act on tonight.

## The keeper core (why #6 matters)

Your keepers are **Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George** — a
guard-led core, strong in **FT%, PTS, STL, 3PM, AST**, weak in **REB, FG%, BLK**:

| | FG% | FT% | 3PM | PTS | REB | AST | STL | BLK | TO |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Keepers-only z | −0.5 | **3.4** | 2.1 | **3.8** | **−1.7** | 1.9 | **3.2** | −0.1 | −1.5 |

So #6 is really a fork: **extend the keeper strengths** (shooting/FT/steals) or **flip
toward big-man categories** (FG/REB/BLK) — accepting a FT% hit. That choice cascades into
#43/#54.

## Candidates (structural comparison — deterministic)

| Candidate | ADP | Strong categories | Leaves weak | Punt | Playoff gm (wk18–20) | Shape | Champ%* |
|---|---:|---|---|---|---:|---|---:|
| Karl-Anthony Towns | 15.6 | FT%, 3PM, STL | FG%, REB, TO | AST | 130 | 9G/5F/3C | 33% |
| Stephen Curry | 23.2 | FT%, 3PM, PTS/STL | FG%, REB, AST | balanced | 134 | 7G/6F/3C | 17% |
| Josh Giddey | 23.1 | FT%, STL, BLK | FG%, AST, TO | REB | 135 | 9G/6F/2C | 0% |
| Evan Mobley | 29.4 | BLK, FG%, REB | FT%, STL, AST | BLK | 133 | 5G/7F/5C | 0% |

\* Preliminary, 2 clusters — noise. Playoff-game totals are all within ~5 (130–135), so
**scheduling is not a differentiator**; the choice is about category shape.

## The two coherent archetypes (and two weaker ones)

- **Karl-Anthony Towns — extend the core.** A shooting big who *adds* FT%/3PM without
  damaging them and gives modest REB/BLK, at the cost of FG% and a likely **AST punt**. The
  build stays on the keeper core's strengths (FT/3PT/STL) — a "double down" path.
- **Evan Mobley — flip the build.** Elite **BLK (+6.7)**, strong **FG% (+3.8) and REB
  (+3.5)**: exactly the categories the keeper core lacks. The price is **FT%** (already a
  keeper strength) and **STL/AST**, i.e. a deliberate **FT% soft-punt** with 5C/7F shape.
- **Stephen Curry / Josh Giddey — structurally weaker fits.** Both leave the core's
  **REB/FG%** hole largely unaddressed (Curry adds REB −2.5 / AST −3.4; Giddey is balanced
  but low-ceiling here). Curry is a points/threes guard where you already have Mitchell/SGA;
  Giddey’s value overlaps rather than complements.

**Read:** the genuine decision is **KAT (extend) vs Mobley (flip)**. Curry and Giddey are
structurally redundant with the keeper core unless a specific value falls.

## Consequences for #43 and #54

| If you take #6… | #43 should target | #54 second piece | Build shape |
|---|---|---|---|
| **KAT** | FG%/REB big (protect the punt), or best STL/3PM value | second FG%/REB contributor | guard-led + shooting big, punt AST |
| **Mobley** | FT%/AST guards to soften the FT punt | best 3PM/STL wing | big-led, FG/REB/BLK, soft-punt FT% |
| Curry | a C/REB anchor (mandatory) | FG%/REB again | guard volume, REB/FG risk |
| Giddey | FG%/BLK big | 3PM/PTS value | balanced, low ceiling |

Practical rule: the engine weights **#43 and #54 as a pair** — do not burn #43 on a
positional need if it means passing a clearly higher-value player who fits the weak
categories above.

## Playoff considerations (March)

- Weeks 18–20 (Mar 1–21, 2027) use the fixed 8-team bracket. Roster playoff-game totals are
  **130–135 for every candidate**, so no candidate wins on schedule volume.
- The engine already weights playoff availability; the differentiator is **category shape
  under pressure** (FT% vs FG%/REB/BLK), not games played.

## Deep run results (final) — no reliable winner

Deep pass: top 6 candidates, 2 opponent models, 4 paired drafts × 4 seasons.

| Candidate | ADP | Champ % | 95% interval | Stable across models? |
|---|---:|---:|---|---|
| Evan Mobley | 29.4 | 25% | [12%, 38%] | yes (25/25) |
| Ausar Thompson | 81.2 | 25% | [12%, 41%] | yes (25/25) |
| Josh Giddey | 23.1 | 19% | [3%, 34%] | no (12/25) |
| Lauri Markkanen | 36.9 | 12% | [0%, 31%] | no (19/6) |
| Devin Booker | 25.2 | 12% | [0%, 25%] | no (19/6) |
| Stephen Curry | 23.2 | 9% | [3%, 16%] | no (6/12) |

**All six intervals overlap → there is no statistically reliable winner.** Mobley and
Thompson are the only two with a *stable* point estimate; the rest flip between models.
This is an "inconclusive, show the tradeoffs" outcome — the intended behaviour.

## Category fit from each player's OWN profile (the reliable part)

Note: the "strengths/weaknesses" lines in the raw lab report come from a **single simulated
continuation roster** and are noisy — not a build plan. The reliable fit is each candidate's
own per-game category z vs your keepers (SGA + Mitchell + George: strong FT% / PTS / STL,
weak REB / FG% / BLK):

| Candidate | FG% | FT% | 3PM | PTS | REB | AST | STL | BLK | TO | Fits the core by… |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Evan Mobley | +1.3 | −2.0 | −0.6 | +0.4 | +1.4 | −0.1 | −0.7 | +2.1 | −0.2 | fixing REB/FG/BLK (costs FT%) |
| Ausar Thompson | +0.7 | −1.6 | −1.5 | −1.0 | +0.1 | −0.3 | +3.4 | +0.5 | +0.3 | elite STL; some FG/BLK (costs FT%/3PT) |
| Josh Giddey | −0.6 | −0.4 | +0.1 | −0.1 | +1.0 | +2.3 | +0.5 | −0.2 | −1.8 | playmaking + low TO; overlaps AST |
| Lauri Markkanen | −1.1 | +1.2 | +1.3 | +1.3 | +0.2 | −1.0 | −0.4 | −0.4 | +0.6 | shooting/scoring; no REB/BLK |
| Devin Booker | −0.8 | +1.8 | +0.4 | +1.5 | −1.0 | +1.2 | −0.7 | −1.0 | −1.3 | perimeter scoring; overlaps core |
| Stephen Curry | −0.8 | +2.0 | +2.7 | +1.6 | −1.0 | +0.7 | −0.1 | −0.6 | −1.3 | shooting; overlaps core |

**Mobley is the only candidate that fills the core's actual holes** (REB/FG/BLK).
**Thompson amplifies a strength (STL) at ADP 81** — a value, not a needs fit.

## Practical read for #6

- Cleanest *fit*, willing to soft-punt FT%/AST: **Mobley at #6**.
- **Ausar Thompson (ADP 81) is the standout value** — his build scores as well as Mobley's
  and his ADP suggests he may last to **#43/#54**, which argues for *not* spending #6 on him:
  take the best fit at #6 and target Thompson later.
- Markkanen / Booker / Curry / Giddey overlap the keeper core — fallbacks or later value.
- Since all intervals overlap, **do not treat Mobley-vs-Thompson as solved** — decide on
  roster fit, FT%-punt tolerance, and where you expect Thompson to actually go.

## #43 / #54 consequences

- **Mobley at #6 →** FT%/AST guards + a 3PM wing at #43/#54 to soften the FT punt.
- **Any #6 pick →** Ausar Thompson is a priority **#43** target if still available.
- Engine weights #43 and #54 as a pair; don't burn #43 on a position if it means passing
  clearly higher value that fits the weak categories.

## Reliable vs not

- **Reliable (deterministic):** each candidate's own category profile (table above), the
  FT%-vs-FG%/REB/BLK tradeoff, playoff schedule (all ~10–11 games).
- **Not reliable:** the championship percentages and any ranking among them (all intervals
  overlap); roster-level "strengths" in the raw report come from one simulated continuation.
- **Fall-elite contingency:** the automated contingency rows are **not valid** (on a board
  that assumes the elite are gone, forcing them at #6 falls back to the normal pick). Treat
  it as a manual rule — if Jokic / Wembanyama / Dončić / Cade / Giannis is actually on the
  board at #6, evaluate it live before picking.
