# Full-draft policy audit — prepared, not launched

## Purpose and status

Evaluate whether following the displayed recommendation at **every owned pick**
produces competitive, coherent teams and works within the 45-second clock.
This is not another search for a uniquely optimal first-three-pick combination.

**The overnight workload has not been started.** No scheduled task or background
overnight process was created. Only the bounded pilot, disposable-app browser
checks, and runner control tests have run.

> **Revision note (harness fix).** An earlier launch attempt stopped after 294
> seconds on the first robustness case. Cause: a defect in the *new audit harness*
> (slot rounds are stored as text, and the new `center_run`/`guard_run` branch
> compared them numerically). It was **not** an engine or policy defect, and no
> `adp_stochastic`/`validated` result reached that line. The fix coerces the round
> to an integer; the scientific application code is unchanged hash-for-hash. All
> partial results from the earlier attempt were archived to
> `main/pre_harness_fix/`, so every retained run result is generated under the
> single final manifest. `center_run` was then verified end-to-end and the other
> robustness branches reached clean checkpoints. A regression test was added.


Run directory:

`/Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013`

The source snapshot, original JSON/Markdown playbook, projection data, policy
definitions, runtime configuration and fresh seed namespace are frozen there.
`READY.json` seals the manifest and preflight evidence. No engine tuning was done.
The application’s live database and saved mocks were not opened by the experiment.

## Experiment

Keepers: **Shai Gilgeous-Alexander, Donovan Mitchell, Kyshawn George**.
Live picks: **6, 43, 54, 67, 78, 91, 102, 115, 126, 150**.
Roster: 13 drafted players; 10 daily active slots, including one C and three UTIL.
There is no arbitrary center cap. Eligibility is the supplied provisional Yahoo
eligibility; the same-round keeper-cost assumption remains unverified.

One projection snapshot is used throughout: the supplied October 12 Hashtag
export, SHA-256
`2363f158bb65c179930f515144e6d7adb9dfe50b1c1243e724b99519ee014d60`.
It is installed in the isolated source copy only, not activated in the live app.
Validation checks identities, keeper coverage, numeric data and schedules; it
does not independently verify current injury news or future role assumptions.

### All four policies make all ten live selections

| Policy | Exact rule |
|---|---|
| A — production | Call the unpruned production `Engine.recommend`. Apply the live UI’s featured filter: keep rows whose `availability_at_next` is missing/null or at least 0.5; if none qualify, keep the original list. Take the first row. Backend order breaks score ties. Log any difference from backend rank 1. |
| B — best available ADP | Lowest `(market_adp, projection rank, provider ID)` among available nonkeepers. Missing Yahoo ADP uses the existing labeled source-rank interpolation. |
| C — ADP + category fit/position coverage | Use the shared `SeasonDraft.pick` fit baseline: first 10 market players when roster size <7, otherwise first 16; diminishing weights for saturated categories; GP health discount at risk 0.5; +0.35 for the first C or +0.2 for the first forward; market reach cost `0.025*log(1+ordinal)`. No fixed punt or playoff multiplier. Exact ties take the first market-ordered player. This is a simple coverage baseline, not a full lineup optimizer. |
| D — preserved playbook, then A | At #6, first available in KAT → Mobley → Şengün → Markkanen → Maxey → Barnes → Durant → Bam. At #43/#54, follow that first-pick branch’s preserved JSON rankings, conditioned on actual #43 selection; filter out every unavailable/keeper ID. Use the published fallback list if necessary. Outside covered branches use best available ADP. From #67 onward use A. |

**Playbook interpretation is explicit:** the earlier prose did not specify a
single automatic rule for overriding KAT with an unexpected elite faller. D tests
the literal provisional chain above, without an optional elite override. Thus a
D loss on a faller board would not prove that the playbook’s optional human
contingency advice was wrong. The original playbook remains intact.

At each simulated pick all available identities, the board, scores/alternatives,
selection, roster before/after, position fit, market ordinal, wait-survival
estimate (where supplied), latency and temporary build label are recorded.
An unavailable production selection, missing recommendation on a legal board,
or roster-integrity violation stops the job with an error rather than substituting
a different policy under the same label.

### Paired paths and separate robustness cases

- Primary models: **ADP-stochastic** and **validated**, reported separately. The
  latter is the validated pooled baseline plus small prospective fit effects;
  rejected manager personas are not enabled. The models are related, so their
  agreement is not independent validation.
