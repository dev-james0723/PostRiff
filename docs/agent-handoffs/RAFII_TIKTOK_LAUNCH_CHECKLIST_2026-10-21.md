# Rafii × TikTok — public-connect launch checklist

**Created:** 2026-10-21 (baseline audit ~20:50Z, read-only)
**Release owner:** James
**Executor:** handoff agent (see `RAFII_TIKTOK_LAUNCH_AGENT_PROMPT_2026-10-21.md`)
**James's goal:** thousands of customers can connect their TikTok accounts to Rafii from 2026-10-22.

## 0. Reality check — read before anything else

- **TikTok owns the critical path.** App Review "may take several days to two weeks" after submission, and nobody outside the Sandbox (max 10 target users) can authorize the app until it is approved.
- **Approval is not public posting.** Until a separate Content Posting audit passes, Direct Post is limited to `SELF_ONLY` posts, at most 5 posting users per 24 hours, and accounts that are private at posting time.
- **What can be true on 2026-10-22:**
  1. TikTok is shown honestly as "not connectable yet / export only".
  2. Every Rafii-owned prerequisite below is done with evidence.
  3. App Review is submitted.
- **What cannot be forced on 2026-10-22:** TikTok approval, the posting audit, and therefore public connect for thousands of users.
- **Done for this checklist means:** every Rafii-owned item is `[x]` with evidence, every James action is completed in batched checkpoints, App Review is submitted, and the post-approval rollout is staged behind flags.

## 1. Verified baseline (2026-10-21)

| Area | State | Evidence |
|---|---|---|
| Connections | **0 TikTok credentials ever** in prod. 1 unconsumed identity OAuth start (2026-10-07 04:44Z, `user.info.basic`). Staging has 6 unconsumed starts (2026-10-14 21:00Z → 10-15 05:47Z) and 0 credentials. | Prod Supabase `buoyhkbodnhzngaotoel`, staging `oxacvkhpfgytkepxcaqh`: `pr_oauth_transactions`, `pr_encrypted_credentials`, `pr_connection_health` |
| Traffic | No TikTok requests in production runtime logs, 2026-10-14 → 10-21 | Vercel `get_runtime_logs` query `tiktok`, 7 days |
| Live code | `rafii.io` = CLI deploy `dpl_yKAToJbv…` = commit `7dc95e2e` (`codex/rafii-pinterest-production-prep-20261014`), **not** `consumer-saas`. The newer `dpl_Aj8ZqLm1…` (10-20) is staged and unaliased. TikTok code is identical on both lines. | Memory `reference-identify-live-vercel-code`; `git diff origin/consumer-saas 7dc95e2e` has 0 TikTok lines |
| Public labels | identity **Direct**; publish **Assisted**; schedule **Assisted**; analytics, comments, reply **Unsupported**. Page says "Assisted · publishing in review". | `web/src/config/channels.ts` (`identityOnly`), https://rafii.io/channels/tiktok |
| In-app connect | "Not available yet", Continue disabled (observed 2026-10-13; not rechecked signed-in on 10-21). Readiness is `configured_awaiting_provider_review` while `production_reviewed` is false. | `src/postriff_phase2/oauth.py` provider catalog; sandbox-branch handoff 2026-10-13 |
| Prod env (names only) | `POSTRIFF_OAUTH_TIKTOK_CLIENT_ID` and `_CLIENT_SECRET` present. `_REVIEWED`, `_PUBLISH_LIVE_TESTED`, `_PUBLISH_APPROVED` absent from the Production env store; they exist only as Preview-scoped to `codex/rafii-tiktok-sandbox-oauth-20261013`. `RAFII_VIDEO_UPLOADS_ENABLED` exists as a Secret with an unknown value. | `vercel env ls`. CLI deploys can inject per-deploy values the store does not show. |
| TikTok app | App ID `7689508412459370497`, Sandbox `7689479552734136327`, target user `@jamesaucreates`. Sandbox has Login Kit, `user.info.basic`, `video.publish`, Direct Post on. Registered Sandbox callbacks (10-13): `https://rafii.io/api/oauth/tiktok/callback`, `https://postriff-phase2-private.vercel.app/api/oauth/tiktok/callback`. **Production status: Draft** (last seen 10-13/14, not rechecked 10-21). | `codex/rafii-tiktok-sandbox-oauth-20261013:docs/agent-handoffs/RAFII_TIKTOK_SANDBOX_OAUTH_2026-10-13.md` |
| Sandbox OAuth | Never completed. On 10-14 the browser landed on TikTok's homepage with no consent page and no callback. | `…/RAFII_TIKTOK_DISABLE_AUTO_AUTH_SANDBOX_2026-10-14.md` on the same branch |
| Domain files | `/tiktokZXN6P78dvnOAOs6qgUIUjfBG4ZWRu5iv.txt` → 200 with token. `/tiktokQeWihaAW0Yiv5hiY1qNzXqn1Fp6Y9l3n.txt` → **404** (only on local branch `codex/rafii-tiktok-production-url-verify-20261013`, commit `91d0872b`). | `curl` on rafii.io |
| Legal | `/privacy` and `/terms` are "Draft — pending qualified legal review" (updated 2026-10-09). Terms has `[Refund policy …]` and `[Jurisdiction …]` placeholders. Neither mentions TikTok. Footer links to `/privacy`, `/terms` and `/data-deletion` are present. | rafii.io pages |
| Health | `/api/health`: `phase0: incomplete`, `customerValidated: false`, `sourceRevision: null` | `curl https://rafii.io/api/health` |
| Release policy | Git-triggered Vercel deploys are **off** (`git.deploymentEnabled=false`). Releases go through one SHA-pinned candidate, `vercel deploy --prod --skip-domain`, hosted acceptance, then an authorized promote. | `AGENTS.md`, `CLAUDE.md`, `docs/operations/VERCEL-ON-DEMAND-COST-CONTROL-20261018.md` |

