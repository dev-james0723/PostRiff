# US$0 Pinterest staging database candidate

2026-10-14 UTC. **Proposal only; NOT CREATED.** The user asked to avoid the US$10/month Micro cost. The previously approved paid creation is on hold. Provider list-projects confirms no `rafii-pinterest-isolated-staging` was created. Prepared paid-project tabs were closed; no project deletion, transfer, plan change or charge occurred.

## Recommended exact target

- New Supabase organization: **`Rafii Pinterest Staging`**, type **Startup**, plan **Free — US$0/month**, under the same signed-in Supabase account currently accessing `gztpsyvraqdcoklwpvdo`.
- One fresh project: **`rafii-pinterest-isolated-staging`**, region **`us-east-1`**, Free/Nano compute; its generated organization ID and project ref must be recorded after creation.
- One empty database and separate project Auth issuer/keys; no existing users, sessions, credentials, workspace data, jobs or storage copied.
- **US$0 additional Supabase budget.** Stop on any card/paid-plan/add-on requirement, Free quota denial or nonzero quote. No automatic upgrade. No existing organization billing or membership changes, and no new account or trial used to evade account limits.

## Verified feasibility and limitations

The authenticated dashboard's new-organization page `https://supabase.com/dashboard/new` shows **Free - $0/month** (2026-10-14). The Rafii connector currently lists one organization, the existing Pro organization; this is not final proof that Free project capacity is available to the browser account. Free eligibility must still be confirmed by the provider before creating the project.

Supabase billing applies per organization: Free and Pro cannot coexist in one organization. Free allows two active projects across organizations where the account is an Owner/Administrator; paused projects do not count. The new organization does not bypass that quota. Free includes 500 MB database, 1 GB object storage and 5 GB egress; inactivity can pause a project after one week. These limits support consideration for this small Trial pilot, but actual runtime/size/refresh/scheduling acceptance is NOT RUN. This is not a production-capacity claim.

Official documentation checked 2026-10-14: [Billing and organization rules](https://supabase.com/docs/guides/platform/billing-on-supabase), [Free limits](https://supabase.com/pricing). For database connectivity, the existing adapter can accept Supabase's shared TLS pooler pattern; [the shared pooler is available on every plan](https://supabase.com/docs/guides/database/connecting-to-postgres). Do not buy an IPv4 add-on merely to connect; use the provider-issued endpoint and verify TLS/project binding. No endpoint, successful connection or user isolation is yet claimed.

## Requested scope and follow-up

Approve creating only this Free organization and one empty Free project, subject to confirmed available quota and US$0 quote. Database-password entry/confirmation/submission remains a human browser step unless an already-authorized authenticated purpose-built API/CLI becomes available. Do not send passwords in chat.

After creation, read back exact org/ref/region/plan/health and prove empty user/session/job/credential state. Then present the checksum-pinned schema/bootstrap and new-ref Auth/deployment configuration for their separately scoped approval. The 81-file schema inventory already exists; it has not been applied and a clean bootstrap rehearsal is not claimed. The local fresh vault key is private, ignored and not installed.

Existing production `buoyhkbodnhzngaotoel`, consumer staging `oxacvkhpfgytkepxcaqh` and their accounts remain unchanged. Schema, Auth settings, deployment, public callback protection, Pinterest callback registration, live consent, Pins, Standard and production are outside this Free provisioning proposal. Vercel metered deployment cost is separate; this proposal avoids the database's US$10/month, not a guarantee that every staging resource is free.

## Superseded by user target correction

User explicitly requires the existing production Supabase project and forbids another organization. This new-organization/project proposal is CANCELED. No new organization or database was created.
