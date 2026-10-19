# Pick #6 decision brief — handoff to a reviewing agent

Self-contained. Primary artifacts: `PICK6_COMPARISON.md` and `PICK6_SHORTLIST_DEEP.md`
(both reproduced in essence below). Companion methodology doc: `BENCHMARK_METHODOLOGY_SUMMARY.md`.

**The one question:** for my #6 pick, is any candidate clearly better than the others, and
which best fits alongside my three keepers?

---

## 1. League & context

- 12-team H2H, 9 categories (FG%, FT%, 3PM, PTS, REB, AST, STL, BLK, TO), Yahoo keeper league
  ("It Begins"). I draft **#6** on 2026-10-18. Advisory tool only; I enter picks in Yahoo.
- **Keepers (locked):** Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George.
- **My live picks:** #6, #43, #54, #67, #78, #91, #102, #115, #126, #150 (R2/R3/R12 forfeited
  to keepers). Note the **long gap between #6 and #43** (36 opponent picks).
- **Objective:** maximise probability of winning the March 2027 playoff title.

Keeper core profile (per-game category z): strong **FT% (+3.4), PTS (+3.8), STL (+3.2),
3PM (+2.1), AST (+1.9)**; weak **REB (−1.7), FG% (−0.5), BLK (−0.1)**, very good **TO (−1.5)**.
So the core is guard-led; #6 ideally adds REB/FG%/BLK without destroying FT%.

## 2. Confirmed facts and assumptions (do not blur these)

- **Confirmed pick ownership:** #106 → Raul, #113 → Samet, #123 → Nick.
- **Confirmed keeper-cost slots:** Samet R10 uses **#111 + #113** (VJ Edgecombe, Dylan Harper);
  Nick R11 uses **#128 + #123** (Ace Bailey, Jabari Smith Jr.).
- **UNVERIFIED rule assumption:** a team may pay two keepers in the same round *when it holds
  two picks in that round*. If the league forbids this, the second keeper for Samet/Nick needs
  re-costing. Flagged, not proven.
- **Assumed taken before #6** (draft order above me): Jokic, Wembanyama, Dončić, Cade
  Cunningham, Giannis Antetokounmpo.
- Many "typical first round" names are **kept** and thus unavailable: SGA (me), Anthony
  Edwards, Jayson Tatum, Cooper Flagg, Jalen Johnson, Haliburton, Mitchell (me), Jamal Murray,
  Brunson, Amen Thompson, Austin Reaves.

## 3. Method (how the numbers were produced)

- The tool forces each candidate as my **#6** pick, keeps my keepers, then **completes the rest
  of the draft using the production recommendation engine** (same logic as draft night).
- **Paired random scenarios and shared season worlds** across candidates (same seeds), 2
  opponent models (`adp_stochastic`, `validated`), 4 paired drafts × 4 seasons, championship
  rate as the primary metric, uncertainty by **draft-cluster bootstrap**. Seeds are drawn from a
  held-out `production_lab` block, disjoint from any tuning block.
- Inputs: Hashtag 2026–27 projections + Yahoo ADP. Opponent behavior is modelled as **ADP-driven**
  (individual manager personas were tested and **failed** predictive validation, so they are not used).

## 4. Results

Deep pass (top 6), championship rate with 95% cluster interval:

| Candidate | ADP | Champ % | 95% interval | Stable across models? |
|---|---:|---:|---|---|
| Evan Mobley | 29.4 | 25% | [12%, 38%] | yes (25/25) |
| Ausar Thompson | 81.2 | 25% | [12%, 41%] | yes (25/25) |
| Josh Giddey | 23.1 | 19% | [3%, 34%] | no (12/25) |
| Lauri Markkanen | 36.9 | 12% | [0%, 31%] | no (19/6) |
| Devin Booker | 25.2 | 12% | [0%, 25%] | no (19/6) |
| Stephen Curry | 23.2 | 9% | [3%, 16%] | no (6/12) |

Deterministic **own** category z (the reliable part), vs the keeper core:

