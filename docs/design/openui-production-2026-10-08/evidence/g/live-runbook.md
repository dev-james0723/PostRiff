# Live sample runbook (G03 / G04 / G05 / G10 / G17 / G18) — for A, through the real UI

Production sign-in is a passkey in a real browser, so the 60-generation G03 corpus runs through the real UI. No bearer token is
ever copied out of the browser or written to disk. `scripts/agent_ui_live.py` prints what to run and turns the results into
evidence. Keep `--origin` explicit (rafii.io DNS was still propagating on 2026-10-08; use the alias that serves the
candidate if rafii.io does not resolve yet, and record which one).

## 0. Preconditions (stop if any is missing; the affected gates stay unverified)

- The candidate SHA is deployed and `GET /api/workspaces/{W}/agent/status` shows `genui.enabled` for the allowlisted test
  workspace `W` (`RAFII_GENUI_ENABLED=1`, `RAFII_GENUI_WORKSPACES=W`; actions/edits flags as intended).
- `W` holds known, consented records for every journey (drafts, calendar items, Library photos/videos, voice sources,
  a campaign, analytics history, saved research, automations; founder data for J09 on the founder surface).
- Budget: the plan is 69 generations (60 normal + 9 edits) plus the 3 fault cases. At run-3 rates (2026-10-09: 2.29 USD
  for 27 cases + 8 edits, ≈0.065 USD per generation with its Manager turn) a full run costs ≈4.7 USD; the runner's per-case
  estimate is 0.07 USD. Approve a cap that covers it (the existing canary cap of 5 USD leaves ≈0.3 USD headroom). If the cap
  is reached, stop: the remaining cases stay **unverified**; they are never replaced by fixtures or by other cases.
- Note the UTC start time `T` before the first case (for the server export).

## 1. Get the plan and the collector

```
python scripts/agent_ui_live.py plan > /tmp/rafii-live-plan.json          # 60 normal (6 × J01–J09 + 6 composite), 9 edits, 3 faults, runOrder
python scripts/agent_ui_live.py browser-snippet > /tmp/rafii-live-snippet.js
```

Sign in at the origin (passkey), open the full chat (`/app/agent`), and evaluate the snippet in the page (e.g. Claude in
Chrome `javascript_tool`). It answers `installed`. It lives in page memory: run `__rafiiLive.collect()` and save the result
**before** any full reload, then re-evaluate the snippet. Do the J09 cases in the founder panel with its own copy of the
snippet and save that collection to a second file.

## 2. The 60 normal cases (the fixed G03 corpus, in `runOrder`; the first one, J01-a, is the cold case)

The corpus is fixed (D-A53, `corpus.id` `g03-live-60/v2`, `corpus.sha256` `703b54cd…`): run every case exactly as printed,
never reword, skip, swap or add one. Follow `runOrder` from top to bottom; each entry is one conversation:

- `"start": "new"`: open a new conversation (consumer entries in the full chat, J09 entries in the founder panel) and run
  its `cases` in order as consecutive turns. A case listed in `corpus.followUps` refers to the turn before it, so it only
  makes sense in that conversation; never run it on its own.
- `"start": "reopen <caseId>"`: an edit case (section 3); reopen that conversation and the case's artifact.

All consumer entries come first, then the founder panel once (J09-1, J09-2, J09-edit). For each `normal` case:

```
__rafiiLive.begin('<caseId>')        // e.g. 'J01-a'
```
type the case's `prompt` into the composer and send; wait until `performance.getEntriesByName('rafii-genui:ready').length`
grows (or the view falls back natively); then `__rafiiLive.end()`. Touch nothing else during a case. Never retry a failed
case: a failure is recorded as it happened, because the denominator is fixed at 60. `ingest` counts only the plan's case
ids (any other id is reported as unplanned and never counted), and a case that shows more than one artifact (re-run under
the same id) never counts as first-pass valid.

## 3. The 9 edit cases

