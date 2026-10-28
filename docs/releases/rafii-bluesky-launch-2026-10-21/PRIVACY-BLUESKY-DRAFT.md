# Draft privacy text for Bluesky (E1). Not legal advice; needs the approver James names.

Proposed paragraph for `/privacy`, section on connected accounts:

> **Bluesky.** When you connect a Bluesky account, you sign in on your own Bluesky server, not on Rafii. Rafii receives and stores your account identifier (DID), your handle, and an access and refresh grant with its cryptographic proof key, encrypted with a key held only on our servers. With an identity-only connection Rafii can confirm which account you own and nothing else. If you grant publishing, Rafii can create posts and upload images to your account, and only after you approve each exact post. Rafii does not read your direct messages, likes, follows or followers. When you disconnect, Rafii asks your Bluesky server to revoke the grant and marks the stored grant revoked so it is never used again. Deleting your workspace deletes these records. Bluesky's own terms and privacy policy apply to your account.

Facts behind it (code on `01cf90a3`):
- Stored: `provider_account_id` (DID), handle in workspace state, `access_ciphertext` and `refresh_ciphertext` (DPoP key inside), scopes, expiry (`pr_encrypted_credentials`).
- Encryption: Fernet with `POSTRIFF_CREDENTIAL_KEY` (application layer).
- Disconnect: `OAuthService.disconnect` calls the Bluesky revocation endpoint and records `remoteRevoked`.
- Workspace deletion: `pr_encrypted_credentials`, `pr_channel_capabilities` and `pr_connection_health` reference `pr_workspaces(id) ON DELETE CASCADE` (migrations 006 and 060).

For `/terms`: "Rafii publishes to Bluesky only content a person approved for that exact account. Rafii does not automate follows, likes, replies or other interactions." Bluesky's developer guidelines prohibit automated or bulk interactions and follower-growth automation ([developer guidelines](https://docs.bsky.app/docs/support/developer-guidelines), summarized from a search result; the page itself served a redirect stub when fetched).
