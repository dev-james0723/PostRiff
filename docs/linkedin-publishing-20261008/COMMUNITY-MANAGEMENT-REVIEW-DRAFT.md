# Community Management review — operator draft, not submitted

Execution state: **DRAFT / NOT SUBMITTED**. This is separate from the existing self-service Share on LinkedIn product and the minimum member connection/publishing pilot. No review is presented as approved. The console observation on2026-10-08 shows Community Management under Available products / Request access, not Added. No approval date is promised.

## Verified facts and proposed description

App: **James Studio**, console app263833009. Existing Added products: **Sign In with LinkedIn using OpenID Connect / Standard Tier**, **Share on LinkedIn / Default Tier**. Product UI: **Rafii / PostRiff**. Product engineering is in the existing `dev-james0723/PostRiff` repository; protected preview uses the origin in PILOT-APPROVAL.md.

Proposed use-case description for the operator to review:

> Rafii lets a customer connect their own LinkedIn member profile through official consent, prepare an exact draft, review the account and content, approve publication or a scheduled time, and retain the provider receipt. Organization management, comment/reaction workflows and native analytics are separate opt-in capabilities. Access remains limited to the customer's selected account and authorized organization, actual granted permissions and workspace membership. No developer app, client secret or app-role enrollment is required from a routine customer.

Do not describe every feature as production-ready or say every scope below is already approved. Only request the reviewed use cases the operator actually intends to operate and can demonstrate.

## Scope justification candidate

| Requested workflow | Scope candidate | Data/effect and minimum boundary |
| --- | --- | --- |
| Identify a member | `openid profile` | Member subject/name for the authenticated connection. Already separate OIDC product; no Community Management prerequisite. |
| Personal approved posts | `w_member_social` | Create/edit/delete the consenting member's own approved posts. Existing Share product; no historical/feed or organization scope added for this workflow. |
| Discover/select eligible organizations and roles | `r_organization_admin` | Find organizations this member may administer and verify the specific destination role. A Page/organization administrator role belongs to the customer's destination; it is distinct from a developer role on our app. |
| Organization posts | `w_organization_social rw_organization_admin` | Create/manage only the selected organization after a fresh content authorization check. Recheck the exact granted scope set against the live provider product before consent. |
| Own member historical posts | `r_member_social` | Import/read this member's historical posts only with specific restricted access approval and separate user consent. Not needed to create or natively inspect the pilot's own returned ID. |
| Organization posts | `r_organization_social r_organization_admin` | Read posts belonging to the selected organization after role verification. |
| Member comments/reactions | `r_member_social_feed` | Read actual native comments/reactions only for the enabled workflow; no inferred zeros or unrelated inbox promises. |
| Member replies/reactions | `w_member_social_feed` | Publish only a specifically reviewed reply/reaction with an immutable target/content approval. This is distinct from `w_member_social`. |
| Organization comments/replies/reactions | `r_organization_social_feed` or `w_organization_social_feed`, plus role discovery | Read or act on a selected authorized organization's feed objects. Use the current provider's exact role/scope combination; never infer from member Share access. |
| Member post analytics | `r_member_postAnalytics` | Fetch provider-defined metrics for the enabled account/posts. Show unavailable metrics truthfully. |
| Organization follower/page/share metrics | `rw_organization_admin` (catalog baseline) | Fetch provider-defined organization metrics only for an eligible selected organization. Verify exact contract/access tier before submission. |
| Organization video analytics | `r_organization_social r_organization_admin` | Fetch eligible organization-owned video metrics; not organic document analytics. |

Native article/newsletter authoring and external Celebration creation remain unavailable in the baseline. URL article sharing is not native article authoring. Organic document analytics remain an unresolved official-contract audit; no advertising-metrics substitute is proposed. Every scope above still needs exact console permission access and its individual operation test; the table is a review draft, not access authority.

## Privacy, deletion and reviewer configuration

Source routes exist at `/privacy`, `/data-deletion`, `/terms` and `/security`. Proposed production URLs, **not newly verified or changed by this worker**, are:

- `https://postriff-phase2-private.vercel.app/privacy`
- `https://postriff-phase2-private.vercel.app/data-deletion`
- `https://postriff-phase2-private.vercel.app/terms`
- `https://postriff-phase2-private.vercel.app/security`

The current privacy source explicitly contains **legal entity/address/registration placeholders** and says hosting/error-tracking verification remains pending. Terms contain unresolved counsel items. Do not submit those placeholders as verified business facts. James/legal must supply the real legal entity, registration/address, matching business email/domain, LinkedIn Page ownership/app verification and approved contact/retention details through the normal secure operator handoff. Do not invent them or silently edit global legal content in this recovery branch.

Connection deletion path for the demonstration: customer opens Channels, selects the connected account and uses Disconnect; Rafii wipes the durable token and revokes with LinkedIn where supported. Account deletion and post deletion are distinct. Use a separately approved dedicated review workspace; do not expose customer tokens, sessions, private drafts or production admin credentials in a video or review form.

## Genuine demonstration storyboard — recording pending

1. Record the actual app/environment/source, signed-in ordinary Rafii reviewer workspace and feature readiness. Show no fixture/dev data as public proof.
2. Connect member via Account only; the owner performs login/MFA/consent. Show actual returned identity, account label and workspace. Reload and sign in fresh to demonstrate persistence.
3. Opt into **Publish** only. Show actual additional grant and unchanged blocked restricted operations. Prepare the separately authorized exact draft and destination; approve and submit once through normal UI.
4. Show real201/returned ID receipt, then native LinkedIn post/text/account inspection. API verification remains pending when restricted read permission is absent. Clean up only the created ID with separate exact approval.
5. After actual Community Management access and per-account consent exist, record each requested organization/feed/analytics use case on an eligible owner-controlled destination. Show destination selection, fresh role verification, exact operation approval and native/provider receipt. Do not record hypothetical enabled screens as completed integration.
6. Demonstrate denied/partial permission and reconnect behavior, two-workspace boundary rejection and disconnect. Record real iPhone Safari separately; desktop Chromium with a390px viewport is not an iPhone pass.
7. Provide only the genuine downloadable application-only screencast and secure dedicated reviewer access requested by the current provider form. Capture the provider's actual submission receipt after explicit submission approval.

## Consolidated review-only human handoff

Console: `https://www.linkedin.com/developers/apps/263833009/products` → Community Management → Request access. James/business owner supplies verified business/domain/Page facts and accepts applicable terms; engineering prepares final exact fields and genuine demonstration after access permits the use cases. Approval to submit is separate and pending. Evidence that unblocks work: actual product/tier approval, approved scopes, verified business/app identity, genuine review recording, and real provider submission/decision receipt. A request button, operator flag, sandbox recording or app-role success does not prove ordinary external-user access.

Primary sources checked2026-10-08: LinkedIn [access products](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access), [Community Management review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review?view=li-lms-2026-03), [permission migration](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-api-migration-guide?view=li-lms-2026-09), and the specific contracts in CAPABILITY-MAP.csv. Version2026-09 review-page fetch failed; the official indexed2026-03 body was available. A fetch failure never established unsupported status.
