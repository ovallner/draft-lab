# Three-season manager personas — methodology and limits

Reproduce from the project root:

```sh
python3 scripts/fetch_player_bios.py   # optional online refresh of NBA biographies
python3 scripts/import_history3.py     # local once biographies are cached
python3 -m unittest discover -s tests -v
```

The legacy single-season pipeline (`scripts/import_history.py` → `data/history/`) is
retained as a fallback and is still tested, but `Data` prefers this three-season
package whenever `data/history3/profiles.json` exists.

## Why the three seasons are not equal

The supplied history is genuinely uneven, and pretending otherwise would corrupt the
model. Each season is tagged with an explicit **ADP tier**:

| Season | ADP tier | Discretionary picks | With ADP | Market pool | Choice sets |
|---|---|---|---|---|---|
| 2023-24 | `none` | 122 | 0 | 0 | 0 |
| 2024-25 | `taken_only` | 122 | 121 | 121 | 110 |
| 2025-26 | `full_market` | 120 | 116 | 166 | 116 |

- **2025-26** is the only complete market (RotoWire export, 200 ADPs; measurement
  date still unknown).
- **2024-25** has ADP **only for players who were actually taken**, so the available
  pool is truncated. Measured consequence: replaying 2025 with the same truncation
  understates the mean available rank by about 12 slots and late-round reach by about
  26 slots. Its ADP slope is therefore **fitted separately, never pooled** with 2025.
- **2023-24** has **no usable ADP**: the supplied 2023 RotoWire export is
  byte-for-byte identical to the 2024 export. All 2023 ADP cells are blank. It cannot
  enter the choice likelihood at all (a pick-order proxy would be circular).

The 2024 ADP *is* usable despite the awkward provenance: each ADP column correlates
highest with its own season's picks (2024→0.956, 2025→0.913), which is what a genuine
season-specific market looks like.

## What each analysis uses

- **Descriptive preferences — all three seasons.** For every manager and trait
  (youth, rookie, guard, forward, center) the manager's picks are compared with the
  same-season league mix **within the same round phase**, so draft-slot availability
  is roughly held constant without needing ADP. Deviations are then checked for
  **cross-season replication**: does the deviation keep the same sign every year?
- **Conditional choice model — the two ADP seasons.** A ridge conditional logit over
  the ADP market available set, with a per-season ADP slope and preference betas
  shrunk toward a pooled prior. Boards thinner than 12 players are dropped.

## Result: the extra seasons strengthen the evidence, not the model

Held-out choice prediction on 134 pooled picks:

| Metric | ADP baseline | Persona |
|---|---:|---:|
| Choice log loss | 4.0081 | 4.0078 |
| Mean selected rank | 16.60 | 16.48 |
| Top-5 accuracy | 32.8% | 32.1% |

Persona − baseline log loss: **−0.0003**, round-block 95% interval **[−0.0386, +0.0339]**
— it spans zero. Cross-season transfer:

| Trained → tested | Baseline | Persona (pooled) | Persona (per-manager) |
|---|---:|---:|---:|
| 2024-25 → 2025-26 | 3.7315 | 3.7596 | 3.7539 |
| 2025-26 → 2024-25 | 3.0445 | 3.0522 | 3.0463 |

**0/2 cross-season pairs favour the persona.** The gate requires better held-out loss,
an interval excluding zero, *and* transfer across seasons. None hold, so **Auto keeps
the ADP baseline.** The validation is leakage-free: every arm is fitted only on the
training rounds/seasons and applied to held-out data.

### Why the traits are real but do not help

The descriptive analysis *does* find replicated traits — for example Adam, Jipples,
Samet and Shiven draft consistently **younger**; Austin, Nick and Oscar consistently
**older** (Oscar −0.34, the strongest); Jipples consistently takes **more rookies**;
Raul consistently **forwards**. The model even captures the direction correctly
(Austin has the lowest youth coefficient, Samet the highest). It simply adds no
predictive power beyond ADP, which is consistent with ADP already pricing youth in —
a young breakout has a high ADP, so conditioning on youth again is largely redundant.
Koo, Addison and San show no trait that replicates at all.

## Limitations (do not over-read)

- The two ADP seasons have different pool tiers, so cross-season transfer partly
  reflects that difference rather than pure behavioural drift.
- Positions come from a **2025-26 snapshot** applied to all seasons; historical
  Yahoo position eligibility is not reconstructed. Bio coverage is 146/155/156 of 156.
- Age is computed as of 1 October of each season's start year; rookie status comes
  from the official NBA first-regular-season record.
- One pick per player means player-specific targeting cannot be identified.
- Subjective manager overrides remain available and are stored separately from every
  observation; they never re-fit the model.
