# Lane G review focus (03-PARALLEL-EXECUTION "Review focus" 1–5)

How each review-focus risk is tested, by which executable check, against what, and what still needs a real deployment or
device. Check names are the ones in `tests/agent_ui_acceptance/corpus.py` (`REVIEW_FOCUS`); the contract test fails if a
named check disappears. "Harness" = cloud CI acceptance stack (real WSGI app, PostgreSQL 17 + migration 102, real Node parser
seam, harness Manager, fixture provider at the network boundary).

## RF1 — two tabs/surfaces apply a stale layout/action against changed domain data: reject/reconcile, not overwrite

| Check | What it proves | Environment |
|---|---|---|
| `api_corpus.Idempotency.test_two_tabs_one_effect` | two concurrent executes with one key → exactly one `pr_ui_actions` receipt, ≤1 audit row | harness |
| `api_corpus.Actions.test_stale_artifact_revision_refused` | activation for a non-current revision → 409, zero business delta | harness |
| `api_corpus.State.test_state_cas_conflict_keeps_other_tab` | second tab's state write from the same `stateRevision` → 409 with the current state; first tab's value kept | harness |
| `api_corpus.Edits.test_stale_base_hash_conflicts_before_spend` | edit on a stale `baseSourceHash`/revision → 409 before any reservation or provider request | harness |

Still needs: the same pair on the deployed canary (two browsers) during the live sample.

## RF2 — the person types while a stream, repair or patch arrives: input and focus survive, or a native conflict UI protects them

| Check | What it proves | Environment |
|---|---|---|
| `e2e:typing-during-stream` | composer value and focus unchanged across a slowed stream (fixture `slow` fault) | Chromium + WebKit emulation |
| `e2e:typing-during-patch` | a dirty generated input keeps its value across an explicit edit, or `[data-rafii-dirty-conflict]`/alertdialog appears | Chromium + WebKit emulation |

Still needs: real iPhone Safari (G15) with the on-screen keyboard; emulation never stands in for it.

## RF3 — a generated Query calls a write tool on mount: zero writes and an explicit denial

| Check | What it proves | Environment |
|---|---|---|
| `validator_corpus.Validator.test_query_write_name_rejected` | write names, concatenated and `$var` tool names never validate (no source reaches the browser) | harness (signed Node seam) |
| `api_corpus.NoAutomaticWrites.test_query_with_write_name_is_denied_without_writes` | 9 write names on `/queries` → denied; business/audit/UI-action counters and provider requests unchanged | harness |
| `e2e:no-auto-writes` | mount, render, replay and reload issue zero `/actions` or `/actions/activate` requests | Chromium + WebKit emulation |

## RF4 — the stream disconnects after provider work or a command commit: usage/idempotency reconcile; never a blind retry

| Check | What it proves | Environment |
|---|---|---|
| `api_corpus.Accounting.test_client_gone_settles_once` | client hangs up mid-stream → attempt `interrupted` (or finished), ≤1 settle row, else cost held `unknown` | harness |
| `api_corpus.Idempotency.test_aborted_response_after_commit_reconciles` | request sent then socket closed; same-key retry returns the stored result; one receipt | harness |
| `api_corpus.Durability.test_duplicate_create_reuses_attempt` | same presentation key → same artifact/attempt, provider-boundary delta 0 | harness |

Still needs: `F-disconnect` in the live runbook (deployed WSGI stream through Vercel).

## RF5 — consumer chat requests founder/private memory data or switches workspace mid-request: zero cross-scope leakage

| Check | What it proves | Environment |
|---|---|---|
| `api_corpus.Founder.test_consumer_and_founder_artifacts_do_not_cross` | founder-scope artifact 404 on consumer routes and vice versa | harness with `--founder-fixture` (BLOCKED on the consumer stack, by design) |
| `api_corpus.Isolation.test_foreign_workspace_path_reveals_nothing` | another tenant gets 403/404 on every route by both workspace paths; nothing echoed; zero writes/spend | harness |
| `api_corpus.Isolation.test_founder_scope_injection` | `surface: founder`, `scope`, `isFounder`, `workspaceId`, `principal` in a body → 400 at the A seam; founder routes refuse a consumer bearer | harness |
| `e2e:scope-switch-aborts` | after a workspace switch no request goes to the previous scope; in-flight UI requests are aborted | Chromium + WebKit emulation |
| `api_corpus.Privacy.test_untrusted_source_text_is_data` | a private marker in the message never reaches the presenter's provider request; an embedded instruction causes no write | harness (provider-boundary capture) |

## How results are read

Each check records `pass`, `fail` or `blocked` (a lane route still answering `ui_not_ready`, or a missing positive control)
in `$AGENT_UI_EVIDENCE_DIR/{api-corpus,validator-corpus,e2e-chromium,e2e-webkit}.json`; `summarize.py` folds them into gate
records; `release.py` refuses any gate whose evidence is stale, blocked, absent, or of a kind the gate does not accept
(a mock, fixture or emulation never satisfies a live-provider, deployment or physical-device requirement).
