# Rafii / PostRiff release consolidation audit - 2026-09-28

Canonical branch audited: consumer-saas
Canonical head before consolidation: 22e42b40d3aad82a7cf7902ab20d4d0fac7b3f95
Clean candidate: release/rafii-consolidation-20260928 at 46e6d920e51bb7401549d8860e4631ec2a6935b6 when this audit was written.
Inventory source: 192 local/remote refs and 74 worktrees; every row has exactly one A-E category.

## Category counts

| Category | Refs | Worktrees |
|---|---:|---:|
| A | 150 | 27 |
| B | 13 | 4 |
| C | 7 | 1 |
| D | 5 | 36 |
| E | 17 | 6 |

## Relevant non-absorbed refs

| Category | Ref | HEAD | Reason |
|---|---|---|---|
| D | ai-routing | d2f23f7be82c | stale/incomplete AI-routing work; migration-numbering docs reserve 026-029 for later reconciliation |
| E | backup-before-filter-repo-202609160658 | 112c5d49a169 | historical pre-filter backup containing obsolete large artifacts; never a release candidate |
| E | backup-before-filter-repo-consumer-saas-202609160658 | 13d913dd00c6 | historical consumer-saas backup snapshot superseded by later canonical development |
| E | codex/consumer-ready-release | b4078713b32a | older staging/support branch superseded by later canonical consumer release and release tooling |
| B | codex/postdoctor-evidence-v2-20260927 | a9a4e64cbb25 | committed Post Doctor v2 feature commits reconstructed on current Growth base; dirty pilot continuation excluded |
| B | codex/rafii-call-status-ui | a67d951edcb7 | committed call-readiness UI patch integrated; unrelated dirty docs preserved |
| B | codex/rafii-composer-delivery-planner-20260928 | fa56a0074b69 | previous production-only delivery-planner release restored to canonical candidate |
| B | codex/rafii-growth-loop | acf2393e58d6 | verified P0 Growth Loop production release restored to canonical candidate |
| B | codex/rafii-inbound-budget-rate-fix | 9b67eb09b007 | caller-identity successor budget/cooldown fix integrated |
| D | codex/rafii-passkey-identity | 9b67eb09b007 | dirty successor worktree with uncommitted auth changes and untracked 046_phone_passkey_identity.sql; preserved |
| C | codex/rafii-phone-caller-identity | 2a8224e6aee1 | production-migrated caller identity code integrated behind existing phone/inbound/verification gates; physical-device Face ID/Touch ID acceptance remains external |
| B | codex/rafii-release-reconcile-20260926 | 1030397f79b2 | guide focus-scope repair integrated to fix modal browser-scene timeout |
| E | codex/rafii-social-wave4-a | 13dd11228111 | stack dependency fully included by Wave 4B successor |
| C | codex/rafii-social-wave4-b | 1c8e7b3b81ab | Wave 4 A/B/C stack integrated fail-closed; live provider approvals/OAuth/publishing/analytics/comments remain off |
| E | codex/rafii-social-wave4-c | 1722eb667c9e | Wave 4C was merged into the Wave 4B stack; successor integrated |
| E | codex/rafii-v3-phase1-20260927 | 8cf23512b809 | superseded by the validated Stage 3 chain; effective Phase 1 work included there |
| E | codex/rafii-v3-phase2-20260927 | 38a3a061a039 | superseded by the validated Stage 3 chain; effective Phase 2 work included there |
| C | codex/rafii-v3-stage3-20260927 | 7cd7622e2736 | V3 through Radar Stage 3 integrated; Radar/provider sources remain default-off pending authorized activation |
| D | codex/rafii-v3-stage4-20260928 | b18a37c1f6de | receipt explicitly STARTED_NOT_COMPLETE; also claims conflicting 044_youtube_coach.sql |
| B | codex/sign-in-again-link | cbeaad953e77 | step-up sign-in-again flow integrated |
| E | codex/social-trend-intelligence | b3395efc1f8f | older Social Trends branch superseded by later canonical Trends releases/PRs; dirty continuation preserved separately |
| D | codex/trend-ledger-closeout | 58abf08e13fc | closeout receipt still has M1/M2 open and production_verified=false; preserved |
| E | feat/cc-w1-be1 | 7eaf2cdfec63 | chat-context planning branch superseded by later shipped chat-context/media work; unique remainder is design docs only |
| E | feat/cc-w1-be2 | 7eaf2cdfec63 | same chat-context design-doc commit as the superseded cc-w1 planning branch |
| E | feat/cc-w1-be3 | 7eaf2cdfec63 | same chat-context design-doc commit as the superseded cc-w1 planning branch |
| E | feat/cc-w1-web1 | 7eaf2cdfec63 | same chat-context design-doc commit as the superseded cc-w1 planning branch |
| E | feat/cc-w1-web2 | 7eaf2cdfec63 | same chat-context design-doc commit as the superseded cc-w1 planning branch |
| E | feat/chat-attachments | 7eaf2cdfec63 | same chat-context design-doc commit as the superseded cc-w1 planning branch |
| E | fix/rafii-twilio-verify | c745db9ad4c5 | Twilio-era phone release superseded by the later Dial/phone release path |
| D | rafii/ai-routing-renumber-026-029 | 0a69f7874040 | prepared renumbering branch with open work; not release-complete |
| B | rafii/automation-credit-rebind | 44bdcb7ef3a8 | same automation credit rebind patch represented by the integrated PR 11 repair |
| B | release/rafii-consolidation-20260928 | 22e42b40d3aa | clean consolidation candidate created from current canonical |
| B | origin/claude/automation-credit-rebind | 44bdcb7ef3a8 | automation credit repository rebind integrated and re-tested |
| C | origin/codex/fix-webauthn-mfa-enrollment | 868e92a4856c | client fallback integrated; physical WebAuthn enrollment still depends on production Supabase/device support |
| B | origin/codex/rafii-composer-delivery-planner-20260928 | fa56a0074b69 | previous production-only delivery-planner release restored to canonical candidate |
| B | origin/codex/rafii-growth-loop | acf2393e58d6 | verified P0 Growth Loop production release restored to canonical candidate |
| B | origin/codex/rafii-inbound-budget-rate-fix | 9b67eb09b007 | caller-identity successor budget/cooldown fix integrated |
| C | origin/codex/rafii-phone-caller-identity | 2a8224e6aee1 | production-migrated caller identity code integrated behind existing phone/inbound/verification gates; physical-device Face ID/Touch ID acceptance remains external |
| E | origin/codex/rafii-social-wave4-a | 13dd11228111 | stack dependency fully included by Wave 4B successor |
| C | origin/codex/rafii-social-wave4-b | f4bf7c7a4c4c | Wave 4 A/B/C stack integrated fail-closed; live provider approvals/OAuth/publishing/analytics/comments remain off |
| E | origin/codex/rafii-social-wave4-c | 1722eb667c9e | Wave 4C was merged into the Wave 4B stack; successor integrated |
| C | origin/codex/rafii-v3-stage3-20260927 | 7cd7622e2736 | V3 through Radar Stage 3 integrated; Radar/provider sources remain default-off pending authorized activation |

