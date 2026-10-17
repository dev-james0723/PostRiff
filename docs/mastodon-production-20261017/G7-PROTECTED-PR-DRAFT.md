# G7 — Proposed protected Pull Request (LOCAL DRAFT, NOT CREATED)
Date: 2026-10-17 · Repository: dev-james0723/PostRiff · Target: consumer-saas

**Proposed title:** Mastodon Public Connect: federated OAuth, tenant-safe account identity and fail-closed publishing

**Proposed source:** local/rafii-mastodon-g7-release-prep-20261017
**Pinned engineering parent:** 2d5ae6527881341399818af381c4269b9675c7d7
**Production main last verified:** 7432c56d96bc9d042b6f00bdbb6acc1b5bb271f1
**Status:** PREPARED OFFLINE. NOT PUSHED. NO GITHUB PR WAS OPENED.

## Merge blockers and PR scope

- Existing Mastodon PR #176 remains OPEN/DRAFT, head 53c8ab899b66e14d7d568146b58e6f85c11c6251, with mergeable=false. Do not merge it as-is or claim its CI is for the new integrated candidate.
- Main branch currently has **no branch protection and no repository rulesets** according to GitHub API. This is not a "protected PR" until an admin separately enables enforcement.
- Current integrated candidate vs main: **146 paths, 11,046 added lines, 160 deleted lines**; 59 files not Mastodon-named, and 22 of those have no explicit "Mastodon" in added lines. That is a REVIEW SCOPE flag, not proof those changes are irrelevant. See G7-CROSS-CUTTING-DIFF-SCOPE-20261017.json.
- Keep three committed source-identical historical SQL files 103/116/117 consistent with the Production checksum ledger. They are already applied; never reapply them. Confirm any proposed "slim PR" still matches all 62/62 Production hashes.
- Do not include 18 archived screenshot binaries in the eventual minimal PR; they are maintained in the G5 evidence archive. The Depot-only transport tree proves runtime/tests/SQL are byte-identical while omitting those 18 files.
- Before a Production merge, split independently reviewable changes into **Connect/Identity & Schema** and **Extended Publish/Management/Analytics** where dependencies allow; rerun cross-platform regression against the exact reduced commit. The current full RC is NOT certified as a safe minimal Connect-only diff.

## Suggested PR Body (after scope reduction & explicit push/PR approval)

**Purpose:** Allow actual Rafii customers to connect account identities to their own Mastodon instances via account-scoped dynamic app registration, one-time OAuth PKCE/state, encrypted token custody, per-workspace isolation, identity readback, disconnect and revocation. Support multiple independent Mastodon servers. Leave publish, schedule, edit, delete and management writes fail-closed until separate live acceptance.

**Safety invariants:**
- No automatic posts, permissions escalation, account login delegated to agents, scope widening, blank/placeholder app secrets or unsafe DNS/redirect targets.
- New app registration cache and action journal service-role only, FORCE RLS, no public/anon/authenticated table grants. User still controls each OAuth authorization.
- Exact account-instance binding; irreversible effects require an account-specific human approval and provider ID readback. No retry after uncertain outcome.
- No cross-workspace content access; verify Supabase membership policies and negative tests.

**Evidence available:** Original production Build 114/114 pages PASS; G1 unit 136/136 PASS; G5 genuine Linux Chromium+WebKit Account/Queue for 1440/390/320px PASS; Linux synthetic PostgreSQL 1,000-user admission + 32 SQL workers PASS. All synthetic, zero real Mastodon calls. Depot runs j3m49xrsq9 and xtsp84fx9b. Not a real-customer performance or OAuth acceptance claim.

**BLOCKED until:** Fresh backup and independent Restore; source/migration 62/62 parity; codeowner review and enforced branch protection; explicit Production schema approval for 131-133 (or a newly reviewed connect-only subset), Postgres17/lock acceptance; secure isolated staging build and DB binding; real user-controlled OAuth on two independent instance operators; negative grant and cross-tenant readback; exact deployment/provenance and rollback; final invited/public rollout approval.

## Branch protection required BEFORE PR publication/merge

1. Admin configures a branch Ruleset for consumer-saas, enforced for administrators, requiring PR, no force push/delete, up-to-date branch, required status checks and at least one independent review + codeowner approval. James remains the final Release Captain.
2. Require only *existing and verified* check names after publishing reviewed workflows; avoid treating Vercel deployment status or skipped checks as the Mastodon release gate. No paid rerun/extra build without approval.
3. Ensure GitHub/Vercel automatic checks on PR push are budgeted and do not accidentally Production deploy. Keep hard-stop budget in place.
4. PR itself must be approved by user separately. DO NOT use gh pr create, push, merge or GitHub API mutations as part of G7.

## Decision
This is a local offline protected-PR specification, **not** a genuinely protected GitHub PR. Public Connect NO-GO.
