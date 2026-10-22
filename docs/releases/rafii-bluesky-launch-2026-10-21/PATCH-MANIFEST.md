# Bluesky patch manifest (A7)

Commit `01cf90a3` on branch `claude/rafii-bluesky-launch-20261022`, parent `d3366822` (the live source). 21 files, +1025 / −63.

## Files

| File | What changed |
| --- | --- |
| `src/postriff_phase2/atproto_oauth.py` | P0: identity-only `atproto` consent, granular publish scopes, DID input, pinned no-redirect transport. Launch: definitive vs transient refresh errors, document cache with one retry, opt-in consent links. |
| `src/postriff_phase2/channels.py` | Bluesky joins YouTube in the vault renewal overlay, so a renewing grant is not shown as Reconnect. |
| `src/postriff_phase2/oauth.py` | P0: `has_publish_scopes`. Launch: mark a Bluesky grant non-renewing only on a definitive refusal; site-wide cap of 300 Bluesky connect starts per minute. |
| `src/postriff_phase2/hosted_social.py` | P0: verified publishing (DID, text, facets, image CID read-back), image validation, grapheme limit. |
| `src/postriff_phase2/publisher.py`, `text_measure.py`, `requirements.txt` | P0: grapheme counting (`regex==2026.9.29`), human approval for every Bluesky post. |
| `src/postriff_phase2/net_guard.py` | P0: allow `text/plain` `/.well-known/atproto-did` on the pinned transport. |
| `src/rafii_control/founder_metrics_ops.py` | Founder health applies the same vault overlay to Bluesky. |
| `web/src/features/channels/channel-card.tsx`, `web/src/lib/channels/state.ts` | P0: "Identity connected" badge and the "Grant publishing" upgrade. |
| `web/src/config/channels.ts`, `web/src/lib/channels/publishing-support.ts` | Copy: connecting confirms identity only. |
| `web/package.json`, `scripts/cloud-bluesky-validation.sh` | `ci:bluesky:jcb` cloud suite. |
| Tests | `tests/test_bluesky_launch_readiness.py`, `tests/test_bluesky_p0_hardening.py` (minus the obsolete Vercel-branch test), `tests/phase2/postgres_bluesky_launch.py`, web channel and copy tests. |

Dropped from P0: its `vercel.json` per-branch Git-deploy toggle (Git deploys are off globally since 2026-10-18).

## Dry-run cherry-pick of only this commit onto other lanes (git merge-tree, 2026-10-22 ~05:40Z)

| Lane head | Result |
| --- | --- |
| claude/mastodon-full-prod-candidate d3366822 (live) | clean |
| codex/rafii-tiktok-launch-20261021 040c2314 | conflict: web/package.json only |
| claude/mastodon-launch-blockers b2e092f0 | conflict: publisher.py, web/package.json |
| codex/rafii-x-g15-media-20261020 48dc8611 | conflict: channels.py, oauth.py, web/package.json |
| claude/linkedin-launch-20261022 d1ae8f9e | conflict: oauth.py, web/package.json, channel-card.tsx |
| claude/linkedin-qualification-integration-20261022 c4c74777 | conflict: oauth.py, publisher.py, web/package.json, channel-card.tsx |
| codex/rafii-telegram-production-20261010 bfb2df0e | conflict: hosted_social.py, oauth.py, web/package.json, channel-card.tsx |
| codex/discord-ping-runtime-20261021 362666dc | conflict: oauth.py, publisher.py, web/package.json, channel-card.tsx |
| codex/rafii-pinterest-production-prep-20261014 7dc95e2e | conflict: oauth.py, web/package.json |

`web/package.json` conflicts are one added script line. The release owner should integrate on top of `d3366822` + `01cf90a3`, then bring other lanes in. No other agent's branch was merged, rebased or touched.