| Candidate | FG% | FT% | 3PM | PTS | REB | AST | STL | BLK | TO | Fits core by |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Evan Mobley | +1.3 | −2.0 | −0.6 | +0.4 | +1.4 | −0.1 | −0.7 | +2.1 | −0.2 | filling REB/FG/BLK (costs FT%) |
| Ausar Thompson | +0.7 | −1.6 | −1.5 | −1.0 | +0.1 | −0.3 | +3.4 | +0.5 | +0.3 | elite STL (value, ADP 81) |
| Josh Giddey | −0.6 | −0.4 | +0.1 | −0.1 | +1.0 | +2.3 | +0.5 | −0.2 | −1.8 | playmaking/low TO; overlaps AST |
| Lauri Markkanen | −1.1 | +1.2 | +1.3 | +1.3 | +0.2 | −1.0 | −0.4 | −0.4 | +0.6 | shooting; no REB/BLK |
| Devin Booker | −0.8 | +1.8 | +0.4 | +1.5 | −1.0 | +1.2 | −0.7 | −1.0 | −1.3 | perimeter scoring; overlaps core |
| Stephen Curry | −0.8 | +2.0 | +2.7 | +1.6 | −1.0 | +0.7 | −0.1 | −0.6 | −1.3 | shooting; overlaps core |

Additional available first-round-caliber profiles we examined (deterministic, from a coarse
run only — no deep sim): **KAT** (FG +0.7, FT +0.9, REB +2.3, PTS +0.8 — a strong, low-downside
fit), **Sengün** (REB +1.6, FG +0.6, AST +0.9, FT −1.8), **Durant** (FG/FT/3PM/PTS positive,
low TO), **Barnes** (balanced, GP 80), **Maxey** (PTS/3PM/STL), **Bam** (REB +1.6).

## 5. Conclusion (stated honestly)

- **All six deep intervals overlap → there is no statistically reliable winner.** Mobley and
  Thompson are the only stable point estimates; the rest flip between opponent models. Do not
  read "25%" as a probability or a ranking.
- On **deterministic fit**, the only candidate that genuinely fills the core's REB/FG/BLK holes
  is **Mobley** (cost: FT% and likely an AST/FG punt). **KAT and Sengün look like equal-or-better
  fits on paper** (KAT adds REB without the FT% penalty; Sengün adds REB/FG/BLK plus AST).
- **Ausar Thompson (ADP 81)** is the standout *value*: his build scores as well as anyone's, and
  his ADP suggests he may last to **#43/#54** — which argues for taking best-fit at #6 and
  targeting Thompson later rather than spending #6 on him.
- Suggestions for #43/#54: if Mobley at #6 → FT%/AST guards + a 3PM wing; in any case Thompson is
  the priority #43 target; the engine treats #43/#54 as a pair (don't reach on a position).

## 6. Limitations — please pressure-test these

- **Not calibrated.** Championship rates are simulated frequencies under stated assumptions, not
  real-world odds. Small sample (32 seasons/candidate in the deep pass).
- **Roster-level "strengths/weaknesses" in the raw reports come from a single simulated
  continuation** and are noisy; use the *player's own* profile (table above) for fit.
- **Fall-elite contingency rows are invalid** (on a board that assumes the elites are gone,
  forcing them at #6 falls back to the normal pick). Treat as a manual rule instead.
- Opponent behavior is ADP-driven; novel/personality behavior is not modelled. Projection
  snapshot and March availability (GP/82 proxy) are assumptions.
- The **same-round keeper rule** (Section 2) is an assumption, not confirmed.

## 7. Projection refresh

A newer Hashtag export (Oct 12) was diffed against the analysis baseline (Oct 11): 430 → 430
players, 266 rank changes overall, but **0 material changes** to my keepers or the #6 candidates
(Mobley/KAT/Curry/Giddey ranks unchanged; only ±1-rank jitter elsewhere). **The analysis above
stands.** Not yet installed; installing would invalidate stale caches automatically (the CSV is
part of the input-hash manifest). See `PROJECTION_UPDATE.md`.

## 8. Artifacts

- `PICK6_COMPARISON.md` — the candidate comparison and tradeoffs.
- `PICK6_SHORTLIST_DEEP.md` — the raw deep run (rate table + rosters).
- `local/pick6_lab_deep.json` — full machine-readable results.
- `PROJECTION_UPDATE.md` — Oct-12 projection diff.
- `OWNERSHIP_CONFIRMED.md` — pick-ownership facts + the unverified keeper rule.
- `BENCHMARK_METHODOLOGY_SUMMARY.md` — full simulation methodology and its limits.

## 9. Questions for the reviewer

1. Given overlapping intervals, is the correct call **Mobley (needs fit)** or **KAT/Sengün
   (better deterministic fit, no FT% cost)** — and does the FT%-punt path make sense at all here?
2. Is "target Ausar Thompson at #43, take best fit at #6" sound, or is his ADP-81 value a trap?
3. Which of the deterministic profiles best complements SGA + Mitchell + George in a 9-cat H2H?
4. Anything in the method (paired completions, cluster bootstrap, model stability) that would
   change the read?
