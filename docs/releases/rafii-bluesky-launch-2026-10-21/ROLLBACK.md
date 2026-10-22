# Bluesky launch rollback and kill switch (A8, D6)

Recorded 2026-10-22 ~05:45Z.

## Current production (rollback target)

- Deployment: `dpl_C57zH6ZPWejerDrysB864XDEw3Qo` (CLI deploy, 2026-10-22 01:52Z, READY, rollback candidate).
- Aliases: rafii.io, www.rafii.io, postriff-phase2-private.vercel.app, postriff-phase2-private-jamesau0723-6572s-projects.vercel.app.
- Source: `origin/claude/mastodon-full-prod-candidate` at `d3366822` (856 of 856 deployed backend and skills files byte-match).
- Deploy owner: the Mastodon session (local_5c65354d). Any Bluesky release must include `d3366822` or be coordinated with it.
- Note: the previous target in the checklist, `dpl_yKAToJbv…` (7dc95e2e), lost its aliases overnight and is no longer the live build.

## Release candidate

- Branch `claude/rafii-bluesky-launch-20261022`, commit `01cf90a3` = `d3366822` + one Bluesky commit.
- No database migration. No environment variable is required for the code itself.

## Lever 1: roll back (fastest, no build)

```
vercel rollback dpl_C57zH6ZPWejerDrysB864XDEw3Qo --scope jamesau0723-6572s-projects
```
Pre-check: `vercel api /v2/deployments/dpl_C57zH6ZPWejerDrysB864XDEw3Qo/aliases?teamId=team_PgXY5VdAYKcsv0RLoDPHscNq` must show the deployment is still READY. Time to take effect: alias swap, seconds.

Effect on Bluesky grants made under the candidate:
- Stored grants are kept; nothing is deleted.
- Identity-only grants (`atproto`) still identify the account. The old code treats them as publish Assisted.
- The old code lacks the renewal overlay, so a Bluesky card may show Reconnect again after its access token lapses (the B2 trap). That is a display regression, not data loss.
- If `POSTRIFF_BLUESKY_CLIENT_ORIGIN` was moved to rafii.io before the rollback, the old code also uses rafii.io as client_id, because it reads the same variable. Grants stay consistent.

## Lever 2: pause Bluesky (needs a new deployment)

Set `POSTRIFF_OAUTH_BLUESKY_DISABLED=true` in the production environment, then deploy. Connect and use then answer "This platform is paused for now". Time to take effect: one build (about 2.5 to 4 minutes) plus promotion. Use this only if a rollback would also remove other lanes' fixes.

## Kill criteria (approved together with the promotion in H2)

K1 a token, DPoP key or client key in a log, receipt or response · K2 more than 10% of Bluesky callbacks fail in any 15 minutes with at least 20 callbacks (user denials excluded) · K3 server errors above 2% for 10 minutes, or pool exhaustion · K4 any write to a customer repository nobody approved · K5 more than 10% of new connections show Reconnect within 30 minutes · K6 bsky.social or plc.directory rate-limits Rafii for more than 5 minutes (pause instead of retrying harder).
