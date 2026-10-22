# Rafii × TikTok — App Review package (draft for James)

**Prepared:** 2026-10-22 by the launch executor
**Checklist items:** C1–C6, D3, F1
**Nothing here has been submitted.** Submitting, accepting TikTok terms and approving legal text are James's actions.

Sources: TikTok [App Review Guidelines](https://developers.tiktok.com/doc/app-review-guidelines) (updated 2026-08-04), [App Review FAQ](https://developers.tiktok.com/doc/getting-started-faq), [Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines), [Webhooks Events](https://developers.tiktok.com/doc/webhooks-events), [Webhooks Verification](https://developers.tiktok.com/doc/webhooks-verification).

## C2 — App details (portal → Rafii app 7689508412459370497 → Production)

| Field | Proposed value | Check |
|---|---|---|
| App name | `Rafii` | Custom, no "TikTok", matches the website name |
| Icon | Existing Rafii mark | Clear, not confusable with another brand |
| Category | Productivity / social media management | — |
| Description (user-facing) | "Rafii helps creators and small teams turn their ideas into posts for each platform. With TikTok, Rafii prepares a video post, shows TikTok's own privacy, interaction and disclosure choices, and posts it to your account only after you approve that exact post." | Describes what the app does and how |
| Website URL | `https://rafii.io` | Not a login page; has channel directory, FAQ and pricing. Footer links `/privacy`, `/terms` and `/data-deletion` are visible without a menu (verified 2026-10-21). |
| Terms of Service URL | `https://rafii.io/terms` | **Still marked Draft with placeholders. Must be final before submitting (C1).** |
| Privacy Policy URL | `https://rafii.io/privacy` | **Still marked Draft and does not mention TikTok. Must be final before submitting (C1).** |
| Web redirect URI (Production) | `https://rafii.io/api/oauth/tiktok/callback` | Matches Rafii's fixed callback route |
| Webhook callback URL | `https://rafii.io/api/tiktok/webhook` | Exists in release candidate `codex/rafii-tiktok-launch-20261021`. Configure it only after that release is live **and** migrations 044 + `20261022_tiktok_provider_webhooks` are applied. |

**Risk:** the guidelines say apps still in development or testing are not approved, and `/api/health` reports `phase0: incomplete`, `customerValidated: false`. The reviewer sees the website and the demo, not that endpoint, but the site and demo must look like a finished product.

## C3 — Products and scopes (request only these)

| Product | Scope | Why Rafii needs it | Where it is used |
|---|---|---|---|
| Login Kit (Web) | `user.info.basic` | Confirm which TikTok account is connected (open_id, display name, avatar) | `TikTokProvider.identity` (`src/postriff_phase2/wave3_connectors.py`) |
| Content Posting API: Direct Post | `video.publish` | Post one approved video to the creator's own profile; read creator_info and publish status | `HostedSocial._submit_tiktok`, `_reconcile_wave3` (`src/postriff_phase2/hosted_social.py`) |

**Remove before submitting**, if present on the Production config: `video.upload`, `video.list`, `user.info.profile`, `user.info.stats`, Share Kit, Display API. They are not built or demonstrated, and the guidelines say extra products and scopes delay review.

## C4 — URL properties

Both verification files are served by the release candidate:
- `web/public/tiktokZXN6P78dvnOAOs6qgUIUjfBG4ZWRu5iv.txt` — already live, HTTP 200.
- `web/public/tiktokQeWihaAW0Yiv5hiY1qNzXqn1Fp6Y9l3n.txt` — added from `91d0872b`, currently 404 on rafii.io until the release candidate is deployed.

James confirms in the portal which property each token belongs to (decision D4).

## C5 — Content Sharing Guidelines UX audit (code level; screenshots pending a hosted Sandbox preview)

| Guideline point | Rafii behaviour | Evidence |
|---|---|---|
| Show the creator's nickname before posting | "Posting as {nickname or username}", from `creator_info` | `web/src/features/queue/publish-options.tsx` |
| Read creator_info when rendering *and* before posting | Fetched by the composer; read again in `_submit_tiktok` | `publish-options.tsx`; `hosted_social.py` |
| Privacy dropdown, no default, only allowed options | `privacyLevel: null`, options from `privacy_level_options` | `web/src/lib/channels/tiktok-rules.ts` `initialChoice`; `problems()` |
| Comment/Duet/Stitch off by default, greyed out if the creator disabled them | All `false` initially; `interactionDisabled()` | `tiktok-rules.ts`, `publish-options.tsx` |
| Max video duration | Blocks approval and re-checks at dispatch | `problems()`; `_submit_tiktok` |
| Commercial disclosure (your brand / branded content), labels, branded cannot be private | `withCommercial`, `commercialLabel`, `privacyDisabled` | `tiktok-rules.ts` |
| Declaration text (Music Usage Confirmation, plus Branded Content Policy when branded) | `consentText()`; consent required | `tiktok-rules.ts`; server re-check in `publish_options.py` |
| Processing notice after posting | `PROCESSING_NOTICE` | `tiktok-rules.ts` |
| Unaudited notice (private only) | `UNAUDITED_NOTICE` | `tiktok-rules.ts` |
| User approves each exact post | Approval freezes options and video hash | `store.py` / approval flow |

**Gap to check in the hosted demo:** the creator avatar is fetched (`creator_avatar_url`) but the composer shows only the nickname. Showing the avatar next to the nickname is a cheap improvement before recording.

## C6 — Demo video script (1–5 videos, ≤ 50 MB each, recorded in Sandbox)

**Decision D1 is needed first.** The demo's domain must match the Website URL (`rafii.io`), but the Sandbox lane deliberately refuses production origins.

Options:
- **(a) Recommended:** a dedicated review host such as `review.rafii.io`, pointed at the Sandbox Preview, with the Website URL left as rafii.io. Ask TikTok support whether a rafii.io subdomain counts as matching.
- **(b)** Temporarily allow the Sandbox lane on rafii.io. Not recommended: it mixes Sandbox and Production keys.

Shot list (one continuous recording, narrated or with captions):

1. Open the website: rafii.io home, then the footer showing Privacy and Terms.
2. Sign in to Rafii and go to Channels → TikTok → Connect.
3. TikTok consent screen showing app name, icon and the requested scopes (`user.info.basic`, `video.publish`). Approve.
4. Back in Rafii: the account card shows the TikTok display name and avatar and the granted scopes.
5. Create a post and attach a video. Open the TikTok options:
   - "Posting as …";
   - the privacy dropdown with no default, choosing "Only me";
   - interaction toggles off, then turning Comment on;
   - commercial disclosure: open it, show both options and the label, then close it;
   - the declaration text, then ticking consent.
6. Approve the exact post. Show the processing notice and the publish status, then the private video on the TikTok profile.
7. Disconnect: Channels → TikTok → Disconnect, which revokes the token at TikTok.

## C1 — Legal text (draft for James and counsel; not legal advice)

Proposed Privacy Policy section "TikTok":

> When you connect a TikTok account, Rafii receives from TikTok your account's open ID, display name and profile image (scope `user.info.basic`). If you enable publishing (scope `video.publish`), Rafii also reads TikTok's current posting options for your account before each post. Rafii uploads to TikTok only a video and caption that a member of your workspace approved, with the privacy, interaction and disclosure choices shown at approval. Rafii stores TikTok access and refresh tokens encrypted and uses them only for these actions. Rafii does not sell TikTok data or use it for advertising. When you disconnect, or when TikTok tells Rafii that you removed access, Rafii deletes its copy of the tokens and stops all TikTok actions. See the data-deletion page to delete your account and data.

**Terms placeholders** (James decides; the agent does not choose legal positions):
- `[Refund policy — to be confirmed by counsel.]`
- `[Jurisdiction — to be confirmed by counsel]`

Removing the "Draft — pending qualified legal review" banner requires James's sign-off (decision D2).

## D3 — Scale notes for "thousands of users"

- **TikTok caps:**
  - Before the audit: 5 posting users per 24 h, private accounts only.
  - After the audit: a 24 h active-creator cap set from the audit form, plus about 15 posts per day per creator, shared across all apps.
- **Rafii worker:** `/api/cron/worker` runs every minute with `POSTRIFF_WORKER_MAX_JOBS` default 10 and a 20 s budget, shared across all platforms (`src/postriff_phase2/hosted_worker.py`). TikTok jobs upload up to 100 MB from memory in 5–64 MB chunks. Raising the budget is a separate, measured change: run a synthetic load test before the audit form numbers are final.
- **Connect alone is cheap:** one token exchange plus one `user/info` call per user, then refresh every 24 h (`refresh_margin` 300 s). A thousand connects a day is well within TikTok's per-user limits.

## F1 — Audit application inputs (prepare after approval)

- **Expected creators posting per day:** start with a realistic rollout cohort, not the total signups.
- **Expected posts per creator per day:** usually 1–3 (cap is about 15).
- **Content type:** original creator videos, approved per post; no automated or bulk reposting.
- **Countries:** to be decided by James.
