# Facebook minimum connection preview — approval candidate

Status: PREPARED, NOT APPLIED. No provider registration, credential, review submission or production setting has changed.

Target existing Meta app **Rafii / 1401844428820097** and Vercel **postriff-phase2-private / prj_6ufJVDjTyWltj4SWT9sRKid4Kk5L**, Preview only, branch **codex/social-connection-recovery-20261007**. Preserve the existing app, existing customer grants, credentials and encryption key.

## Exact proposed operator changes

1. [Facebook Login for Business settings](https://developers.facebook.com/apps/1401844428820097/business-login/settings/): add this exact redirect, preserving current registrations:
   `https://postriff-phase2-private-git-c-752940-jamesau0723-6572s-projects.vercel.app/api/oauth/facebook/callback`
   Add only the exact preview hostname to App domains if Meta requires that match; preserve existing domains. Do not allow a wildcard or the shared vercel.app domain.
2. [Configurations](https://developers.facebook.com/apps/1401844428820097/business-login/configurations/): create one additional User access token configuration named **Rafii Preview Page Connection**, requesting **pages_show_list only**. Meta automatically includes public_profile. Do not reuse or edit existing broad Publishing config2961092884234131; it requests pages_show_list, pages_read_engagement, pages_manage_posts and pages_manage_engagement. Record the new config ID after creation.
3. [Vercel encrypted Environment Variables](https://vercel.com/jamesau0723-6572s-projects/postriff-phase2-private/settings/environment-variables): set only branch-scoped Preview variables:
   - POSTRIFF_OAUTH_FACEBOOK_CLIENT_ID =1401844428820097
   - POSTRIFF_OAUTH_FACEBOOK_CLIENT_SECRET =the existing matching Meta app secret, entered through a secure secret-store handoff; never chat, logs, screenshots or a repository file
   - POSTRIFF_FACEBOOK_LOGIN_CONFIG_ID =new minimal config ID
   - POSTRIFF_OAUTH_FACEBOOK_LOGIN_CONFIGS_JSON =mapping of pages_show_list to that same ID
   Preserve POSTRIFF_PUBLIC_BASE_URL and stable POSTRIFF_CREDENTIAL_KEY. Do not copy Rafii application-sign-in credentials without verifying app identity.
4. Redeploy the approved, checked recovery source to Preview, then verify callback/config identity and presence-only diagnostics. Do not set publicConnectionReady, productionReviewed, liveVerified, a global workflow switch or fabricated approval evidence.

Requested data/effect: official owner consent for basic profile identity plus the Pages the owner grants and their assigned tasks; explicit selection of one Page in Rafii. No publishing, comments, insights, messaging, ads, deletion, billing change or X requests. Additional billing authority: **$0**.

## Current evidence and genuine remaining gates

Meta console read-only observation2026-10-08: app Published; four currently added Page permissions display **Ready for testing / Add to App Review**. Published alone does not prove Advanced Access for ordinary customers. Current preview has no Facebook connector credential pair. Registered redirects include the production callback and a historical tunnel callback, but omit the fixed preview callback above.

Business portfolio3124765741050025 is in the app-console context; the legal owner name and verification outcome remain UNVERIFIED. Do not invent either. Existing privacy/terms/deletion URLs under postriff-phase2-private.vercel.app were verified reachable in the normal browser. All visibly remain Draft — pending qualified legal review; legal entity name/address/registration details remain placeholders. The deletion page honestly marks retention/backup targets unverified. Genuine operator legal/business facts and reviewable policy content remain needed; do not invent them.

For a genuine review demonstration, use an existing operator app-role account and owned eligible Page only after consent is authorized; record it as app-role evidence. Do not add ordinary customers as testers. The current public gate stays closed until genuine minimum-scope external-access evidence exists. A narrowly bound app-role preview test policy, if needed, requires its own reviewed candidate and cannot assert public readiness.

After Meta approves pages_show_list for external users, record the actual approval receipt, exact app/config/callback and scope in the server-owned connection review store. Only then start the ordinary-user test through Rafii Channels → Facebook → Account only → Meta consent → choose Page. Test two isolated Rafii workspaces, reload/fresh session, owner-approved disconnect/reconnect and real iPhone Safari. No manual per-customer E2E insertion is required to begin an eligible connection.

## Review draft — prepared, not submitted

Scope justification: Rafii uses pages_show_list to list the Facebook Pages a consenting user grants, show each Page's name and assigned tasks, and let the user explicitly select the Page for their workspace. Basic connection does not create, edit or delete content. Additional features request separate permissions only when enabled.

Reviewer sequence: sign in to the designated Rafii review workspace; Channels → Facebook → Account only; complete Meta consent for the intended account and Pages; return to the same workspace; select an authorized Page; verify connected Page name, retained basic grant and publishing unavailable; reload; disconnect/reconnect with owner approval. Genuine recording, reviewer access details, legal/business facts and policy URLs must be supplied and verified before a submission approval request.

Publishing, media, scheduling, comments/replies/moderation, analytics and Messenger remain independent rows in the original205-capability scope. No review-submission receipt or ordinary-user Facebook success exists.

## Rollback

Remove only newly added branch-scoped Facebook Preview variables and redeploy the preceding checked preview source. Preserve existing broad config and all existing redirects/grants; removal of a new provider registration requires a separately confirmed operator change. Rollback must leave LinkedIn basic connections and their encrypted tokens intact. Production is excluded.

Primary contract verification2026-10-08: [Meta permissions](https://developers.facebook.com/documentation/development/permissions#pages_show_list) lists pages_show_list with no dependency and public_profile automatic; external data access requires applicable review/Advanced Access. [User Accounts](https://developers.facebook.com/docs/graph-api/reference/user/accounts/) identifies assigned Pages/tasks. [debug_token](https://developers.facebook.com/docs/graph-api/reference/v26.0/debug_token) provides app/user/validity/expiry metadata. These sources were read in the native browser when the document-fetch tool failed. Fetch failure was not treated as lack of support.