### Code facts that drive the work

- `TikTokProvider` is in `src/postriff_phase2/wave3_connectors.py`.
  - Scopes are identity `user.info.basic`, publish/schedule `user.info.basic, video.publish`.
  - Web Login Kit runs without PKCE; hex PKCE sits behind `POSTRIFF_TIKTOK_HEX_PKCE`.
  - Publishing uses `FILE_UPLOAD` Direct Post through `hosted_social._submit_tiktok`, with a fresh `creator_info` query first.
- `TikTokProvider` has **no `server_schedule`**. Only Instagram and Pinterest set it, so TikTok schedule stays Assisted even after review.
- There is **no** TikTok deauthorization webhook handling.
- Composer rules follow TikTok's Content Sharing Guidelines in `web/src/lib/channels/tiktok-rules.ts`, re-checked server-side in `src/postriff_phase2/publish_options.py`.
- Hosted gating comes from env (`providers.py`):
  - `POSTRIFF_OAUTH_TIKTOK_REVIEWED` turns `production_reviewed` on: identity Direct and public connect.
  - Publish is Direct only if `_PUBLISH_LIVE_TESTED` and `_PUBLISH_APPROVED` are also true and `video.publish` is granted.
- Worker: `/api/cron/worker` runs every minute, default `POSTRIFF_WORKER_MAX_JOBS=10`, shared by all platforms. The video bucket cap was 50 MB (YouTube audit), and the verified read cap is 100 MB.


## Status update — 2026-10-22 ~02:30Z (executor, this session)

- **Live lineage changed.** `rafii.io` is now CLI deploy `dpl_HQHUJrhr53sKDsDMwRJ1pvpsHJjs` (READY 2026-10-21 21:15Z). All 2,220 deployed files sha1-match `origin/claude/mastodon-connect-prod-candidate` `75312e78`, which is `7dc95e2e` + 4 Mastodon commits with 0 TikTok lines changed. Work branch `codex/rafii-tiktok-launch-20261021` is based on `75312e78`.
- **New blocker found and fixed (D1a).** TikTok has no `publisher` object, so `POSTRIFF_OAUTH_TIKTOK_REVIEWED=true` alone used to unlock Connect *and* dispatch, Direct labels and chat promises.
  - TikTok now has `separate_publish_gate`: posting also needs `_PUBLISH_LIVE_TESTED` and `_PUBLISH_APPROVED`.
  - So E2 (open Connect after Login Kit approval) no longer opens posting before the audit.
