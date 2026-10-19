# Hashtag projections import — 2026-10-11

- `players_projections.csv` contains **347 distinct player rows**, merged from the initial top-200 HTML and the newly uploaded browser-DOM HTML table.
- The new DOM capture has **347 parseable** player rows with displayed ranks up to 376. The missing ranks are **[244, 245, 265, 266, 278, 279, 317, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355, 356, 357, 358, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 399, 400]**. Some markup around rank 245 is malformed. The file is **not a complete top-400 export**.
- Existing top-200 rows were retained where not replaced. Do not interpret missing rows as undraftable.
- The source ranking is H2H, averages, 20% GP penalty; prior documented TO 0.25x. The copied DOM itself does not include the filter controls, so the exact category weighting of the latest capture cannot be confirmed independently. Recompute equal-weight 9-cat player values from stats.
- All FG/FT makes and attempts are per-game as displayed, rounded to one decimal. For roster percentage calculations sum projected makes / sum projected attempts, rather than averaging percentages.
- Per-game box scores, projected GP/MPG, source rank/total, Yahoo ADP and Hashtag player IDs are preserved.
- Player matching to keeper sheet is normalized for accents/punctuation. Verify any unmatched keepers.
- Do not automatically scrape subscriber-only pages. Newer HTML copies can be parsed locally with permission and imported.
