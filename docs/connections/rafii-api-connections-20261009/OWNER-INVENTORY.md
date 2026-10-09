# Owner inventory — Rafii API connections (2026-10-09)

Read-only inventory taken at session start. The base is `26d7e901` (= `origin/consumer-saas` after fetch). These are observations, not deploy proof.

## Lanes and paths

| Lane | Anchor | Head | Owned paths (do not edit from this lane) | Who can approve |
|---|---|---|---|---|
| YouTube authority, capacity, AI privacy | PR #149 `codex/rafii-youtube-gates-20261009`; worktree `~/.codex/worktrees/rafii-youtube-public-20261008` | `55a18b7b` | `src/postriff_phase2/{oauth,store,privacy}.py`, `youtube/*`, `site_agent/reads.py`, migration 105, `web/src/features/youtube/*`, `web/src/lib/{api/client,youtube/types}.ts` | YouTube owner, then James |
| YouTube consent and policy fence | PR #138 `codex/rafii-youtube-revocation-fence-20261008` (draft) | `74cb0452` | `oauth.py`, `hosted*.py`, `hosted_worker.py`, `store.py`, `agent_runtime_v2/*`, `youtube/*`, migrations 098–100 and 106, `web/src/features/channels/connect-sheet.tsx` | YouTube owner, then James |
| Social connection recovery / LinkedIn member publishing | PR #131 `codex/social-connection-recovery-20261007` (draft); LinkedIn worktree `.worktrees/linkedin-publishing-20261008` | `a780b5e3` | `oauth.py`, `channels.py`, `providers.py`, `provider_base.py`, `hosted_*`, `official_*`, `outcomes.py`, `social_*`, `wave3_connectors.py`, migrations 100–101, `web/src/features/{channels,queue,library}/*`, `web/src/lib/channels/*` | Recovery owner. The expired LinkedIn pilot job and its rejected cancellation stay with that owner. |
| Founder support | PR #101 | `c6c065c5` | `rafii_control/{founder_support,founder_tools,founder_metrics_support}.py`, `slices.py` (one shared line) | Founder owner |
| Notifications, Founder plan, Growth, Trends, Meta trends, Library | PRs #104, #121, #142, #140, #139, #143, #144 | — | not touched | their owners |
| Main checkout | `/Users/ouxianxing/Documents/James-Au-Studio` | — | uncommitted social-connection work belonging to another owner | never edited |

## This lane

- Branch `worktree-rafii-api-connections-20261009` in `.claude/worktrees/rafii-api-connections-20261009`.
- New: `src/rafii_control/founder_connections.py`, `tests/control/test_founder_connections.py`, `web/src/features/founder/settings/connections-attention-panel.tsx`, and `docs/connections/rafii-api-connections-20261009/*`.
- Edited: `src/rafii_control/founder_metrics_ops.py` (connection projection uses the YouTube vault facts), `src/rafii_control/slices.py` (+1 line), `web/src/features/founder/settings/settings-view.tsx` (+2 lines), `tests/control/test_founder_ops.py` (+1 test).
- No migration number is used. No configuration, flag, provider or credential change.

## Pending dependencies and decisions

1. Launch scope: recorded by James on 2026-10-09 as YouTube read-only (connection health, channel identity, refresh capability, analytics within granted scopes; publishing, content changes and scope changes excluded). It lives in `founder_connections.LAUNCH_SCOPE`. Update 2026-10-09 ~20:00Z: #149 merged to `consumer-saas` (`220d2de1`, production `dpl_3mcXs7Xwtc8gKsjjYJNpjrNkJF7U`), and this branch merged it cleanly with no shared-file overlap.
2. Provider decision receipts. `RECORDED_DECISIONS` is empty, so every approval requirement reads "check required". Each receipt (status, decision time, provider receipt reference, approved scopes, verifier, last check) gets added by a reviewed PR. Owner: each provider app owner.
3. Launcher session id mismatch. The receipt id `78aab31f…` differs from the observed job id `497b094e…`. Owner: launcher or Codex coordinator.
4. Library WebKit 1440 `/preview` intermittent CI failure: owned by the Library lane (#144). See LIBRARY-CI-DIAGNOSIS.md.
5. Release: James's latest instruction is NO merge or deploy. PR #150 stays a draft.