- **B1 evidence.**
  - All 6 staging attempts sent `redirect_uri=https://rafii-tiktok-sandbox-650aea72.vercel.app/api/oauth/tiktok/callback`, which was not in the Sandbox redirect list recorded on 10-13 (rafii.io and postriff-phase2-private only).
  - The prod attempt (10-07) used `https://postriff-phase2-private.vercel.app/api/oauth/tiktok/callback` with the Production key while the Production app was Draft.
  - The callback-mismatch hypothesis is strong but needs the portal view (H1).
- **Portal read:** Claude in Chrome reached the signed-in portal and listed the app (`Rafii 7689508412459370497`, Individual ownership). Reading the app page failed 3 times because the extension kept dropping its tab group. Production status is still unverified, so it moves into H1.
- **D2 needs migrations.** `pr_social_provider_events` (migration 044) is **not applied** in prod or staging. The TikTok webhook therefore needs 044 + `20261022_tiktok_provider_webhooks.sql`, both approved by James, before the webhook URL is configured in the portal. Until then it returns 503 and never leaks details.
- **App Review package draft:** `docs/agent-handoffs/RAFII_TIKTOK_APP_REVIEW_PACK_2026-10-22.md` covers C1–C6, D3 and F1.
- **Review and validation (02:20–02:50Z).**
  - An independent Codex CLI review (fallback, read-only) found 3 P2 issues, all fixed in `2e8c3a12`: the stale-revocation fence, the `:443` alias of production origins, and a CI lane that stopped before the web checks.
  - JCB remote: typecheck `cv3c3gshfl` exit 0; lint `xdbsl600m6` exit 0 (36 warnings); web tests 961/0.
  - Full Python suite `b7n5h8rbz2`: 12 failures and 9 errors, none in TikTok code (Library LibreOffice, a Mastodon failure that predates this branch, Pinterest order-dependence).
  - The re-run of the corrected lane was refused because another session's JCB run holds the cache lock; retry once it is released.
  - Draft PR: https://github.com/dev-james0723/PostRiff/pull/220 (base `claude/mastodon-connect-prod-candidate`).
- **B4: no new build needed.** Protected Preview alias `rafii-tiktok-sandbox-650aea72.vercel.app` = `dpl_EH2bH8rZQSveGu4eknTZqJDT2Qbu`, built from `e107bbb5`, READY. H1 uses it as is: James only needs to register its callback in the Sandbox and consent.
- **Portal read with Ego Lite (2026-10-22 ~03:05Z, read-only, no changes).**
  - **Production** app = **Draft** and empty: no category, description, Terms or Privacy URL, platform, products or scopes. History shows only "Created Sep 25". It has **never been submitted**.
  - **Sandbox** `7689479552734136327`:
    - Category Photo & Video; description (100/120) "Draft, schedule and publish posts to your own social accounts, with your approval before every post."
    - Terms, Privacy and website URLs all on `postriff-phase2-private.vercel.app`; platform Web.
    - Login Kit redirect URIs: `https://postriff-phase2-private.vercel.app/api/oauth/tiktok/callback`, `https://rafii.io/api/oauth/tiktok/callback`, `https://rafii-tiktok-sandbox-650aea72.vercel.app/api/oauth/tiktok/callback`.
    - Content Posting API with Direct Post on; scopes `user.info.basic`, `video.publish`, `video.upload`; target user `jamesaucreates` (added Sep 28).
  - **Correction to B1:** the Preview callback *is* listed, so the callback-mismatch hypothesis is unlikely. Remaining candidates, all unverified:
    1. Sandbox edits saved but not applied ("Apply changes");
    2. the Preview's `POSTRIFF_OAUTH_TIKTOK_SANDBOX_CLIENT_ID` holds the Production (Draft) key;
    3. a TikTok session or account mismatch at consent time.
  - **B3 is not needed.** H1 now asks James to retry consent once. If TikTok bounces, he compares the `client_key` in the TikTok URL with the Sandbox client key shown in the portal (a prefix is enough; never paste the secret).

## 2. Legend

`[ ]` not started · `[~]` in progress · `[x]` done (evidence required) · `[!]` blocked (reason required)
Owner: **A** = agent · **J** = James · **T** = TikTok

## 3. Checklist

