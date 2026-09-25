# Rafii coworker HTTP API

The source is `src/postriff_phase2/coworker/http.py`, with the behaviour in `coworker/service.py` and `notifications/service.py`.

Workspace routes share these rules:
- They are session-only. API tokens (`prt_…`) are refused with a 403.
- They use the same `Authorization: Bearer`, `X-PostRiff-Request: founder-alpha` and origin checks as every other `/api` route.
- A foreign workspace gets `403 {"error": "Workspace unavailable."}`, identical to a missing one.
- A feature whose flag is off answers `404 {"code": "feature_disabled"}`.

Every mutation answers with `verified: true|false`: the result was re-read and compared before the answer. A `false` means "it did not do what was asked; do not claim it".

## Notifications (flag `RAFII_NOTIFICATIONS_V2_ENABLED`; push also needs `RAFII_WEB_PUSH_ENABLED`)

| Method, path | Body | Returns |
|---|---|---|
| `GET /api/workspaces/{id}/notifications?unread=1&before=<epoch>` | — | `{items:[{id, status (delivered or read or acted), createdAt, type, category, severity, entity:{type,id}, payload:{title?, platform?, reason?, href, count?, …}, readAt, actedAt, actionable}], unread, catalogVersion}` |
| `POST /api/workspaces/{id}/notifications/{deliveryId}/{read or acted or dismissed}` | `{}` | `{changed, status, verified}` |
| `POST /api/workspaces/{id}/notifications/read-all` | `{}` | `{changed, unread, verified}`: every unread in-app notification of the caller in this workspace (and account-wide ones) becomes read; `verified` when the recount is 0 |
| `GET /api/workspaces/{id}/notification-preferences` | — | `{catalog:{version, categories[], events{type:{category,severity,email,push,transactional}}}, rows[], effective{category:{…}}, push:{available, vapidPublicKey, devices}, email:{available}}` |
| `PATCH /api/workspaces/{id}/notification-preferences` | `{scope: "workspace" or "all", category: "*" or a category, in_app?, email_mode? (immediate, digest or off), push_mode? (immediate or off), digest_frequency? (daily, weekly or off), quiet_start?/quiet_end? (minutes 0–1439 or null), time_zone?, mute_hours? (1–720 or null), email_unsubscribed?}` | `{scope, category, stored, verified}` |
| `GET /api/workspaces/{id}/push-subscriptions` | — | `{devices:[{id,label,createdAt,lastSuccessAt}]}` |
| `POST /api/workspaces/{id}/push-subscriptions` | `PushSubscription.toJSON()` = `{endpoint, expirationTime, keys:{p256dh, auth}}` | `201 {subscriptionId, active, verified}`. 400 if the endpoint is not a known push service. |
| `POST /api/workspaces/{id}/push-subscriptions/unsubscribe` | `{endpoint}` | `{revoked, verified}` |
| `DELETE /api/workspaces/{id}/push-subscriptions/{subscriptionId}` | — | `{revoked, verified}` |
| `GET /api/notifications/unsubscribe?token=` (public) | — | An HTML confirmation page with a POST button |
| `POST /api/notifications/unsubscribe?token=` (public; RFC 8058 one-click) | — | An HTML "unsubscribed" page. A repeat click changes and records nothing; a deleted account's link is refused. |
| `POST /api/notifications/email/webhook` (public; Svix-signed) | Resend event | `{outcome}`. With notifications v2 off: 404 `feature_disabled` before the body is read. |

## Coworker (`/api/workspaces/{id}/coworker/…`)

