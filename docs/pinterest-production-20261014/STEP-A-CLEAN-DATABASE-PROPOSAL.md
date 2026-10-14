# Step A addendum — clean database proposal

2026-10-14 UTC. **Proposed only; no new database provisioned.** Step A was approved for source `a54fadf519a69e125ebd1d0d4c3139f2946ee183`. The original proposal requires stopping before deployment when `oxacvkhpfgytkepxcaqh` fails qualification. It failed: shared workspaces, sessions, credentials and recurring tasks remain in that consumer staging project. No existing data will be removed to make it qualify.

## Exact proposed new target

- Supabase project name: **`rafii-pinterest-isolated-staging`**.
- Existing organization: **`dfestival.office@gmail.com's Org`**, ID **`gztpsyvraqdcoklwpvdo`**, currently Pro, via the Rafii database connection.
- Region: **`us-east-1`**. Compute: **Micro**. Generated project ref is unknown until creation; it must be captured and explicitly pinned before app configuration.
- Create one empty project with its own Auth issuer, database and project keys. Generate a fresh staging vault key. Copy no users, sessions, tokens, workspace state, credentials, jobs or storage objects from any existing project. Reconcile the other active continuation's ownership before any shared remote mutation.
- Keep canonical production `buoyhkbodnhzngaotoel` and existing consumer staging `oxacvkhpfgytkepxcaqh` unchanged. No organization-wide settings changes.

## Cost and authorization

Official Micro pricing is **US$0.01344/hour (approximately US$10/month)**, before applicable taxes. This is a public rate, not an authenticated organization-specific quote. Existing organization compute credits may already be consumed; do not assume the new project is free. Paid plans share usage quotas; excess disk/egress/Auth usage can cost extra. Sources checked 2026-10-14: [Compute and Disk](https://supabase.com/docs/guides/platform/compute-and-disk), [Pricing](https://supabase.com/pricing).

The connected `get_cost` tool is unavailable (`get_cost was not returned by tools/list`). **Confirm the actual Micro price, existing quota headroom and applicable cost controls in the provider before provisioning.** Stop if the offered base price exceeds US$10/month before tax, or if required usage/add-ons create an additional charge. No plan upgrade, compute upgrade, paid add-on or overage is requested. Do not change an organization-wide spend cap affecting other projects.

**Requested next authorization:** provision this one empty Micro project in this exact organization, subject to that price check. This addendum does not approve schema application, auth-setting changes or deployment against its new ref: prepare the checksum-pinned schema/bootstrap and new-ref configuration for review first. The new public Pinterest quota migration remains excluded from the read-only pilot.

## Other Step A blockers

The existing Vercel project `rafii-pinterest-trial-staging` (`prj_7AB6iulp2Vk0wPqeT1CRAi9XwBUl`) has no deployment or environment variables. Its team reports Pro billing **overdue**; deployment spend qualification is incomplete. No payment or billing-setting change is authorized. The alias is unassigned in this team (404); global availability is unverified. Default SSO protection is enabled for `all_except_custom_domains`; public callback access remains untested. Do not change protection without the separately scoped approval required by the original proposal.

Callback registration, live OAuth consent, real Pins, Standard submission, public enablement, Git push/merge and production remain separate gates. [Read-only preflight evidence](evidence/step-a-preflight.json).
