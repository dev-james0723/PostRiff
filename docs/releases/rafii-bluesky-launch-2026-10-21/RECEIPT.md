# Bluesky launch receipt

> **Update 2026-10-22 ~06:40Z:** production is now `dpl_AkP8r1Lfx4nWgCYSJuJxCKWkF3yM` = `claude/mastodon-full-prod-candidate` `f6edf90a` (d3366822 + a Mastodon schedule read-back fix). The Bluesky commits were rebased onto `75c7a6be` (current branch head) and passed JCB `h8v537cdh7`. Use `dpl_AkP8r1Lfx4nWgCYSJuJxCKWkF3yM` as the rollback target; older IDs below are history. The Mastodon session builds and promotes production.

Updated 2026-10-22 ~06:10Z by the Bluesky launch agent. No credentials, tokens, account details or environment values are recorded here.

## James's answers (2026-10-22)

- H1 test account: `jamesaucreates.bsky.social` (did:plc:lwc7oniypsw6h6gkvpudufd2), which is James's own creator account, not a throwaway; the baseline grant is disconnected right after the test.
- T0: tomorrow, 2026-10-23 (hour not given; gates count back from the start of that day in Hong Kong time, 2026-10-22 16:00Z, unless James says otherwise).
- Legal approver: James. The Bluesky paragraph is now in `/privacy` source; the Draft banner stays until James signs.

## Source and production

- Live production (rollback target): `dpl_C57zH6ZPWejerDrysB864XDEw3Qo`, CLI deploy 2026-10-22 01:52Z, = `origin/claude/mastodon-full-prod-candidate` `d3366822` (856/856 deployed backend and skills files byte-match). Production moved off `dpl_yKAToJbv…`/`7dc95e2e` overnight; the plan was re-based on `d3366822`.
- Candidate: branch `claude/rafii-bluesky-launch-20261022`, draft PR https://github.com/dev-james0723/PostRiff/pull/221 (base `claude/mastodon-full-prod-candidate`). No database migration.
- Deploy owner for production: the Mastodon session; Bluesky must ship on top of `d3366822`.

## Cloud validation (JCB on Depot, the only heavy compute used)

| Run | Result | Notes |
| --- | --- | --- |
| `qfcqrmm372` | exit 1 | 8 failures from tests asserting the literal `provider='youtube'` (query kept that literal afterwards); 1 error in a Mastodon-lineage test that already fails on `d3366822` (excluded, reported to the deploy owner) |
| `td07wtg4xp` | exit 0 | 496 Python tests, `postgres_bluesky_launch`, `postgres_connection_health`, 26 web tests, lint (warnings only), typecheck |
| `z7bvzfctkm` | exit 0 | after review fixes: 500 Python tests, both PostgreSQL suites (renewal p95 62.3 ms, burst 300/700), 26 web tests, lint, typecheck |

The `jcb ci` task was temporarily remapped to `ci:bluesky:jcb` for each run and restored; the remap is not committed.

| `h8v537cdh7` | exit 0 | rebased onto `75c7a6be`; full `test_founder_product_events` restored (501 tests), both PostgreSQL suites, web tests, lint, typecheck |

## Independent review (B6)

Codex CLI `codex review --base d3366822` (read-only, CLI fallback) found 1 P1 and 3 P2, all fixed in the follow-up commit and covered by tests:
- P1: plc.directory serves DID documents as `application/did+ld+json`; the pinned transport rejected it, which would have broken every standard Bluesky connect. Fixed; a real read-only lookup of bsky.app's DID, PDS and authorization server succeeded afterwards.
- P2: Bluesky's 3,000-byte text cap is now enforced beside the 300-grapheme cap.
- P2: `invalid_client`/`unauthorized_client` no longer disable a customer's grant (operator problem, 503).
- P2: the card offers "Grant publishing" when the image scope is missing.

## Checklist status

| Item | Status | Evidence or blocker |
| --- | --- | --- |
| A1 | Done | live re-frozen at `dpl_C57zH6ZP…`/`d3366822` |
| A2 | Blocked | H1: James connects a test account |
| A3 | Done | P0 applied on `d3366822` (only `vercel.json` conflicted, dropped) |
| A4 | Done | `td07wtg4xp`, `z7bvzfctkm` |
| A5 | Blocked | H2: build approval |
| A6 | Done | live acceptance on rafii.io after promotion; `ROLLBACK.md` |
| A7 | Done | `PATCH-MANIFEST.md` |
| A8 | Done | no migration; `ROLLBACK.md` |
| B1 | In progress | code requests identity-only `atproto`; consent screens need H1/H3 |
| B2 | In progress | fix + tests green; live before/after needs H1 and G2 |
| B3 | In progress | PostgreSQL concurrency, revoke and outage tests pass; live 30-minute refresh needs G2 |
| B4 | Blocked | live disconnect needs H1 |
| B5 | In progress | offline cases tested; consent-denial and in-app browsers need live |
| B6 | Done | adversarial tests + Codex review, all findings fixed |
| B7 | Blocked | code and test ready; env change needs H2 |
| B8 | Blocked | stretch; live publish |
| C1, C3, C6 | Blocked | stretch; H3 and a second build |
| C2 | Done | human approval for every Bluesky post (P0 tests) |
| C4 | In progress | trial plan: 2 connected accounts, 1 member; whether trial may publish not verified |
| C5 | Done | `LOADTEST.md` |
| D1 | In progress | database share done; HTTP load of the deployed build not run |
| D2, D3, D4, D5, D7 | Done | cache and retry; 300/min cap; advisors show nothing on the Bluesky tables; `WATCH.sql` first reading all zero; `COPY-AUDIT.md` |
| D6 | Done | rollback and pause written; rollback is pre-approved only via H2 |
| E1 | Blocked | draft in `PRIVACY-BLUESKY-DRAFT.md`; needs the approver |
| E2, E3, E4, E5 | Done | consent links behind a flag; copy tests; cascade from migrations 006/060; P0 human approval |
| P1 | Blocked | Supabase Auth email/SMTP settings need the dashboard |
| P2 | In progress | trial entitlements known; launch-day policy is James's call |
| P3, P6 | Blocked | James |
| P4 | Done | failed builds stopped at `runtime/verify_release_target.py` (release-provenance receipt invalid); that gate is not on `d3366822` |
| P5 | In progress | Auth DB connection strategy is absolute (advisor INFO); Vercel concurrency not measured |
| P7 | Done | `/api/cron/worker` returned 200 every minute 05:21–05:40Z on `dpl_C57zH6ZP…` |
