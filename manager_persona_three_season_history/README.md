# 2023–2025 Fantasy Basketball Draft History

## Verified draft records

- 2023–24: 156 selections, 13 rounds from the supplied Yahoo screenshots, including keeper K markers and current-manager mapping. Original 2023 team names preserved.
- 2024–25 and 2025–26: imported from the previous two-season handoff.
- Combined 2023–2025: 468 draft selections.

## IMPORTANT — Historical RotoWire ADP export is NOT verified

The 2023 JSON file supplied via the RotoWire script is BYTE-FOR-BYTE IDENTICAL to the supposed 2024 JSON file already supplied. The endpoint likely ignored `season` or served a cached/default season. Therefore, all **2023 Yahoo ADP cells and ADP deltas are intentionally blank** in the newly supplied 2023 CSV and the three-season combined history. Do not use 2023 RotoWire data to train personas.

The 2024 ADP from the prior handoff may also be wrong; re-verify the entire historical series before using ADP-dependent features. The 2025 export is different, but its draft-time collection window remains unverified.

## Contents

- `draft_2023_results.csv` — 2023 Yahoo picks, managers, keeper markers; ADP blank
- `keepers_2023_yahoo_marked.csv` — 2023 K-marker records
- `combined_draft_2023_2025.csv` — 468 historical picks; 2023 ADP blank; 2024/25 retained but unverified
- `draft_2023_vs_yahoo_adp.csv` — placeholders only for eventual confirmed 2023 ADP
- `validation.json` — validation and warning

2023 keeper worksheet exists in Drive as a secondary historical record, but Yahoo K markers are the primary evidence. Do not confuse historical team names with stable manager IDs.