| Method, path | Flag | Returns |
|---|---|---|
| `GET status` | — | `{flags:{RAFII_*: bool}, registryRelease, notifications:{enabled,push,email}, research:[providers…], weekly:{recipes, weeks}}` |
| `GET attention` | — | `{items:[{id, type, priority, urgent, title, why, detail, evidence, href}], counts:{total, urgent}, rules}` |
| `GET weekly` | WEEKLY | `{recipes:[recipe], weeks:[week + counts]}` |
| `POST weekly/recipes` | WEEKLY (owner) | `201 {recipe, verified}`. Body: `{name, goals[], destinations:[{channelId, postsPerWeek 0–7, language}], contentMix{type:weight}, planningDay 0–6, planningHour, timeZone, voiceMode, expectImages, useResearch, maxCostUsdMicroPerWeek, model?}` |
| `PATCH weekly/recipes/{recipeId}` | WEEKLY (owner) | `{recipe, verified}` |
| `POST weekly/recipes/{recipeId}/status` | WEEKLY (owner) | Body `{status: active, paused or deleted}` → `{recipe, verified}` |
| `POST weekly/recipes/{recipeId}/prepare` | WEEKLY (edit) | Body `{maxSlots?}`: a whole number, clamped to 1–12, 8 when absent; anything else is a 400. A writer run starts only if it can finish within 240 s of the request (each run is budgeted 95 s), so none starts after about 145 s; a later call continues. `{week, advanced, drafted, verified}` |
| `GET weekly/weeks/{weekId}` | WEEKLY | `{week:{id, weekOf, state, blockedReason, slots:[{id, day, localTime, platform, account, language, contentType, goal, angle, status, reason, question, variantId, quality:{evaluator, meaning[], style[], lint[], voiceFit}, creative, draft:{text, unknowns, needsReview}}], history[]}, counts, queueHref}` |
| `POST weekly/weeks/{weekId}/slots/{slotId}/{accept, reject, answer, redo or skip}` | WEEKLY (edit) | Body `{answer?}` or `{reason?}` → `{week, slot, verified, next}` |
| `POST research/search` | RESEARCH (edit) | Body `{query}` → `{status (ok, failed or unavailable), provider, errors[], items:[{title, url, snippet, provenance{…}, evidenceId, usableForDraft:false, note}]}` |
| `GET research/providers` | — | `{providers:[{id, kind, hostedOk, capabilities, readiness:{state, reason}}], enabled}` |
| `POST source-campaigns` | WEEKLY or RESEARCH (edit) | Body `{format, text?/url?, title?, goal, audience?, cta?, destinations:[{channelId, language}]}` → `201 {sourceCampaign:{id, campaignId, sourceId, evidenceId, source, factPack{claims[], contradictions[], injectionFlags[]}, brief, angles, drafts[], creativeBriefs[], status}, verified, creative}` |
| `POST creative/plan` | CREATIVE | Body `{brief:{message, copy?, cta?}, platforms[], format}` → the creative plan |
| `GET overlays` / `GET overlays/export` | ADAPTIVE | `{voice[], brand[], strategy[], revisions, history}`. Each item has `{id, memoryType, origin (explicit or inferred), statement, scope, status, confidence, evidenceIds, counterEvidenceIds, lastSupportedAt, expiresAt, kind (note or learned)}` |
| `POST overlays/notes` / `PATCH overlays/notes/{id}` | ADAPTIVE (owner) | Body `{memoryType: voice or brand, statement, scope:{platform?, language?, contentTypeId?, audience?}}` → `{note, verified}` |
| `POST overlays/{itemId}/status` | ADAPTIVE (owner) | Body `{status: active, disabled or retired}` → `{id, status, verified}`. Learned items go through preference learning's pause/resume/retire. |
| `POST overlays/reset` | ADAPTIVE (owner) | Body `{scope: notes, learned or all, confirmed: true}` → `{reset, remaining, verified}` |
| `GET performance` | PERFORMANCE | `{posts, measured, unavailable, hypotheses:[{id, platform, dimension, statement, confidence, status, samples:{a,b}, effect, evidenceIds, counterEvidenceIds, causal:false, dateRange, expiresAt, why}], rules}` |
| `POST performance/hypotheses/{id}/decide` | PERFORMANCE (owner) | Body `{decision: experiment, dismissed or rejected}` → `{id, status, causal, verified}` |
| `GET listening` | LISTENING | `{watchlists[], opportunities:[{id, title, url, evidence[], relevance, novelty, freshness, score, confidence, status, expiresAt, why, proposedAction}], coverage}` |
| `POST listening/watchlists` | LISTENING (edit) | Body `{query, goal}` → `201 {watchlist, verified}` |
| `POST listening/opportunities/{id}/decide` | LISTENING (edit) | Body `{decision: act or dismiss}` → `{opportunity, verified}` |
| `GET engagement` | ENGAGEMENT | `{items:[{threadId, author, provider, category, priority, fresh, ageHours, why, urgent:false, summary, replyAvailable}], counts, note, capabilities, replySendingEnabled, limits}` |
| `POST engagement/threads/{threadId}/draft` | ENGAGEMENT (edit) | `201 {drafted, verified, draftId, category, text, status:"draft", label, placeholders[], sending, provenance}` |
| `GET growth` | — (owner or admin) | `{metrics{…}, definitions[], note}` |
| `GET experiments/{name}` | GROWTH | `{experiment, variant, enabled, copy}` |
