# Draft-night readiness (Japan / offline)

Verified 2026-10-12. Application runs **locally on this laptop**; no remote access or
cloud needed. Practical freeze: **Thu 2026-10-15 evening**; draft **Sun 2026-10-18**.

## Projection update (Thu, before departure)

If you grab a fresh Hashtag export, diff it first (no changes made), then install:

```sh
cd ~/Development/fantasy-basketball-helper
python3 scripts/update_projections.py --new ~/Downloads/hashtag_new.csv          # diff only
python3 scripts/update_projections.py --new ~/Downloads/hashtag_new.csv --activate
```

- The diff (`PROJECTION_UPDATE.md`) reports rank / GP / MPG / all nine categories and a
  value index, focused on **your keepers and the #6 candidates**, and says whether the
  #6 plan materially changed (or not).
- `--activate` **archives** the current file under `data/projections/archive/` and installs
  the new one. **Restart the app** to reload valuations.
- Cache safety is automatic: the projection CSV is part of the benchmark input-hash
  manifest, so older runs **refuse to resume** rather than mix stale projections.
- If a leading candidate moves materially, rerun the lab with the **same seeds** for a
  low-noise old-vs-new comparison (the script prints the exact command).
- If anything looks wrong, just don't `--activate`: compare exports manually and leave the
  current projections in place.

## Exact procedure (startup / restart / recovery)

**Start**
1. Open Terminal, `cd ~/Development/fantasy-basketball-helper` (or
   double-click `Start Draft Assistant.command`).
2. Run `python3 run.py`. Wait for `Draft assistant: http://127.0.0.1:8765`.
3. Open that URL (it usually opens automatically). Confirm your keepers
   (SGA, Donovan Mitchell, Kyshawn George) and pick slots #6/#43/#54/#67/#78/#91/#102/#115/#126/#150.

**Restart (normal)**
1. Ctrl-C in the terminal (or close the window).
2. Run `python3 run.py` again. The board, session, and cached research reload automatically.

**Recovery (crash / power loss / unresponsive)**
1. Relaunch `python3 run.py`. Every pick is committed to `local/draft.sqlite3`, so the
   board returns exactly as it was.
2. If a background simulation was running, it is optional; start a fresh one or ignore it.
3. If the port is stuck: `pkill -f run.py` then relaunch. Nothing is lost — state is on disk.
4. Last-resort restore from backup:
   `mkdir -p ~/restore && tar -xzf ~/draft-backup/<newest>.tgz -C ~/restore` then run from there.

**Offline test (do this before Friday)**
1. Turn Wi-Fi off.
2. `python3 run.py`, open the URL, record a few mock picks, use Undo.
3. Ctrl-C, relaunch, confirm the picks and cached research (`PICK6_SHORTLIST.md`,
   `local/pick6_lab.json`) are intact. The tool must work with no network.

**Pausing background work**
- `pkill -f BenchmarkRunner` and `pkill -f run_pick6_lab` stop any background simulations.
  They never block the server; pausing frees CPU so `recommend()` stays fast in the
  45-second window.

## Start / stop

- **Start:** double-click `Start Draft Assistant.command`, or run `python3 run.py`.
  It prints `http://127.0.0.1:8765` and opens the browser. No coding-agent session needed.
- **Stop:** Ctrl-C in the terminal, or close the window.
- The server is local-only (binds `127.0.0.1`), so nothing is exposed on hotel Wi-Fi.

## Internet dependency (what stops if hotel Wi-Fi is unreliable)

Runtime drafting needs **no internet**. The only network code is in two *pre-draft*
refresh scripts you never run during the draft:

| Needs internet | Purpose | Run when |
|---|---|---|
| `scripts/fetch_schedule.py` | refresh NBA daily fixtures | before the draft, optional |
| `scripts/fetch_player_bios.py` | refresh NBA biographies (persona traits) | before the draft, optional |
| Yahoo (browser) | your actual pick submission | draft night |

Everything else — projections, ADP, keepers, schedule, calendar, cached analysis, the
recommendation engine, the season lab — is local files + SQLite. A verified browser check
asserts the app makes **no external requests**. If Wi-Fi drops mid-draft, the assistant
keeps working; only submitting the pick in Yahoo is affected.

## Restart / crash survival

- Draft state lives in `local/draft.sqlite3` (every pick is committed; the log is
  append-only). Relaunch restores the exact board and session (e.g. "Mock 5").
- Cached analysis lives in `local/*.json` (e.g. `pick6_lab.json`, `decision_study.json`,
  `survival_calibration.json`) and benchmark checkpoints in `local/draft_benchmarks/`.
- Season benchmarks resume from per-season detail files; nothing is recomputed.
- **Recovery:** just relaunch. If a background job was running, relaunch it from its run
  folder — completed seasons are reused.

## Time zone (Japan Standard Time)

All scheduling uses explicit ISO dates and Eastern-Time NBA dates from the verified
files; the only local-clock use is UTC timestamps in the store. There is **no
`date.today()`/local-time dependence** in the runtime path, so JST does not shift weeks,
game days, or fantasy scoring boundaries. Weeks 1–20 and the verified Yahoo playoff dates
(Mar 1–21, 2027) are date-string driven.

## 45-second pick window

- `engine.recommend()` ≈ **10 s** per call (unpruned, authoritative), comfortably inside
  Yahoo's 45 s window.
- Background work runs in **separate processes** and never blocks the server. Pause or
  cancel any background job (`pkill -f BenchmarkRunner`) before a tight pick if the laptop
  feels loaded. The live recommendation runs in the server process on the real board.

## Precomputed vs live

- Precomputed research is written to explicitly named files (`PICK6_SHORTLIST.md`,
  `local/pick6_lab.json`) and labelled "precomputed — decision support, NOT calibrated odds".
- The live tool always recommends from the **actual current board**. Cached research
  supplements; it never overrides fresh board information.

## Backup before departure

Run once before leaving (writes a timestamped archive outside the app):

```sh
cd ~/Development/fantasy-basketball-helper
mkdir -p ~/draft-backup
tar -czf ~/draft-backup/draft-assistant-$(date +%Y%m%d-%H%M).tgz \
  --exclude='local/draft_benchmarks' \
  app web scripts tests data *.csv *.json *.md run.py 'Start Draft Assistant.command' \
  fantasy_league_2026_27_schedule_with_dates local/draft.sqlite3 local/*.json 2>/dev/null
ls -lh ~/draft-backup
```

Then copy `~/draft-backup/*.tgz` to a second location (USB stick or cloud) so a laptop
loss does not lose the tool. Restore = untar and run.

## Quick checklist

1. `python3 run.py` starts and prints the local URL.
2. Board shows your 3 keepers (SGA, Mitchell, George) and your pick slots #6/#43/… .
3. `PICK6_SHORTLIST.md` and `local/pick6_lab.json` exist (precomputed #6 research).
4. `local/draft.sqlite3` exists (state survives restart).
5. Backup archive copied off the laptop.
6. Wi-Fi off test: reload the page — the tool still works from local files.
