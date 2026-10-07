# Migration 101 — X OAuth provider ID

Claim: `101_x_oauth_provider.sql`, owned by `codex/social-connection-recovery-20261007` / PR #131.

After fetching the current origin refs on 2026-10-07, inspected migration paths across 361 local/remote refs and 102 registered worktrees. No `101_*.sql` claim existed. Recheck before release because concurrent work can advance.

Live read-only inspection confirmed production's `pr_oauth_transactions_provider_check` requires 2–40 characters. The canonical `x` provider fails at OAuth start with `CheckViolation` / HTTP 500. Migration 006 and its recorded checksum are preserved. This forward migration allows exactly `x` in addition to the existing range; it changes no stored grants, keys, policies or data. It has a five-second lock timeout.

The regression recreates the legacy constraint, reproduces the failure, applies this actual migration, and checks an X identity start, preserved existing transaction/forced RLS, hashed state, encrypted PKCE and rejection of other invalid IDs. Provider interactions are synthetic and no metered request is made.

Production DDL has not been approved or executed. The six historical ledger gaps must be reconciled separately; do not use this repair as authorization for blanket apply/adoption. Migration 100 and an explicit X budget remain separate prerequisites for paid identity lookup.