## Dirty worktrees preserved

No dirty worktree was reset, cleaned, stashed, or merged directly. Dirty worktrees are category D even when their underlying branch is already landed or separately reconstructed.

| Path | Branch | HEAD | Dirty paths | Reason |
|---|---|---|---:|---|
| /Users/ouxianxing/Documents/James-Au-Studio | consumer-saas | 468811b73d28 | 514 | dirty worktree with 514 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/.codex/worktrees/developer-ai-exemption/James-Au-Studio | codex/developer-ai-exemption | 56380501e9bd | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/.codex/worktrees/mobile-theme-toggle-release/James-Au-Studio | codex/mobile-theme-toggle-20260928 | 3cce26169902 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/.codex/worktrees/rafii-call-status-ui/James-Au-Studio | codex/rafii-call-status-ui | a67d951edcb7 | 3 | dirty worktree with 3 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is B |
| /Users/ouxianxing/.codex/worktrees/rafii-passkey-identity/James-Au-Studio | codex/rafii-passkey-identity | 9b67eb09b007 | 19 | dirty worktree with 19 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is D |
| /Users/ouxianxing/.codex/worktrees/social-trend-intelligence/James-Au-Studio | codex/social-trend-intelligence | b3395efc1f8f | 73 | dirty worktree with 73 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is E |
| /Users/ouxianxing/.codex/worktrees/trend-acceptance-m1-m2/James-Au-Studio | codex/trend-visual-polish-20260928 | 218276cf5db5 | 16 | dirty worktree with 16 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/.codex/worktrees/trend-visual-intelligence/James-Au-Studio | codex/trend-visual-intelligence | 595eab656841 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/Codex/2026-09-26/032-table-forced-rls-service-role/release-fix | codex/rafii-agent-entrypoint-20260926 | be284cac0996 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/Codex/2026-09-28/take-ownership-of-the-rafii-social/work/repo | codex/trend-ledger-closeout | 58abf08e13fc | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is D |
| /Users/ouxianxing/Documents/James-Au-Studio-ai-routing | ai-routing | d2f23f7be82c | 8 | dirty worktree with 8 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is D |
| /Users/ouxianxing/Documents/James-Au-Studio-all-updates | release/rafii-all-updates-20260927 | d5bb9d6b1e03 | 133 | dirty worktree with 133 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-consumer-ready | codex/consumer-ready-release | b4078713b32a | 2 | dirty worktree with 2 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is E |
| /Users/ouxianxing/Documents/James-Au-Studio-context-pocket-fix | fix/context-pocket-source-hygiene-20260926 | f1346fca793d | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-growth | claude/growth-phase0 | efc62a1d4a01 | 9 | dirty worktree with 9 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-growth-loop | codex/rafii-growth-loop | acf2393e58d6 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is B |
| /Users/ouxianxing/Documents/James-Au-Studio-hosted-integration-20260928 | codex/hosted-social-integration-20260928 | 7688840e4bad | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-hosted-wave3 | claude/hosted-connectors-wave3 | 66937062df44 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-jev-scoring-recovery | codex/jev-scoring-recovery-20260927 | 0ba0c60406dc | 5 | dirty worktree with 5 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-languages | languages-per-channel | 5dd8188c4285 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-launch-20260923 | codex/launch-audit-20260923 | 468811b73d28 | 483 | dirty worktree with 483 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-live-agent | feat/rafii-live-agent | e11c3fbc8e5c | 42 | dirty worktree with 42 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-postdoctor-v2 | codex/postdoctor-evidence-v2-20260927 | a9a4e64cbb25 | 7 | dirty worktree with 7 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is B |
| /Users/ouxianxing/Documents/James-Au-Studio-raffi-launch | raffi/launch-final | 1761d3c6ccda | 66 | dirty worktree with 66 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-rafii-polish-20260926 | codex/rafii-polish-20260926 | 818d6b769537 | 12 | dirty worktree with 12 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-release-reconcile-20260926 | codex/rafii-release-reconcile-20260926 | 1030397f79b2 | 3 | dirty worktree with 3 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is B |
| /Users/ouxianxing/Documents/James-Au-Studio-rla-scenes | feat/rla-scenes | a271c04d0b54 | 4 | dirty worktree with 4 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-site-agent | raffi/site-agent | 056f71b7515a | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-social-wave4-a | codex/rafii-social-wave4-c | 1722eb667c9e | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is E |
| /Users/ouxianxing/Documents/James-Au-Studio-twilio | fix/rafii-phone-live-diagnostics | c2f24bce0052 | 4 | dirty worktree with 4 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio-v3-phase1 | codex/rafii-v3-phase1-20260927 | 8cf23512b809 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is E |
| /Users/ouxianxing/Documents/James-Au-Studio-v3-phase2 | codex/rafii-v3-phase2-20260927 | 38a3a061a039 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is E |
| /Users/ouxianxing/Documents/James-Au-Studio-v3-stage3 | codex/rafii-v3-stage3-20260927 | 7cd7622e2736 | 1 | dirty worktree with 1 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is C |
| /Users/ouxianxing/Documents/James-Au-Studio/.claude/worktrees/wf_24d9f45f-4a5-1 | rafii/model-picker-server | 677d49c23e4d | 20 | dirty worktree with 20 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |
| /Users/ouxianxing/Documents/James-Au-Studio/.claude/worktrees/wf_24d9f45f-4a5-2 | rafii/model-picker-web | 677d49c23e4d | 29 | dirty worktree with 29 uncommitted/untracked paths; preserved, never merged directly; underlying branch classification is A |

## Migration reconciliation

- Pre-existing canonical migrations were left immutable.
- Consolidation adds 037_growth_phase1.sql, 038_growth_closed_loop.sql, 039_radar.sql, 044_social_provider_webhooks.sql, and the already-production-applied 045_phone_caller_identity.sql.
- 044_youtube_coach.sql remains only on incomplete V3 Stage 4 and is not landed; the 044 collision is resolved by preserving Stage 4 as WIP, not by renumbering a released migration.
- Dirty passkey-identity work still contains untracked 046_phone_passkey_identity.sql; it remains outside the release.
- 026-029 remain reserved for unfinished AI-routing reconciliation.

Full machine-readable per-ref and per-worktree metadata is in inventory.json.
