# Pick #6 shortlist (precomputed — decision support, NOT calibrated odds)

Assumed taken before #6: Nikola Jokic, Victor Wembanyama, Luka Doncic, Cade Cunningham, Giannis Antetokounmpo.
Own keepers: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George.
Seeds: `production_lab` (held-out evaluation block untouched). Generated 2026-10-12 16:10.

| # | Candidate | ADP | Champ % | 95% cluster interval | Best-built categories | Weak categories |
|---|---|---:|---:|---|---|---|
| 1 | Karl-Anthony Towns | 15.6 | 33% | — | STL, 3PM, FT% | TO, REB, FG% |
| 2 | Stephen Curry | 23.2 | 17% | — | STL, 3PM, FT% | FG%, REB, AST |
| 3 | Josh Giddey | 23.1 | 0% | — | STL, FT%, BLK | AST, TO, FG% |
| 4 | Evan Mobley | 29.4 | 0% | — | BLK, FG%, REB | FT%, STL, AST |

## Candidate detail

### Karl-Anthony Towns (ADP 15.6)
- Championship rate 33.3%, advancement 2.50/4. Per-model: adp_stochastic 33%
- Category strengths: STL, 3PM, FT%. Weak: TO, REB, FG%.
- Engine punt build: AST.
- Resulting roster: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George, Karl-Anthony Towns, Desmond Bane, Donovan Clingan, Keegan Murray, Ausar Thompson, Immanuel Quickley, Ryan Rollins, Jalen Suggs, CJ McCollum, Myles Turner

### Stephen Curry (ADP 23.2)
- Championship rate 16.7%, advancement 1.83/4. Per-model: adp_stochastic 17%
- Category strengths: STL, 3PM, FT%. Weak: FG%, REB, AST.
- Engine punt build: balanced.
- Resulting roster: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George, Stephen Curry, Donovan Clingan, Jaren Jackson Jr., Keegan Murray, Ausar Thompson, Kel'el Ware, Ryan Rollins, De'Andre Hunter, CJ McCollum, DeMar DeRozan

### Josh Giddey (ADP 23.1)
- Championship rate 0.0%, advancement 1.67/4. Per-model: adp_stochastic 0%
- Category strengths: STL, FT%, BLK. Weak: AST, TO, FG%.
- Engine punt build: REB.
- Resulting roster: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George, Josh Giddey, Desmond Bane, Donovan Clingan, Keegan Murray, Ausar Thompson, Ryan Rollins, Cedric Coward, Miles Bridges, Zach Edey, CJ McCollum

### Evan Mobley (ADP 29.4)
- Championship rate 0.0%, advancement 1.83/4. Per-model: adp_stochastic 0%
- Category strengths: BLK, FG%, REB. Weak: FT%, STL, AST.
- Engine punt build: BLK.
- Resulting roster: Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George, Evan Mobley, Desmond Bane, Matas Buzelis, Ivica Zubac, Zach Edey, Kel'el Ware, Zach LaVine, Myles Turner, Toumani Camara, Saddiq Bey

## Contingency (unexpected elite fall)
- If one of Nikola Jokic, Victor Wembanyama is still on the board at #6, evaluate it directly before picking: it was assumed gone here.

## Read with care
- Differences within the cluster interval overlap are NOT a ranking; show tradeoffs.
- Uncalibrated decision support; opponent/projection/March-availability assumptions can flip the order.

## Consequences for picks #43 and #54

Assuming your pick at #6 is one of the strong candidates above, your next two live picks are **#43** and **#54** (36 opponent picks in between). Directional guidance:

- **If you take Karl-Anthony Towns (#6):** your resulting build is strong in STL, 3PM, FT% and weak in TO, REB, FG%. Target **TO** at #43, and treat #54 as the chance to add a second piece in REB — unless a scarce STL option falls.

- **If you take Stephen Curry (#6):** your resulting build is strong in STL, 3PM, FT% and weak in FG%, REB, AST. Target **FG%** at #43, and treat #54 as the chance to add a second piece in REB — unless a scarce STL option falls.

Opportunity cost of waiting: the engine weights #43 and #54 as a pair; do not force a positional need at #43 if it means passing a clearly higher-value player who fits the weak categories above.

## Preliminary status
- This is a **preliminary** pass (1 opponent model, 2 paired drafts) — cluster intervals are uninformative and the ordering among close candidates is NOT reliable.
- Run the deeper pass to firm it up: `python3 scripts/run_pick6_lab.py --broad 12 --broad-drafts 2 --deep-top 6 --deep-drafts 4 --deep-seasons 4 --models adp_stochastic,validated`.

## Confirmed ownership (2026-10-12)

This analysis uses the **confirmed** asset scenario: owners #106→Raul, #113→Samet, #123→Nick; keeper slots #111 VJ Edgecombe, #113 Dylan Harper (Samet), #123 Jabari Smith Jr., #128 Ace Bailey (Nick). This matches the scenario used by all prior runs, so no result here is invalidated. See `OWNERSHIP_CONFIRMED.md`.

## Fall-elite contingency (all five)

Assumed taken before #6: Nikola Jokic, Victor Wembanyama, Luka Doncic, Cade Cunningham, Giannis Antetokounmpo. If **any** of these five is still available at #6 (and draft-eligible), evaluate it directly before picking — it was assumed gone here. Re-run with `--contingency 5` to include all five as forced candidates.
