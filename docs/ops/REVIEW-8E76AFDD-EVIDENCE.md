# REVIEW 8e76afdd: the evidence behind each closed finding

Raw outputs behind `H07-EVIDENCE.md` sections 4a and 5, copied from the agent's scratchpad so they survive it. Synthetic tenants, posts and ids only; disposable PostgreSQL 16 clusters; a mock Discord. Head under test: the merged line `d864f25f` (probes) and the branch head of each commit (tests and mutants).

## 1. The evaluator tests run against the reviewed evaluator (fail before)

The new `tests/test_discord_ops_check.py` (63 tests) run against `scripts/discord_ops_check.py` and the thresholds of `d864f25f` (the reviewed rules): 27 fail or error. On this branch all 63 pass.

```
ERROR: test_L3_an_internal_error_exits_3_and_a_log_drain_envelope_is_read (ReviewFindings.test_L3_an_internal_error_exits_3_and_a_log_drain_envelope_is_read)
ERROR: test_M4_an_unresolved_uncertain_admission_keeps_the_warning_after_its_window (ReviewFindings.test_M4_an_unresolved_uncertain_admission_keeps_the_warning_after_its_window)
ERROR: test_M6_held_and_failed_growth_against_the_previous_report (ReviewFindings.test_M6_held_and_failed_growth_against_the_previous_report)
FAIL: test_boundaries (Backlog.test_boundaries) (lag=900.0)
FAIL: test_boundaries (Backlog.test_boundaries) (lag=900.1)
FAIL: test_boundaries (Backlog.test_boundaries) (lag=2400.0)
FAIL: test_boundaries (Backlog.test_boundaries) (lag=2700.0)
FAIL: test_pages_sort_before_warnings (Baseline.test_pages_sort_before_warnings)
FAIL: test_the_thresholds_file_carries_every_value_the_rules_read (Baseline.test_the_thresholds_file_carries_every_value_the_rules_read)
FAIL: test_exit_codes_follow_the_worst_severity (CommandLine.test_exit_codes_follow_the_worst_severity)
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence) (detail='kind')
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence) (detail='version')
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence) (detail='source')
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence) (detail='missing:deliveries')
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence) (detail='missing:coordinator')
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence) (detail='missing:errors')
FAIL: test_M1_a_malformed_snapshot_is_an_alarm_not_silence (ReviewFindings.test_M1_a_malformed_snapshot_is_an_alarm_not_silence)
FAIL: test_M1_each_failed_section_warns_then_pages_when_it_persists (ReviewFindings.test_M1_each_failed_section_warns_then_pages_when_it_persists)
FAIL: test_M1_no_progress_still_pages_when_the_ledger_section_failed (ReviewFindings.test_M1_no_progress_still_pages_when_the_ledger_section_failed)
FAIL: test_M3_the_phase_is_required_on_the_command_line_and_the_function_defaults_to_open (ReviewFindings.test_M3_the_phase_is_required_on_the_command_line_and_the_function_defaults_to_open)
FAIL: test_M5_the_probing_message_no_longer_says_hold_first (ReviewFindings.test_M5_the_probing_message_no_longer_says_hold_first)
FAIL: test_M6_work_due_and_nothing_reaching_discord (ReviewFindings.test_M6_work_due_and_nothing_reaching_discord)
FAIL: test_M8_fetch_has_one_overall_deadline (ReviewFindings.test_M8_fetch_has_one_overall_deadline)
FAIL: test_M8_fetch_never_follows_a_redirect_and_never_sends_the_bearer_elsewhere (ReviewFindings.test_M8_fetch_never_follows_a_redirect_and_never_sends_the_bearer_elsewhere)
FAIL: test_M8_fetch_refuses_plain_http_to_another_machine (ReviewFindings.test_M8_fetch_refuses_plain_http_to_another_machine) (url='http://rafii.example.invalid/api/ops/discord/health')
FAIL: test_M8_fetch_refuses_plain_http_to_another_machine (ReviewFindings.test_M8_fetch_refuses_plain_http_to_another_machine) (url='ftp://rafii.example.invalid/')
FAIL: test_M8_fetch_refuses_plain_http_to_another_machine (ReviewFindings.test_M8_fetch_refuses_plain_http_to_another_machine) (url='file:///etc/hosts')
Ran 63 tests in 5.449s
FAILED (failures=24, errors=3)
```