In `runOrder` they follow the consumer conversations (J09-edit runs in the founder panel). Reopen the artifact of `<J>-a`,
`__rafiiLive.begin('<J>-edit')`, use the view's explicit edit affordance and type the case's `instruction`, wait for
`rafii-genui:ready`, `__rafiiLive.end()`. Check by eye that filters/selections/typed values survived (note anything lost
in `faults` below).

## 4. G04, G05, G18 in the page

```
probe = await __rafiiLive.probe('<W>')                                     // G04: ≥3 spaced frames before the end, UTF-8 split
p = __rafiiLive.count('/agent/ui/(queries|presentations|edits)', 6000)    // G05: start, then change a filter in a generated view
filter = await p                                                           //      within 6 s
h = __rafiiLive.count('/agent/ui/(queries|presentations/:id/events)', 40000)  // G18: switch to another tab for 40 s, come back
hidden = await h
```
G05 also needs the server's model-attempt delta: run
`select count(*) from public.pr_ui_attempts where workspace_id='<W>'` (read-only) just before and after the filter change.

## 5. Faults (separate from the denominator; record what you saw)

`F-cancel` press Stop while a view streams → `ui.canceled`, native answer kept. `F-disconnect` close the tab mid-stream,
reopen → interrupted, last valid revision shown, no new generation on reopen. `F-retry` explicit Try again after a failure →
cost/consent shown first, one new attempt.

## 6. Save, export, ingest

In each page: `r = __rafiiLive.collect(); r.probe = probe; r.filterCheck = {queryRequests: filter.routes.filter(x => x.includes('queries')).length,
presentationOrEditRequests: filter.routes.filter(x => !x.includes('queries')).length, modelAttemptDelta: <after − before>};
r.hiddenCheck = hidden; r.faults = [...]; JSON.stringify(r)` → save to a scratch file (it holds timings and ids, no text).

```
python scripts/agent_ui_live.py server-sql --workspace <W> --since <T>       # read-only SQL; run it on the production DB (Supabase
                                                                            # execute_sql) and save the JSON array as attempts.json
RAFII_LIVE_CHECKS=1 python scripts/agent_ui_live.py ingest --origin https://rafii.io --workspace <W> --budget-usd 5 \
  --sha <deployed sha> --browser-results consumer.json founder.json --server-rows attempts.json
```

`ingest` writes `evidence/g/live-<sha>-<timestamp>.json` (cases, verdicts, budget, declared time origins; workspace only as a
hash) and `evidence/g/results/live-<sha>-<timestamp>.records.json` (gate records that `release` mode reads). It exits 0 only
when every live verdict passes. Commit both files. A short sample or a reached budget cap leaves the affected gates
`unverified` with the exact missing case ids; it is never relabelled. G03 fails before the sample is complete only when
the cases already collected can no longer reach 59/60 first pass or one of them is not functional after its repair.

## What each verdict means

| Gate | Pass rule (from 04-ACCEPTANCE) | Source |
|---|---|---|
| G03 | ≥59/60 (98.3%) first-pass valid (initial attempt ready, no repair) on the fixed corpus; 60/60 functional after ≤1 repair; fails as soon as 2 cases miss the first pass or 1 is not functional, otherwise unverified until all 60 are collected (D-A53) | server attempt rows |
| G17 | warm p95 presentation-start → `rafii-genui:first-component` ≤ 8 s; → `rafii-genui:ready` ≤ 30 s; cold case reported separately; end-to-end turn time reported separately | page marks + resource timing |
| G04 | probe: ≥3 frames, first→third ≥1 s apart and before the stream ends; multi-byte payload decoded with `TextDecoder(stream:true)`; split observed is reported | in-page probe |
| G05 | a filter change issues ≥1 query request, no presentation/edit request, model-attempt delta 0 | page + 2 counts |
| G18 | hidden for 40 s: zero query/replay requests | page |
| G10 (live part) | 9/9 edit cases ready | server rows |