### Phase A — Guardrails and launch-day posture (target: 2026-10-22)

- [x] **A1 (A)** Re-verify the baseline before changing anything: which deployment holds `rafii.io` (`list_deployment_aliases`), its source lineage (sha1 file match), TikTok env names, DB counts. Update section 1 with timestamps.
- [x] **A2 (A)** Keep public connect closed.
  - `POSTRIFF_OAUTH_TIKTOK_REVIEWED` stays absent in Production.
  - **Never set any TikTok `_REVIEWED` / `_PUBLISH_*` flag as a workaround.** Unapproved OAuth would send thousands of users to a TikTok error page.
- [x] **A3 (A)** Copy fix: TikTok must not show identity **Direct** while connecting is closed.
  - Give TikTok its own capability map instead of the shared `identityOnly`, which other channels also use.
  - Set `reviewStatus` to say connecting *and* publishing are in review.
  - Fix the FAQ sentence "Not yet. publishing in review."
  - Accept when: the page shows no Direct level until E2 is done.
- [ ] **A4 (A)** Confirm the Assisted path works for TikTok: draft, video preview, export/download. Use synthetic or James-owned data only.
- [ ] **A5 (J)** Approve the launch message for TikTok ("connect coming soon; prepare and export today").

### Phase B — Prove Sandbox OAuth end to end (blocks the demo video)

- [~] **B1 (A)** Diagnose why 7 OAuth starts never returned.
  - Compare the exact `redirect_uri` Rafii sent with the Sandbox Login Kit redirect URIs.
  - Check what TikTok shows (error vs homepage) and look for callback hits in the Preview's runtime logs.
  - Leading hypothesis, **unverified**: the Preview origin `rafii-tiktok-sandbox-650aea72.vercel.app` callback was not registered.
  - Also check `client_key` lane (Sandbox vs Production key), scope string format, `disable_auto_auth=1`, and whether James's TikTok session is the target user.
- [x] **B2 (A)** Bring the Sandbox lane onto the live lineage.
  - Port `650aea72`, `b6a647e9`, `e107bbb5` from `codex/rafii-tiktok-sandbox-oauth-20261013`. They give a fail-closed, identity-only Sandbox lane that never falls back to Production keys.
  - Keep the 13 Sandbox tests green.
- [x] **B3 (J, portal)** Add the exact Preview callback URL to **Sandbox** Login Kit redirect URIs. Never touch Production app settings.
- [ ] **B4 (J/A)** One bounded hosted Preview for the Sandbox lane (`--skip-domain`, Preview-scoped env that already exists). This needs a release-owner exception under `AGENTS.md`.
- [ ] **B5 (J)** James signs in to TikTok as the target user and personally approves consent. The agent stops at the consent screen.
- [ ] **B6 (A)** Read back:
  - `open_id` / `providerAccountId`, granted scopes, encrypted credential row, single-use state.
  - Token refresh (24 h access, 365 d refresh).
  - Disconnect plus `/v2/oauth/revoke/`.
  - Confirm no second account appeared.
- [ ] **B7 (J+A)** One private test post.
  - James approves the exact video and caption; posting is `SELF_ONLY` to his own account, through the Sandbox lane with video uploads on in that Preview only.
  - Accept when: `publish_id` exists, `status/fetch` reaches `PUBLISH_COMPLETE`, and the post is visible only to James.

### Phase C — App Review package (agent drafts, James submits)

- [~] **C1 (A → J)** Privacy Policy and Terms.
  - Draft a TikTok section covering: data read (open_id, display name, avatar, creator_info); content posted only after approval of each exact post; token storage and encryption; retention; deletion; revocation; the data-deletion page.
  - Propose text for the placeholders.
  - James (and counsel if he chooses) approves. The agent never removes the "Draft" banner without James. This is not legal advice.
- [~] **C2 (A)** Check app details against the App Review Guidelines:
  - Custom name with no "TikTok" in it, and a clear icon.
  - User-facing description.
  - Website URL is a developed site, not a landing or login page.
  - Privacy Policy and ToS links visible without opening a menu.
  - Valid web redirect URI.
