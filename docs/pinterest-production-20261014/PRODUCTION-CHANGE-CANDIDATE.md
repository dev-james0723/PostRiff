# Existing production Pinterest change candidate

2026-10-14 UTC. **Prepared only; NO-GO for release.** No new organization/database. Canonical Supabase: `postriff-phase2-private` / `buoyhkbodnhzngaotoel`; Vercel project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; origin `https://rafii.io`.

Current source `6d36716cfcc945fcc93a819ba243ffa870a1a799` adds quota hardening to the previously tested b99cf89a candidate. Live rafii.io now uses5e4f4e13; this newer account-security baseline is not yet merged. [Pending exact local merge](NEXT-ACTION-MERGE.md). The earlier cab2b288 diff/fingerprints and bcz5vdqznw remain historical evidence. New quota-only cloud7lkkltn4d9 PASS; no full-project CI or current-live compatibility claim. Pro/overdue remains observed, but a later READY deployment means billing status alone does not prove a deployment block. No deployment attempted.

## Additive DB delta

Existing OAuth vault/transaction and tenant schemas are reused. Do not apply the 81-file clean-bootstrap inventory to this existing database. The one new Pinterest quota candidate is `migrations/postriff/20261014_pinterest_rate_budgets.sql`, SHA256 `9a9b20f0e41ce5ba65c1bf013ed9e427e4b60237dc1e9130ac9043253f56fce4`. Current production metadata confirms the table absent. Its fields contain hashed app/account keys and rate counters, no tokens/content. The read-only pilot also requires this table and now counts token exchange/refresh against100 requests/day. Current production OAuth constraint metadata confirms the existing exchange_started/denied states used for callback claiming/cancellation. RLS enabled and forced; PUBLIC/anon/authenticated have no privileges. Explicit REVOKE ALL removes inherited service_role grants before restoring only SELECT/INSERT/UPDATE/DELETE, including under actual Supabase broad default grants. Fresh disposable PG tests confirm quota concurrency/recovery and client read denial.

Before applying: rerun absence/schema/privilege preflight, preserve a migration receipt, apply only the reviewed additive file transactionally through the approved runner. Stop on drift. Actual production apply, PostgreSQL17 runtime and canary are NOT RUN. Quota maintenance/deletion is separately approved. Rollback: pause Pinterest gates and jobs first; reviewed DROP of quota table makes publishing fail closed. Do not delete posts, receipts or credentials for rollback.

## Exact configuration direction

Use the existing production Auth/database project and existing production vault key; never install the locally generated staging key or rotate the shared vault key. Existing production secret values were not read. Actual DSN/Auth-key binding still needs secure release preflight, not inference from env names.

App ID `1615884`; client ID/secret absent from Production env metadata. Callback-origin value freshly read as `https://postriff-phase2-private.vercel.app`; the exact `https://rafii.io/api/oauth/pinterest/callback` was separately approved, registered and verified after reload. That console action is complete. Approved final production origin is `https://rafii.io`; proposed official callback `https://rafii.io/api/oauth/pinterest/callback` must be checked against the provider before any change. Install existing App secret privately, never reset it or write it to evidence. Credential install is part of a concrete separately reviewed production operation after release prerequisites qualify.

Keep public ENABLED/VERIFIED/REVIEWED/POLICY_APPROVED flags and Agent provider-data gates closed until their own evidence qualifies. Provider console currently says Trial access active. Sandbox/Trial credentials and results must not be described as public Standard publication. No public customer connections before Standard Access.

## Remaining critical path

Obtain the intended Rafii workspace and Pinterest account from the human, then prepare a narrowly scoped real OAuth/Trial pilot on existing approved infrastructure. The previous dedicated-new-DB Step A design is superseded; it is not a grant for a shared-production test or customer publishing. Define tenant/job/credential/session containment and the exact callback/deployment/config effects before requesting that pilot approval. Reuse existing projects and do not provision an organization/database.

Human consent and a frozen specific Pin approval remain separate. Capture real identity/boards/refresh/reconnect/disconnect and read-back, scheduling, failure recovery and actual tenant isolation. Prepare the real demo video and Standard package, obtain submission approval and record official provider approval. Only then finalize the exact production release/canary operation. Current source integration/scoped CI passing does not establish these gates.