- Sensitivity: **market-tight**, sampling the top eight with rank weights
  `(rank)^-3.5`; **need-pressure**, sampling the top 24 with flatter market weights,
  stronger current-category needs, position coverage and fixed manager styles.
  These change opponent choices meaningfully rather than relabeling a baseline.
- Adverse cases: opponents deliberately prioritize centers or guards from the
  top 24 remaining market players in rounds 4–7. These are constructed position
  runs, not estimates of their natural frequency.
- All four policies share source-path opponent randomness and season seeds.
  Different source indices use different draft and season seeds. Pilot, primary,
  sensitivity and adverse seed namespaces are distinct. No old held-out or
  first-three-pick paths are reused.
- Three season worlds per completed draft. Policies and worlds are not counted
  as independent draft situations. Comparative summaries use source paths with
  all four policy completions, preserving partial work separately.
- All drafting policies use identical season management: Oscar aggressive
  streaming, observed opponent activity, no imposed punt for any team, the same
  position-constrained daily lineup algorithm, IL/FAB/waivers and placement
  eligibility. Temporary draft build labels cannot change season management.

Scheduling is fixed before the run: both primary models at each index; both
sensitivity models every fourth index; two cases each of center/guard runs.
There is no selection of a winning policy followed by reuse of its screening data
as independent confirmation. Main-run evidence is entirely fresh.

## What the report will evaluate

- Paired championship, playoff qualification and advancement differences; draft-
  cluster bootstrap intervals and conservative simultaneous bounded intervals.
  No significance, equivalence or noninferiority claim is implied by overlapping
  or zero-spanning intervals.
- Five-category route fraction against each opponent in playoff weeks, the
  fifth-strongest category edge, strengths/weaknesses/close categories, usable
  starts, blocked games and a stronger-GP-discount diagnostic.
- Distributions and downside, not just average results. Strong, typical and weak
  examples are selected by projected roster construction, **not by title losses**.
- Large reaches relative to the remaining market pool (not raw ADP minus keeper
  draft slot), plausible waiting estimates, position congestion and availability
  sensitivity. These are review signals, not automatic proof of a defect.
- Punt-label switches are descriptive; they are not failures by themselves.

The final report distinguishes:

1. **Ready to use as my default decision-maker** — adequate coverage and passed
   operational, roster-downside and observed competitive-performance checks under
   the frozen practical rubric.
2. **Useful, but requires specific fixes or guardrails** — unresolved coverage,
   latency or roster-quality concerns.
3. **Not yet dependable enough** — material correctness failure or widespread
   weak projected routes under both primary models.

The precise rubric is in the frozen report script and manifest. Its thresholds
are transparent practical heuristics, not calibrated guarantees. Championship
significance is not a prerequisite. Any justified fix should be followed by a
new snapshot and fresh validation, not tuning on this run.

The competitive guardrail flags an observed deficit versus C exceeding 10
percentage points in championship or qualification frequency, or 0.35 advancement
steps, in either primary model. Passing these observational gates is **not** proof
of equivalence/noninferiority. The paired uncertainty remains part of the report.
This reporting-only rubric was tightened during preparation; the prior preflight
is retained under `preflight_v1/`, and the bounded pilot was rerun against the final
snapshot. No engine or drafting-policy code changed.

## Preflight results and estimated coverage

- **19 backend/contract checks passed** against the frozen application code.
- Actual checkpoint/resume passed after two own picks and after one season world.
  Saved decisions/worlds were unchanged; reopening a complete task did no work.
- Control checks passed: exclusive run lock, hash-mismatch refusal, elapsed-budget
  carry-forward, SIGINT checkpoint stop, budget-expiry stop, deterministic failure
  propagation without retry, and correct counting of complete four-policy paths.
- Browser checks used disposable databases: stale UI callback, stale backend
  revision and wrong-session submission refused; featured order matched policy A;
  ADP fallback order verified; disposable live board remained empty.
- Recalculation plus recording: **12.10s at #6, 19.19s at #78, 10.82s at #150,
  9.54s on a #43 board with the top two targets removed**. These are representative
  measurements, not a promise every board/device state will meet the clock.
- Four-policy timing pilot: **157 seconds**, including checkpoint/resume checks.
  Per-policy active times: A 87.3s, B 7.4s, C 7.4s, D 54.0s.
