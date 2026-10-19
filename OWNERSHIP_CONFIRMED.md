# Confirmed draft-pick ownership and keeper mapping (2026-10-12)

Commissioner notes + Discord evidence resolve all previously-flagged items. The local
source file and the append-only live board were updated; **the Google Sheet was not touched.**

## Confirmed facts

| Pick | Round | Trade history | Final owner | Local status |
|---|---|---|---|---|
| #106 | R9 | Samet → Nick → Raul | **Raul** | confirmed |
| #113 | R10 | Nick → Samet | **Samet** | confirmed |
| #123 | R11 | Raul → Nick | **Nick** | confirmed |

## Keeper-cost duplicates — both resolved from records

- **Nick (R11 ×2).** Nick retained his own R9 pick **#104** (he traded #106, not #104).
  He holds two R11 picks: his original **#128** and the acquired **#123** → both used for
  **Ace Bailey** and **Jabari Smith Jr.**
- **Samet (R10 ×2).** Samet retains his original R10 pick **#111** and acquired **#113**
  (Nick's original R10) → both used for **VJ Edgecombe** and **Dylan Harper**.
  The spreadsheet confirms #111 stays Samet and #113 is Samet's, so two usable R10 slots.

Which player maps to which of a team's two same-round picks is immaterial here and is
**not guessed** — only that each team holds two picks in that round is required.

## Local changes applied

- `draft_slots.csv`: owners for #106/#113/#123; keeper forfeitures for #111/#113/#123/#128;
  confidence → `confirmed`.
- Live board (`local/draft.sqlite3`): 5 `slot_override` events appended (append-only,
  auditable). Verified: **13 assets/team, 36 keeper slots, `uncertainty_barrier = None`,
  #106 → Raul, Samet keepers on #111/#113, Nick keepers on #123/#128.**

## Standing assumption (NOT commissioner-confirmed)

The commissioner confirmed **pick ownership** (#106→Raul, #113→Samet, #123→Nick) and the
Discord evidence explains how Nick acquired an extra R11 pick. Neither confirms a **league
rule about same-round keeper costs**.

**Assumption (documented, not verified): a team may pay two keepers at the same round when
it holds two picks in that round.** Under this assumption:

- Nick pays Ace Bailey + Jabari Smith Jr. at R11 using **#123 + #128**.
- Samet pays VJ Edgecombe + Dylan Harper at R10 using **#111 + #113**.

If the league actually forbids two same-round keepers regardless of extra picks, both teams'
second keeper would need to be re-costed. **Keep this flagged; do not treat commissioner
confirmation of ownership as confirmation of this rule.** Everything else reconciles
(13 assets/team, 36 keepers, `uncertainty_barrier = None`).

## Impact on existing simulations and caches: NONE board-dependent is invalidated

Every prior run (the 100-draft benchmark, the decision study, the survival calibration,
and the preliminary Pick #6 lab) already used the asset scenario:

```
owners:       {106: Raul, 113: Samet, 123: Nick}
keeper_slots: {111: VJ Edgecombe, 113: Dylan Harper, 123: Jabari Smith Jr., 128: Ace Bailey}
```

This is **byte-for-byte the confirmed mapping**. So:

- No board-dependent calculation relied on incorrect ownership — nothing must be recomputed.
- Board-independent season worlds remain valid.
- Only the **label** changes, from "hypothetical/unverified" to **"confirmed ownership
  2026-10-12"**. Future reports state this confirmed scenario explicitly.

## Residual flags (do not silently resolve)

- **Same-round keeper rule** — see the standing assumption above (unverified; ownership is
  confirmed, the rule is not).
- No other pick-ownership conflicts remain.
