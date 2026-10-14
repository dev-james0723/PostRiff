# Existing production Pinterest change candidate

2026-10-14 UTC. **Prepared only; NO-GO for release.** No new organization/database. Canonical Supabase: `postriff-phase2-private` / `buoyhkbodnhzngaotoel`; Vercel project `prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L`; origin `https://rafii.io`.

Candidate source `f54028edc1eb5bd8e78d089899c694505cd15c0e` includes the live production baseline `7da3375cc0409d8e3a434955a75f57478889372b`, preserving account-protection/browser-session guards. [Source diff](evidence/production-engineering-candidate.patch), [fingerprints](evidence/production-source-hashes.json), [scoped cloud validation](evidence/production-baseline-validation.json). Recheck the live SHA before release; other sessions can deploy meanwhile.

## Additive DB delta

Existing OAuth vault/transaction and tenant schemas are reused. Do not apply the 81-file clean-bootstrap inventory to this existing database. The one new Pinterest quota candidate is `migrations/postriff/20261014_pinterest_rate_budgets.sql`, SHA256 `e8bbf902dc5e46010aae34d4bd8653b37601b8df0b3b585ba5ffa89b3abe07ee`. Current production metadata confirms the table absent. Its fields contain hashed app/account keys and rate counters, no tokens/content. RLS enabled; PUBLIC/anon/authenticated have no privileges, service_role gets bounded internal access. Fresh disposable PG tests confirm quota concurrency/recovery and client read denial.

Before applying: rerun absence/schema/privilege preflight, preserve a migration receipt, apply only the reviewed additive file transactionally through the approved runner. Stop on drift. Actual production apply, PostgreSQL17 runtime and canary are NOT RUN. Quota maintenance/deletion is separately approved. Rollback: pause Pinterest gates and jobs first; reviewed DROP of quota table makes publishing fail closed. Do not delete posts, receipts or credentials for rollback.

## Exact configuration direction

Use the existing production Auth/database project and existing production vault key; never install the locally generated staging key or rotate the shared vault key. Existing production secret values were not read. Actual DSN/Auth-key binding still needs secure release preflight, not inference from env names.

App ID `1615884`; client ID/secret absent from Production env metadata. Callback-origin variable present, its value/registered-URI agreement unverified. Approved final production origin is `https://rafii.io`; proposed official callback `https://rafii.io/api/oauth/pinterest/callback` must be checked against the provider before any change. Install existing App secret privately, never reset it or write it to evidence. Credential install is part of a concrete separately reviewed production operation after release prerequisites qualify.

Keep public ENABLED/VERIFIED/REVIEWED/POLICY_APPROVED flags and Agent provider-data gates closed until their own evidence qualifies. Provider console currently says Trial access active. Sandbox/Trial credentials and results must not be described as public Standard publication. No public customer connections before Standard Access.

## Remaining critical path

Obtain the intended Rafii workspace and Pinterest account from the human, then prepare a narrowly scoped real OAuth/Trial pilot on existing approved infrastructure. The previous dedicated-new-DB Step A design is superseded; it is not a grant for a shared-production test or customer publishing. Define tenant/job/credential/session containment and the exact callback/deployment/config effects before requesting that pilot approval. Reuse existing projects and do not provision an organization/database.

Human consent and a frozen specific Pin approval remain separate. Capture real identity/boards/refresh/reconnect/disconnect and read-back, scheduling, failure recovery and actual tenant isolation. Prepare the real demo video and Standard package, obtain submission approval and record official provider approval. Only then finalize the exact production release/canary operation. Current source integration/scoped CI passing does not establish these gates.