- [~] **C3 (A)** Products and scopes: request only Login Kit (`user.info.basic`) and Content Posting API Direct Post (`video.publish`). Remove anything not built *and* demonstrated, such as `video.upload`, `video.list` or `user.info.stats`, because extras delay review.
- [x] **C4 (A/J)** URL properties: confirm in the portal which property the Production app needs. If it needs the `91d0872b` file, include it in the release candidate and verify 200 on rafii.io.
- [~] **C5 (A)** Content Sharing Guidelines UX audit, with screenshots, on the real composer:
  - Creator nickname/avatar from `creator_info`.
  - Privacy dropdown with no default, offering only allowed options.
  - Comment/Duet/Stitch off by default and greyed out when the creator disabled them.
  - Max-duration check.
  - Commercial disclosure, the "Promotional content" / "Paid partnership" labels, and the rule that branded content cannot be private.
  - The exact consent text, the processing notice and the unaudited-private notice.
- [~] **C6 (A)** Demo video script and shot list covering every product and scope end to end: login, consent, account card, composer rules, approval, posting, status, disconnect.
  - **Domain-match risk:** TikTok wants the demo's domain to match the Website URL, but the Sandbox lane rejects production origins. Needs decision **D1**.
- [ ] **C7 (J)** Record (or approve an agent-assisted recording of) 1–5 videos, ≤ 50 MB each.
- [ ] **C8 (J)** Submit App Review in the portal. Accepting TikTok terms and submitting is James's action.

### Phase D — Rafii code gaps (agent; one release candidate on the live lineage)

- [x] **D1 (A)** Add `server_schedule = True` for TikTok.
  - At dispatch: re-query `creator_info`, re-check privacy option and max duration, and hold (no retry loop) if anything changed.
  - Add tests.
- [x] **D2 (A)** Deauthorization.
  - Verify TikTok's current webhook docs (`authorization.removed` or equivalent) and implement a signed webhook if one exists.
  - Otherwise make the `401` / `access_token_invalid` paths mark the connection "reconnect needed" without retrying.
  - Add tests.
- [~] **D3 (A)** Scale.
  - Confirm current Content Posting and Login Kit rate limits from TikTok docs.
  - Model the worker (10 jobs/min shared, 1-minute cron) against thousands of creators and about 15 posts/day/creator.
  - Add per-provider backpressure or a configurable job budget, and a synthetic load test. No real provider calls.
- [x] **D4 (A)** Error handling: map `unaudited_client_can_only_post_to_private_accounts`, `spam_risk_*`, `privacy_level_option_mismatch`, rate limits and the 5-user cap to clear "held"/"failed" copy with no automatic resubmission.
- [~] **D5 (A)** One SHA-pinned release-candidate branch containing A3, B2, C4 (if needed) and D1–D4.
  - JCB `ci` (or `test`/`typecheck`/`lint`) passes remotely.
  - An independent Codex review is done.
  - Open a draft PR. No merge.
- [ ] **D6 (J)** Authorize one staged production candidate (`vercel deploy --prod --skip-domain`), then hosted acceptance, then promote.
  - Coordinate with other lanes that build on `7dc95e2e`, such as the YouTube RC. One release candidate per lane, no duplicates.

### Phase E — After TikTok approves the app (gate: T)

- [ ] **E1 (T)** Production app status = Live/approved.
- [ ] **E2 (A, J approves the env change)** Verify the approval in the portal, set `POSTRIFF_OAUTH_TIKTOK_REVIEWED=true` in Production, and connect a **non-owner** test account. Confirm identity Direct, then revoke and disconnect.
- [ ] **E3 (A)** Gradual public connect rollout. Watch `pr_oauth_transactions` outcomes, callback errors and refresh failures, with a rollback plan (unset the flag).

### Phase F — Posting audit and public posting

- [ ] **F1 (A → J)** Prepare the audit application with realistic usage estimates (daily active creators, posts/day) for thousands of users. TikTok sets the 24 h creator cap from these numbers. James submits.
- [ ] **F2 (A)** Pre-audit private beta: at most 5 posting users per 24 h, private accounts only, `SELF_ONLY`. Set `_PUBLISH_LIVE_TESTED` only after B7-style verification in Production. `_PUBLISH_APPROVED` requires James.
- [ ] **F3 (T)** Audit passed.
- [ ] **F4 (A)** Public posting rollout, monitoring the ~15 posts/day/creator cap and failures.