- Seven hours with one worker suggests approximately **37–58 complete independent
  primary paths per opponent model**, plus sensitivity/adverse cases. The estimate
  allows overhead and slower boards; actual coverage may be lower. Main evaluation
  has not started, so no competitive-performance verdict is available yet.

## Why the launch design changed

Existing logs show a four-worker `BrokenProcessPool` after about 76 minutes and
a later two-worker supervisor disappearance without a recorded exception. They
do **not** establish an OOM diagnosis or another specific underlying cause.
The eventual detached one-worker recovery completed. Its recorded supervisor
peak RSS was about 406 MB; that does not describe failed workers’ peak memory.

This runner is deliberately simpler:

- One **foreground, terminal-owned supervisor**, one fresh Python child per
  policy draft. No persistent process pool, agent dependency or scheduled task.
- Exclusive run lock; strict frozen file/Python-version/readiness checks.
- Atomic, flushed checkpoints after every own selection and every season.
- Progress/heartbeat every five seconds while a child is active, plus task logs.
- At most one fresh-process retry after an abrupt SIGKILL. Ordinary Python errors
  and a 600-second task timeout fail visibly with a nonzero exit. A failed run is
  blocked pending diagnosis; it is not silently retried under changed code.
- Ctrl-C or the `stop` command requests a checkpoint-boundary stop. Resume reuses
  saved work and the remaining seven-hour budget; downtime does not consume the
  recorded running budget. A forced termination can lose at most the uncheckpointed
  operation; status detects an abandoned run lock rather than saying it is active.
- Budget expiry preserves useful partial reports. Allow the current pick/season
  boundary and report publication to finish; they can extend slightly past the
  nominal deadline.

## Exact terminal commands

No project-directory change or activated environment is required. Use the frozen
Python 3.9 interpreter shown below. The workload needs only Python’s standard
library; Playwright was used for preflight only.

### Launch — this is the command YOU run

```sh
/usr/bin/caffeinate -is /Library/Developer/CommandLineTools/usr/bin/python3 -B /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013/source/scripts/policy_audit.py run --run /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013 --hours 7 --workers 1
```

### Check progress from another terminal

```sh
/Library/Developer/CommandLineTools/usr/bin/python3 -B /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013/source/scripts/policy_audit.py status --run /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013
```

### Stop gracefully

Press **Ctrl-C once** in the launch terminal and wait for a checkpoint, or run:

```sh
/Library/Developer/CommandLineTools/usr/bin/python3 -B /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013/source/scripts/policy_audit.py stop --run /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013
```

### Resume an interrupted run

```sh
/usr/bin/caffeinate -is /Library/Developer/CommandLineTools/usr/bin/python3 -B /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013/source/scripts/policy_audit.py run --run /Users/oval/Development/fantasy-basketball-helper/local/full_policy_audit_20261013 --hours 7 --workers 1 --resume
```

The `--hours 7` value must still match the manifest; it does **not** grant seven
additional hours on resume. A second simultaneous launch is refused. Do not edit
the frozen `source/` tree. Normal app edits outside that tree cannot affect the run.

Keep the terminal open, Mac plugged in, and lid open. `caffeinate -is` prevents idle
sleep for the command lifetime and system sleep while on AC power. It does not
protect against lid-close sleep, shutdown/restart, depleted battery, or manually
forced sleep. Closing the agent conversation does not affect the terminal-owned job.

## Outputs

Inside the run directory, after launch:

- `main/CAN_I_FOLLOW_THE_TOOL.md` — concise readiness assessment and comparisons.
- `main/RESULTS.json` — separate per-model policy comparisons, uncertainty, roster
  distributions, latency, operational evidence and provenance.
- `main/EXAMPLES.md` — strong/typical/weak drafts and trace references.
- `main/tasks/` — completed drafts, complete decision traces and resumable checkpoints.
- `main/status.json`, `main/events.jsonl`, `main/logs/` — progress, heartbeat and failures.
- `manifest.json`, `READY.json`, `verified_setup.json`, `checks.json`,
  `operational.json`, `pilot/proof.json` — frozen provenance and preflight evidence.

Check report status before treating a partial checkpoint as the final evaluation.
Pilot outputs remain under `pilot/` and never enter the main evidence.
