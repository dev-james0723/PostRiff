# Owner steps — acceptance not executed

The owner has identified and authorized the existing accounts **@jamesaucreates@mastodon.social** and **@jamesau0723@mastodon.social** for the temporary acceptance workflow. Both signed-in identities were observed in Chrome. OAuth identity and granted scopes still require verification through Rafii. No password, authorization code, access token or client secret is requested through chat.

1. Identify the existing paid Supabase organization by its dashboard URL or ID and make it accessible to the existing connection if needed. The owner approved up to USD 1 total for 24 hours of dedicated staging and chose an existing paid organization. All three connected organizations and the Vercel-managed installation currently report Free; none will be upgraded. The shared Rafii staging database is active for another release.
2. After isolated staging is provisioned and its redirect, database, storage and credential pins are verified, Rafii will register the application and create one-time state with S256 PKCE under the authenticated owner. The two exact OAuth URLs will then be presented for the two known mastodon.social accounts. They have not been created yet. A sign-in URL is not an OAuth authorization URL.
3. Approve each exact OAuth URL in the browser using the corresponding account. Rafii will verify returned identity and effective scopes before any test publication. Do not paste callback codes or secrets into chat. The scoped temporary media, edits, schedules, approved automation, deletion, disconnect and revocation actions are already authorized; they do not need another account-information request.
4. Supply a maximum attributable USD budget for the real Brand Brain model call, if no existing Mastodon-specific budget is established. Infrastructure permission does not authorize model spend. No purchase, top-up or recurring plan change is authorized.

## Cross-instance gate

Both supplied accounts are on mastodon.social. Read-only searches of the two connected mailboxes (sender/subject and full-message Mastodon/mstdn searches, including Spam/Trash) returned no account evidence. This limited search does not prove that another account does not exist. No owner-authorized account on an independent instance has been discovered. **Only cross-instance acceptance is BLOCKED_NO_VERIFIED_SECOND_INSTANCE_ACCOUNT**; all applicable same-instance two-account tests and independent engineering work should proceed when their own prerequisites are ready.

If an existing independent-server account becomes available, authorize it through Rafii. The optional signup page for mstdn.social is https://mstdn.social/auth/sign_up; email verification, moderator approval, CAPTCHA and terms acceptance remain owner-only steps. New signup is not required to run the two known accounts' tests. Production release still requires the mandatory real independent-instance test.

Public operator evidence: https://mastodon.social/about identifies Mastodon GmbH; https://mstdn.social/about identifies stux as owner and administrator and Stuxhost as its funding recipient. The deployments have separate origins and different running versions. This verifies independent operation, not separate cloud vendors. Real identity and scope verification remains NOT_RUN.

Staging creation is pending an accessible paid organization and a verified account-specific price within the approved cap. The connector cost tool is unavailable. Exact OAuth URLs cannot safely be created before that real staged environment is ready.
