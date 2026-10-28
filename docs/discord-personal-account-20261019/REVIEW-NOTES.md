# Discord personal-account extension — review notes

Reviewed 19 October 2026 against parent `63864bd6654f62a165c398ce4c493528aee6f501`.

## Review performed

This is an implementation-side whole-diff review, not an independent reviewer sign-off. The local diff, newly added presenter/helper, server projection, callback and request lifecycle were inspected. Release still requires independent review and exact-source hosted/browser qualification.

## Findings and resolutions

1. **Identity metadata could be misunderstood as publication authority.** A fixed server-produced non-publishing contract now overrides any stored authority-shaped fields. Neither identity projection nor identity save adds publishing channels, destination approvals or jobs. New backend tests exercise actual projection/save methods with synthetic custody.
2. **Loose identity projection accepted malformed/unbound records.** Projection now requires a dictionary with both the current workspace ID and authorizing actor. Missing authentication fails before the repository is used. Credential/private fields remain outside the allowlist.
3. **Identity success had no main-page publishing card to target.** Personal accounts now have their own semantic main-page section and stable article IDs; callback highlighting distinguishes an identity from an actual publishing channel.
4. **Missing discovery consent led to a failing server-list attempt.** A presentation helper separates choose/reconnect/scope-upgrade/ready states. The upgrade control only prepares an official OAuth request; it cannot grant a scope. Server-side live validation remains authoritative.
5. **Changed/reopened connection context could consume a stale response.** Request generations fence OAuth-start and server-list completion. Relevant selections are disabled while busy. Platform changes and identity reconnect preparation clear old identity/destination state. The server-list result must name the selected identity.
6. **Reconnect could leave old channel selection visible.** Reconnect preparation clears the guild ID/list and explicitly warns that dependent server/channel authorization must be renewed. An additional RED-to-GREEN wiring regression covers the change.
7. **Shared callback text could suggest an Assisted Discord capability.** Discord now says publishing is unavailable until separate authorization; other providers retain their existing wording. The changed shared ConnectSheet still requires other-provider regression coverage; this is not claimed to be a Discord-only component at runtime.
8. **Initial local dependency source was stale/incomplete.** Main-worktree dependencies were not edited. Only the new worktree's symlink was removed, then its own dependencies were restored from the existing unchanged lockfile with lifecycle scripts disabled. The restored TypeScript check passed; the initial failure receipt is retained.

## Boundaries confirmed in the inspected diff

No database migration, provider credentials, vault keys, publishing-worker implementation, shared scheduler, Production setting, package manifest/lockfile, GitHub workflow, or Vercel deployment policy was changed. Existing Bot installation and frozen message approval remain distinct from personal account connection. No Discord message or publication job was created by this extension.

## Qualification still required

Actual client-browser interaction/accessibility and multi-viewport layout are not proven by the component SSR tests. Two request-lifecycle tests check source wiring, not a running browser. OAuth callback/readback, fresh eligible customer onboarding, per-message approved provider send/readback, actual unattended scheduling, cancellation/revocation under a running worker, exact-deployment provenance and release approval remain separate gates. The additional webhook and user-installed-app runtimes specified in the PRD are not implemented by this patch. Complete localization is not claimed.
