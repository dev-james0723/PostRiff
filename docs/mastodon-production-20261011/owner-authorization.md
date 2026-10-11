# Owner steps — acceptance not executed

No account, authorization code, access token, password or client secret has been supplied or requested through chat. The inspected Chrome window shows both instances signed out. Existing accounts can be used instead of creating new ones.

1. Account A: sign in at https://mastodon.social/auth/sign_in or create an account at https://mastodon.social/auth/sign_up. Its public API currently advertises open registration without moderator approval.
2. Account B: sign in at https://mstdn.social/auth/sign_in or request an account at https://mstdn.social/auth/sign_up. Its public API advertises moderator approval and a signup reason. A truthful reason can explain that you are testing your own social-publishing application using clearly labelled temporary posts and cleanup. The owner must complete email verification, any CAPTCHA and terms acceptance.
3. Supply only the two full public handles and confirm the scoped actions in staging-action-preview.json: media publication, owned-post editing/deletion, native and managed scheduling, manual approval/automation, and disconnect/reconnect/revocation. Confirm the pending isolated database budget and a separate maximum for the real Brand Brain model call. No purchase or top-up is authorized.
4. After the isolated application is deployed and redirect configuration is verified, Rafii will register each instance application, persist encrypted client credentials and create one-time state with S256 PKCE under the authenticated owner. The two exact OAuth authorization URLs will then be presented. They have not been created yet. Signup/sign-in URLs above are not OAuth authorization URLs.
5. The owner signs in and approves those exact URLs in their browser. The callback returns only to the protected staging application. Do not paste callback codes, tokens or secrets into chat.

Public operator evidence: https://mastodon.social/about identifies Mastodon GmbH; https://mstdn.social/about identifies stux as owner and administrator and Stuxhost as its funding recipient. The deployments have separate origins and different running versions. This verifies independent operation, not separate cloud vendors. Real identity and scope verification remains NOT_RUN.

Staging creation remains pending owner approval of a dedicated Supabase branch for up to 24 hours and USD 1, subject to verifying the account-specific quote. The connector cost tool is unavailable. The existing shared staging database is active for another release and cannot serve as this mission's isolated upgrade/restoration environment.