### Phase G — Out of scope for this launch (stay Unsupported)

- **Analytics:** a Display API counts version (`video.list`, `user.info.stats`) is possible later and needs its own review and demo.
- **Comments and reply:** no official creator comment API was found. TikTok's Business API is a separate program.

## 4. Human checkpoints (batched — keep James's time minimal)

| Checkpoint | When | James does |
|---|---|---|
| **H1** (~20 min) | After B1/B2 are ready | Confirm the Production app status in the portal. Add the Sandbox callback (B3). Approve the bounded Preview (B4). Sign in and consent (B5). Approve the exact private test post (B7). Decide D1. |
| **H2** | After C1–C6 are ready | Approve the PP/ToS text (C1), record or approve the demo (C7), submit App Review (C8). |
| **H3** | After D5 | Approve the staged production candidate and promotion (D6). |
| **H4** | After TikTok approves | Approve the Production env flag (E2), submit the audit (F1), approve `_PUBLISH_APPROVED` (F2). |

## 5. Decisions needed from James

- **D1** Demo domain: record on `rafii.io` itself (which needs a safe review mode on the real domain) or on a dedicated `*.rafii.io` subdomain registered as the Website URL. Confirm against TikTok's rule before recording.
- **D2** Who signs off the legal text, and whether the "Draft" banner can go.
- **D3** Launch wording for TikTok on 2026-10-22.
- **D4** Whether the second domain-verification file ships.

## 6. Realistic timeline

- **2026-10-22:** Phases A–D done, H1 and H2 completed, App Review submitted. TikTok stays export-only for customers.
- **+ several days to two weeks:** TikTok review (E1). Rejections add resubmission cycles.
- **After approval:** public **connect** for everyone (E2–E3). Posting stays private-only, max 5 users per 24 h.
- **After audit (timing not published by TikTok):** public posting (F3–F4).

## 7. Evidence log (agent appends; never record secrets, tokens, cookies or customer data)

| UTC time | Item | Result | Evidence |
|---|---|---|---|
| 2026-10-21 20:50 | Baseline | Recorded | This document, section 1 |
| 2026-10-22 01:40 | A1 | Live = 75312e78 (dpl_HQHUJrhr…) | sha1 match 2220/2220 vs origin/claude/mastodon-connect-prod-candidate |
| 2026-10-22 01:45 | B1 | Callback mismatch evidence | staging pr_oauth_transactions.redirect_uri; prod row 10-07 |
| 2026-10-22 01:50 | B2 | Sandbox lane ported (9665ca0a, 4781c5f3) | 56 targeted tests OK |
| 2026-10-22 02:00 | D1 | server_schedule + separate publish gate (ecced2d0) | 143 + 60 targeted tests OK |
| 2026-10-22 02:10 | D2 | authorization.removed webhook (57a75c63) + candidate migration | 21 targeted tests OK; prod/staging lack migration 044 |
| 2026-10-22 02:12 | D4 | reached_active_user_cap copy (707dd871) | 45 tests OK |
| 2026-10-22 02:15 | A3 | TikTok page copy (98d28783) | identity Unsupported, "connecting and publishing in review" |
| 2026-10-22 02:20 | C4 | Second verification file added (cherry-pick of 91d0872b) | web/public |
| 2026-10-22 03:05 | Portal | Production Draft and empty; Sandbox callback already registered | Ego Lite read-only, space 36 finished |
| 2026-10-22 02:40 | D5 | Codex review fixes (2e8c3a12); web checks remote PASS; draft PR #220 | runs cv3c3gshfl, xdbsl600m6, b7n5h8rbz2 |

## Sources

- TikTok Content Sharing Guidelines: https://developers.tiktok.com/doc/content-sharing-guidelines
- TikTok App Review Guidelines (updated 2026-08-04): https://developers.tiktok.com/doc/app-review-guidelines
- TikTok App Review FAQ: https://developers.tiktok.com/doc/getting-started-faq
- TikTok Add a Sandbox (updated 2026-08-04): https://developers.tiktok.com/doc/add-a-sandbox
- TikTok Scopes Reference: https://developers.tiktok.com/docs/en/tiktok-api-scopes