## 2. The reviewer's runbook probes re-run on the merged head `d864f25f`

Command: `REV=<worktree> POSTRIFF_PG_BIN=/usr/lib/postgresql/16/bin python exp_runbook.py e2 e1 e1c e3b` (the reviewer's script, unchanged); E2 also with a 10-second permit lifetime and as a control without any hold.

### E1 (the lane does not own Discord; the hold lands right after a create was accepted)

```
  after create + hold   : [{'state': 'provider_accepted', 'checks': 0, 'nextIn': 4.9, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord created the approved channel message; read-back pending'}]  POSTs on the wire: 1
  hold-on step 1        : [{'state': 'uncertain', 'checks': 1, 'nextIn': 4.9, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}]
  hold-on step 5        : [{'state': 'uncertain', 'checks': 5, 'nextIn': 86400.0, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}]
  hold-on step 8        : [{'state': 'uncertain', 'checks': 8, 'nextIn': 86399.9, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}]
  after HOLD_OFF + step : [{'state': 'verified', 'checks': 9, 'nextIn': 4.9, 'nextAction': 'Inspect receipt', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord read-back matched the approved text, bot, channel and mention policy.'}]  (nextIn near 86400 = parked a day; the message IS in Discord: 1 message)
  duplicates on the wire: 0
```

Read: each refused read-back burns one check; the fifth parks the post for 86,400 s as "manual provider review" (the probe then forces `nextAt` to show it would verify). E1 survives on the merged head.

**Re-run on 2026-10-28 against the limiter's read wait.** Limiter `1fe434c7` (B4, "a read refused by a hold is a wait") makes a read under a hold a 300 s deferral that refunds its check. The same probe, unchanged, on the sparse scratch merge `65abc75f` (alerts `f7a111f4` + limiter `68f968a7` + W-02 `4cf85a78`; local, never pushed):

```
  after create + hold   : [{'state': 'provider_accepted', 'checks': 0, 'nextIn': 5.0, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord created the approved channel message; read-back pending'}]  POSTs on the wire: 1
  hold-on step 1        : [{'state': 'provider_accepted', 'checks': 0, 'nextIn': 300.0, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord message receipt retained; awaiting shared capacity for the exact read-back. Do not'}]
  hold-on step 5        : [{'state': 'provider_accepted', 'checks': 0, 'nextIn': 300.0, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord message receipt retained; awaiting shared capacity for the exact read-back. Do not'}]
  hold-on step 8        : [{'state': 'provider_accepted', 'checks': 0, 'nextIn': 300.0, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord message receipt retained; awaiting shared capacity for the exact read-back. Do not'}]
  after HOLD_OFF + step : [{'state': 'verified', 'checks': 1, 'nextIn': 4.9, 'nextAction': 'Inspect receipt', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord read-back matched the approved text, bot, channel and mention policy.'}]  (nextIn near 86400 = parked a day; the message IS in Discord: 1 message)
  duplicates on the wire: 0
```

Read: with the read wait the frozen path spends no check under the hold and does not park the post; after the lift it verifies with one check. E1 still describes every build without the read wait (RC1, and the serving build until the limiter ships); the payload's `config.holdReadWaitSeconds` and the hold alert say which applies. E1c below (the pinned RC1 file) is the rollback case and is unchanged.

### E1c (the pinned RC1 worker serving while the hold is on)

```
  hold set: True  readback: (1, 1)  POSTs: 1
  RC1 tick 1 under hold :
       {'state': 'scheduled', 'checks': 0, 'nextIn': 299.6, 'nextAction': 'Await Discord shared rate budget; no POST occurred and this approval remains frozen', 'intents': 0, 'ref': False, 'stage': 'released', 'lastEvent': 'Proven unsent Discord operation released: rate_delayed'}
       {'state': 'uncertain', 'checks': 1, 'nextIn': 4.8, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}
  RC1 tick 5 under hold :
       {'state': 'scheduled', 'checks': 0, 'nextIn': 299.6, 'nextAction': 'Await Discord shared rate budget; no POST occurred and this approval remains frozen', 'intents': 0, 'ref': False, 'stage': 'released', 'lastEvent': 'Proven unsent Discord operation released: rate_delayed'}
       {'state': 'uncertain', 'checks': 5, 'nextIn': 86399.8, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}
  RC1 tick 8 under hold :
       {'state': 'scheduled', 'checks': 0, 'nextIn': 299.6, 'nextAction': 'Await Discord shared rate budget; no POST occurred and this approval remains frozen', 'intents': 0, 'ref': False, 'stage': 'released', 'lastEvent': 'Proven unsent Discord operation released: rate_delayed'}
       {'state': 'uncertain', 'checks': 8, 'nextIn': 86399.8, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}
  after HOLD_OFF + 3 RC1 ticks (the parked read-back is NOT retried by itself; the unsent post resumes):
       {'state': 'provider_accepted', 'checks': 0, 'nextIn': 4.5, 'nextAction': 'Await provider reconciliation; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord created the approved channel message; read-back pending'}
       {'state': 'uncertain', 'checks': 8, 'nextIn': 86398.2, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord receipt lookup is unavailable. Keep the original message ID; do not resubmit.'}
  POSTs: 2 duplicates: 0
```

Read: the unsent post is pushed back 5 minutes per claim; the created post is parked after tick 5 and is still parked after the lift and three more ticks. E1c survives.

### E3b (an approval ending 200 s after the claim)

```
  before the claim: [{'state': 'scheduled', 'checks': 0, 'nextIn': -3400.6, 'nextAction': None, 'intents': 0, 'ref': False, 'stage': None, 'lastEvent': 'Waiting for the local durable worker'}]
  claim under hold: [{'state': 'held', 'checks': 0, 'nextIn': 300.0, 'nextAction': 'Discord rate wait outlasts approval; review the frozen destination and approve again', 'intents': 0, 'ref': False, 'stage': 'released', 'lastEvent': 'Proven unsent Discord operation released: rate_delayed'}]
  after HOLD_OFF + step (a held post is not retried; it needs a NEW approval by a person): [{'state': 'held', 'checks': 0, 'nextIn': -1792738337.0, 'nextAction': 'Discord rate wait outlasts approval; review the frozen destination and approve again', 'intents': 0, 'ref': False, 'stage': 'released', 'lastEvent': 'Proven unsent Discord operation released: rate_delayed'}] POSTs: 0
```

Read: one claim under the hold makes the post `held` (a person must approve it again); the lift does not retry it. E3b survives.

### E2 (two posts sealed when the hold lands), 10-second permits, and the control without a hold

With the hold:

```
  warm-up done; jobs: ['scheduled', 'scheduled', 'provider_accepted']  POSTs so far: 1
  both workers sealed and are about to consume: True
  publish admissions before the hold (state,is_publish): [('observed', True), ('sealed', True), ('sealed', True)]
  HOLD_ON executed; readback: (1, 1)
  POSTs on the wire: 1  messages in Discord: 1
  publish admissions after (state,status,is_publish): [('observed', 200, True), ('sealed', None, True), ('blocked', None, True)]
  DRAIN_CHECK (live_leases, sealed_now, uncertain_to_reconcile): (0, 1, 0)
  POSTs on the wire: 2  duplicates: 0
      {'state': 'verified', 'checks': 1, 'nextIn': -1792738566.0, 'nextAction': 'Inspect receipt', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord read-back matched the approved text, bot, channel and mention policy.'}
      {'state': 'verified', 'checks': 1, 'nextIn': -1792738566.0, 'nextAction': 'Inspect receipt', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord read-back matched the approved text, bot, channel and mention policy.'}
      {'state': 'uncertain', 'checks': 7, 'nextIn': 86399.9, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': False, 'stage': 'done', 'lastEvent': 'The original Discord target or message ID is missing. Manual reconciliation required; do n'}
```

Control (the same probe, `HOLD_ON` replaced by nothing; the read-back shows held 0):

```
  both workers sealed and are about to consume: True
  publish admissions before the hold (state,is_publish): [('observed', True), ('sealed', True), ('sealed', True)]
  HOLD_ON executed; readback: (1, 0)
  POSTs on the wire: 1  messages in Discord: 1
  publish admissions after (state,status,is_publish): [('observed', 200, True), ('blocked', None, True), ('sealed', None, True)]
  DRAIN_CHECK (live_leases, sealed_now, uncertain_to_reconcile): (0, 1, 0)
  POSTs on the wire: 2  duplicates: 0
      {'state': 'verified', 'checks': 1, 'nextIn': -1792738670.4, 'nextAction': 'Inspect receipt', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord read-back matched the approved text, bot, channel and mention policy.'}
      {'state': 'verified', 'checks': 1, 'nextIn': -1792738670.4, 'nextAction': 'Inspect receipt', 'intents': 1, 'ref': True, 'stage': 'done', 'lastEvent': 'Discord read-back matched the approved text, bot, channel and mention policy.'}
      {'state': 'uncertain', 'checks': 7, 'nextIn': 86399.9, 'nextAction': 'Manual provider review required; do not resubmit', 'intents': 1, 'ref': False, 'stage': 'done', 'lastEvent': 'The original Discord target or message ID is missing. Manual reconciliation required; do n'}
```

Read: the probe's threads wait inside `consume` longer than the permit lifetime on this loaded machine, so the reviewer's interleaving (A posts, A's observation blocks B) is not reached. One sealed post that was never sent ends "uncertain, target or message ID missing" with or without the hold: a loop stalled between sealing and sending past its permit and lease, the case W-02 documents as uncertain by design. The hold-blocked case itself is covered by W-02 `466232ab` and `f525aa17` and their tests.

## 3. The reviewer's vacuous mutants re-run on this branch

Command: the reviewer's `mutate.py` (copy of the worktree with one change, then `tests/discord_ops_drills.py --only ...`). Before (reviewer, `8e76afdd`): both PASS, so the drills did not test these properties. Now:

```
{"mutation": "M1_coordinator_ignores_hold", "drills": "O1,O2", "exit": 1, "drill_results": {"O1": "FAIL", "O2": "FAIL"}, "failed_checks": {"O1": ["nothing was admitted after the hold committed"], "O2": ["the coordinator refuses the older worker under the hold: no create sent (review M7)"]}}
{"mutation": "M5_drain_check_blind", "drills": "O2", "exit": 1, "drill_results": {"O2": "FAIL"}, "failed_checks": {"O2": ["drain check sees the create in flight: a live lease, a sealed post and its admission (review C1, M7)", "2: drain check: no live lease and nothing in flight, so the worker can be switched"]}}
exit=0
```

## 4. 2026-10-28: the limiter and W-02 heads (fail before, pass after)

The coordinator's resume of 2026-10-28 (D3 red against the limiter head, W-02's new counters and lag split, failed reads as observed 503, retention fields). Each new test was written first and run against the code just before its fix: `e79df41d` (the head before this work) for 4.2 and 4.3; that tree with the 4.2 and 4.3 fixes for 4.4 (all three in `5a04369e`); `1c7966ce` for 4.5 (fixed in `da6973ff`). Outputs condensed to the failing lines. All pass on `828192e8` and on the scratch merge (`H07-EVIDENCE.md` section 4a).

### 4.1 D3 on the scratch merge before the fix

`e79df41d` + limiter `e6aa7db8` + W-02 `090c7ce6` (sparse scratch merge, local), `tests.test_discord_ops_drills_postgres` and `tests.test_oncall_drills_postgres`:

```
FAIL: test_d3_rate_limit (tests.test_discord_ops_drills_postgres.IsolatedDrills.test_d3_rate_limit)
AssertionError: Lists differ: [{'check': 'budget spent for the last minu[64 chars]one}] != []
{'check': 'budget spent for the last minute: RATE_APP_BUDGET_SPENT is warn', 'pass': False, 'observed': None}
Ran 28 tests in 273.122s
FAILED (failures=1)
```

After (`d995ff13` = alerts `828192e8` + limiter `68f968a7` + W-02 `4cf85a78`): 28 tests OK; the receipt's D3 row is in `DRILL-RECEIPT-ISOLATED.md`. In between, one run of the receipt on `65abc75f` failed D3 for the machine, not the rule: under other sessions' load the single demand loop reached 102 admissions of the 109.1 the coordinator can grant (0.935, below 0.95), so the alert correctly stayed silent; D3 now asks with three loops and checks the injection itself (`43553f98`).

### 4.2 Task 1: the achievable ceiling and the guard from the build

```
ERROR: test_the_payload_reports_the_guard_the_serving_coordinator_uses
FAIL: test_a_guard_above_a_tenth_of_the_window_counts_as_a_tenth
FAIL: test_an_unknown_guard_is_the_largest_the_coordinator_allows
FAIL: test_application_budget_spent_against_the_achievable_ceiling (admitted=1296)
FAIL: test_application_budget_spent_against_the_achievable_ceiling (admitted=1363)
FAIL: test_continuous_demand_under_the_limiters_guard_is_reported
Ran 15 tests in 0.016s
FAILED (failures=5, errors=1, skipped=1)
```

### 4.3 Tasks 2 to 4: W-02's counters, quarantine, lag split and pause; failed reads; retention

```
ERROR: test_a_quarantined_workspace_is_a_warning_with_its_error_class_only 
ERROR: test_the_create_and_read_back_thresholds_are_the_lanes_own 
ERROR: test_the_lane_counters_include_quarantined_and_positions_kept 
FAIL: test_a_known_pause_never_pages_and_says_so  (rule='BACKLOG_LAG')
FAIL: test_a_known_pause_never_pages_and_says_so  (rule='SILENT_HALT_NO_PROGRESS')
FAIL: test_a_known_pause_never_pages_and_says_so  (rule='SILENT_HALT_NO_CREATE')
FAIL: test_a_known_pause_never_pages_and_says_so 
FAIL: test_late_creates_use_the_lanes_split_at_300_seconds_and_page_at_the_backlog_page  (lagging line, creates 301 s)
FAIL: test_late_creates_use_the_lanes_split_at_300_seconds_and_page_at_the_backlog_page  (lagging line, creates 2701 s)
FAIL: test_read_backs_deferred_by_a_burst_warn_only_past_an_hour 
FAIL: test_retention_behind_when_settled_rows_outlive_three_retentions 
FAIL: test_retention_purged_and_remaining_counts_are_read_when_present 
FAIL: test_server_errors_include_failed_reads_and_say_so 
AssertionError: 'failed before an answer' not found in 'Discord server errors are 5.0% of 100 responses in 5 minutes. Usually a Discord outage: do not roll back (RUNBOOK-INCIDENT 4.A).'
Ran 10 tests in 0.170s
FAILED (failures=10, errors=3)
```

### 4.4 The hold alert follows the build's read wait (limiter `1fe434c7`)

```
ERROR: test_the_payload_says_whether_a_read_under_a_hold_waits
KeyError: 'holdReadWaitSeconds'
FAIL: test_the_hold_message_follows_what_the_serving_build_does_with_a_read_under_a_hold
AssertionError: 'parked' unexpectedly found in "The operator hold is on: Discord sends nothing and posts wait. A post needs a new approval from about 55 minutes after its own scheduled time, and while the lane does no...
Ran 19 tests in 0.345s
FAILED (failures=1, errors=1)
```

(The 19 tests of that run include the 17 policy tests, which pass.)

### 4.5 A lagging line from before a recovery

```
FAIL: test_a_lagging_line_from_before_the_recovery_does_not_keep_the_alert
AssertionError: 'page' is not None
Ran 1 test in 0.001s
FAILED (failures=1)
```

### 4.6 Every alert id has an on-call priority

`Priorities.test_every_evaluator_rule_and_severity_has_a_row` with the count raised to 42 and no new rows: `Lists differ: [('RATE_RETENTION_BEHIND', 'warn'), ('SILENT_HALT_QUARANTINE', 'warn')] != []`; with the count at 40: `AssertionError: 42 != 40`. Passes with the two rows in `h07-oncall-policy.json`.

### 4.7 Route circuits opened by a 403 (limiter `7f8eacb6`, B2)

Seen in the regenerated receipt: D3's sixteen 403 answers now also raise `RATE_ROUTE_CIRCUITS` (warn), whose message said every circuit came from server errors. Run on `43553f98`, fixed after it:

```
FAIL: test_route_circuits_name_a_403_refusal_as_a_cause
AssertionError: '403' not found in '16 Discord routes have a short circuit open after repeated server errors.'
Ran 1 test in 0.002s
FAILED (failures=1)
```
