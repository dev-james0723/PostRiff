# Agent handoff — continue Rafii × Twitch G1

**Keep the full public-integration goal open. Do not restart from G0. Do not overwrite other missions or claim production completion.**

## Read first

Read this directory's `README.md`, `acceptance-results.json`, `oauth-regression-results.json`, `ui-acceptance.md`, `FEATURE-STATUS.md`, `native-api-sources.md` and `APPROVAL-PACKET.md`. The distribution `RECEIPT.json` supplies the exact committed revision and checksums. Preserve the earlier Mac START-AGENT-PROMPT, AGENT-HANDOFF, README and original G0 ZIP.

Canonical repository: `dev-james0723/PostRiff`. Candidate branch: `codex/rafii-twitch-full-20261018`. Base: `7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1`. Production Supabase: `buoyhkbodnhzngaotoel`. Staging `oxacvkhpfgytkepxcaqh` is never production.

Cloud worktree: `/workspace/scratch/84c4d423cd8c/rafii-twitch-worktree`.

Requested persistent Mac continuation directory: `/Users/ouxianxing/Documents/Rafii-Twitch-FullAccess-20261018/Engineering-G1`. Its distribution receipt records the installed isolated worktree path, branch and commit after transfer verification. The separate local Git metadata borrows the canonical checkout's object store; retain the bundle and patch. Do not prune, clean, reset or switch the existing canonical checkout.

## Authorization and ownership

James authorized reversible isolated engineering, free offline/mock/synthetic tests, docs and local commits. Push/PR/merge, production change/deployment, paid resources, app creation, live external actions and message sending require approval. Prepare the full concrete result before asking. No credentials or security codes in chat. Login challenges are handled by James in the browser. Do not stop Piano or other Agents. Use the free isolated runner for builds/tests because the Mac was under substantial swap pressure.

Ownership during this phase:

| Owner | Files/area |
| --- | --- |
| Root | Twitch service, HTTP mount, durable migration, worker, PostgreSQL/runtime tests, final acceptance/docs/commit |
| `twitch_oauth_engineering` | OAuth adapter/custody, providers, minimal Channels projection, Agent tools/authz/registry, associated tests; composite my_channels attribution fix |
| `twitch_api_verification` | 112-operation native registry/executor, native tests/sources, EventSub/HTTP boundary tests; final verifier hardening |
| `twitch_native_ui` | Actual native page/controls/API client, Channels integration, Site Agent route/privacy metadata and frontend tests |

Files were frozen for consolidated acceptance. Existing mission files outside this isolated worktree were not changed. Reconfirm live ownership before new edits; these ownership notes do not authorize overwriting another agent's newer work.

## Core integration contracts

- `TwitchProvider` is mounted by the existing provider registry. Confidential auth-code callback is pinned to `https://rafii.io/api/oauth/twitch/callback`. Optional identity scopes are empty; actual grants are verified.
- `oauth.token_for_worker(workspace_id, connection_id)` returns server-only validated custody. `raw_access_token`, `credential_subject` and `credential_generation` inspect sealed envelopes. Do not treat raw opaque tokens as stored envelope values.
- `oauth.twitch_lifecycle(cur, ws, conn, event, generation)` runs within the custody transaction. The lock order is workspace → credential → action → subscription → event. Challenge handling locks subscription and only reads credential state without a row lock; there is deliberately no direct EventSub receipt→credential FK.
- Native `prepare_operation` returns an immutable authenticated object. Its `as_dict()` contains stable semantic approval data, not refreshed evidence timestamps. `execute` dispatches once. `execute_sensitive` sends stream keys only through a human secret sink.
- Service `preview` binds actor/workspace/connection/generation, normalized payload, precise execution time and rights/marker declarations. PostgreSQL timestamps are rounded to microsecond precision before digest/due checks. `approve` requires exact hash, current actor and a recent interactive session.
- `dispatch_one` commits `dispatching` before the provider write and rechecks authority under locks. Lost/ambiguous writes become terminal unknown outcomes. Never turn `accepted`, `partial` or `outcome_unknown` into success or automatic mutation retries. Clip reconciliation performs a distinct GET when a known ID exists.
- `read` receives `{payload: ...}` at the HTTP layer. `twitch.account.verify` explicitly refreshes cached account/live context. `twitch.eventsub.events` serves the authenticated human inbox only.
- `secret_access` requires exact approved manifest and fresh human session; no Agent/API-token access. Stream keys and approved clip URLs are not stored in ordinary results, logs or Agent context. Clip media is never fetched automatically.
- EventSub verifies HMAC over exact bytes, timestamp bounds, message identity, version/condition, known generation and a nonempty provider ID. Pending subscription binding occurs only via an authenticated challenge. Revocation message type must match a documented revoked status inside the signed body.
- Content storage and AI processing are separate default-off purpose gates. Withdrawal purges stored events/stops queued AI actions; a Twitch OAuth scope does not grant those purposes.
- The native UI excludes its complete provider-content body from generic Site Agent collection. The three Agent tools are local context, numeric snapshot and unapproved action draft. They cannot approve or dispatch. `authz.IN_TOOL.get()` is the correct state check; `authz.in_tool()` is a context manager.
- Existing generic text publishing explicitly rejects Twitch with `twitch_native_only`.

## Resume offline acceptance

Cloud Python dependencies installed during this phase:

```text
/workspace/scratch/84c4d423cd8c/twitch-test-deps
/workspace/scratch/84c4d423cd8c/twitch-sdk-deps
```

The latter includes repository-pinned `openai-agents==0.22.3` and `openai==3.19.2`. SDK import/registration is tested offline with tracing disabled. No model request is required.

The actual PostgreSQL sandbox is `/tmp/rafii-twitch-pg-20261018`, localhost port 55439, database `rafii_twitch_test`, OS/database user `nobody`. It is a disposable free Linux runner, not Supabase. The fixture rejects every other host/port/database before SQL. It creates a minimal Rafii fixture plus migration 134 and destroys only that disposable schema between acceptance runs. Recreate a sandbox if the transient runner is gone; never point it at a real workspace database.

Run from the owned worktree:

```sh
RAFII_TWITCH_TEST_DSN='host=127.0.0.1 port=55439 dbname=rafii_twitch_test user=nobody' \
PYTHONPATH=src:tests:/workspace/scratch/84c4d423cd8c/twitch-sdk-deps:/workspace/scratch/84c4d423cd8c/twitch-test-deps \
python3 scripts/verify_twitch_offline.py --require-postgres --output-dir /tmp/rafii-twitch-recheck
```

Use a new output directory for repeat verification so that committed acceptance receipts remain historical evidence. Without the explicit DB DSN, PostgreSQL tests skip and must not be reported as passed.

Frontend commands and exact dependency versions are in `ui-acceptance.md`. The final complete project dependency copy is `/tmp/rafii-twitch-ui-project-deps/node_modules`, linked by ignored `web/node_modules`. It is disposable and not packaged. Install the existing lockfile only in a suitable free isolated runner; do not run a heavy Mac build. No tracked dependency files changed.

## Concrete remaining work

1. Verify the distribution SHA-256 and installed commit; read current canonical HEAD and ownership. Do not assume the main Mac checkout HEAD is current. Preserve its existing uncommitted files.
2. Use approval packet A to publish the reviewed candidate as a draft PR only when James approves. Review/rebase current production schema and migration numbering. The complete production migration chain remains unverified.
3. After the separate deployment approval, release the disabled candidate to canonical production and verify the exact callback and source revision. Current public callback is 404; code-level tests are not proof of deployment.
4. Present the single browser security-login handoff for the Twitch console, then create the reviewed confidential app only with authorization. Store secrets directly in the approved secret store. No inherent Google console dependency has been established.
5. Finish material commercial application facts and obtain approval to submit the unsent request. Keep marketing, storage and AI purpose decisions separate and record written outcomes.
6. Establish a restricted canary, then run the named live OAuth/EventSub/native tests with per-action approval. Do not enable a global public flag without the canary and release controls. Verify worker hourly sweep capacity, deployment deadlines, operational alerts, tenant isolation, retention/deletion and deployed browser/accessibility behavior.
7. Continue any specialized Twitch products only as separately owned/authorized adapters; do not mislabel unimplemented extension JWT, Drops/org or Guest Star beta functionality as unavailable APIs.

The next phase should preserve the current engineering and continue from these pending gates. Passing offline tests never closes the full public integration goal.
