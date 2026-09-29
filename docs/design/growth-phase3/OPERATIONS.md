# Radar: local implementation and release controls

Execution state: local candidate. No production migration, release, plan activation, paid provider request, external alert or publication has been performed by this task.

## Enablement and sources

Apply additive migration `039_radar.sql` through the project's normal release process after reconciling concurrent migration numbers. Read access is service-only, with workspace authorization at the HTTP boundary. Production remains off by default in `.env.example`.

`POSTRIFF_GROWTH=1` and `POSTRIFF_RADAR=1` enable the feature. Both `POSTRIFF_RADAR_QUICK_USD_CAP` and `POSTRIFF_RADAR_DEEP_USD_CAP` must be deliberately configured, alongside the existing global/workspace daily growth caps. Missing allowances fail closed. Never copy the deterministic test fixture environment into production.

`POSTRIFF_RADAR_SOURCES` explicitly selects available adapters: `bluesky,news,exa,youtube,x`. Exa, YouTube and X require their own server credentials. Exa/X additionally require a positive maximum cost for a complete bounded source request (`POSTRIFF_RADAR_EXA_REQUEST_MICRO`, `POSTRIFF_RADAR_X_REQUEST_MICRO`) and `POSTRIFF_RADAR_PRICE_REVIEWED_AT` within 30 days. This is an operator-reviewed ceiling, not an invented current tariff. Configure the X ceiling for the maximum 40 returned posts. Source availability, current data rights, credential scopes, pricing and live responses still require operator validation.

The owner grants exact sources and public-evidence/approved-Genome AI access in Radar. Growth model routes require their existing separate consent. Quick reads at most 12 items/source, 4 judgments, 2 native presence checks and 1 angle; Deep reads at most 40 items/source, 10 judgments, 5 checks and 3 angles. AI attempt ceilings are reserved before dispatch; the shared router retains permission checks on every actual attempt. Ambiguous timeout/upstream outcomes stop retries and fallback for that attempt. Source requests do not retry or follow redirects. Each batch has a persisted lease and a 75-second fence; an expired/abandoned lease becomes unknown.

News discovery uses GDELT metadata, globally throttled to one request per five seconds. Exa returns at most 500 highlight characters per result. Bluesky supports bounded re-fetch of discovered native record IDs; an absent or edited record is removed from that run. Presence does not establish factual truth. No arbitrary URL-fetch tool or HTML scraper is exposed to the model. YouTube charts display native counts only, separately from AI and rankings. Threads, Instagram, RSS, Mastodon and Google Trends discovery remain unavailable pending provider-specific configuration/review.

## Evidence, ideas and retention

Lexical duplicates are folded before scoring. Scores are versioned ordering heuristics, not virality probabilities. New coverage is compared only with a recent run of the same topic and creator context. Source independence and causal impact remain unverified. For You uses only a current, approved, supported Genome statement with valid evidence bindings. Raw evidence is untrusted data; suspected instruction injection is excluded. Low confidence, unknown sensitivity and unavailable source coverage remain visible.

An idea requires a user review action. The existing Ideas source stores the topic, suggested question and reference links, marked `needsFactCheck`; no source claim becomes an approved fact, and no draft or publication job is silently created. Repeated save requests reuse the existing idea. Revoked source/AI permissions clear scan evidence and cancel affected runs; context changes fence stale actions. Short excerpts expire after 30 days. The existing authenticated minute cron runs retention even if discovery is subsequently switched off. Account/workspace deletion cascades database rows. A trusted `tombstone(source, native_id)` integration hook purges a removed source's affected scans; a production deletion-event collector is still required before broad source rollout.

## Costs and monitoring

The V3 Quick/Deep price proposal does not activate new plan terms. By default scans consume the operator-configured included growth allowance. `POSTRIFF_RADAR_CREDIT_BILLING=1` opts into the existing wallet and requires already active credit-policy terms and funded credits. Quote, reserve and settle are bound to the member, workspace and request. Fewer than three eligible useful opportunities refunds reserved scan credits. Unknown actual costs remain unknown and hold the wallet reservation for reconciliation; explicit cancellation refunds the customer, while provider usage remains in the attempt ledger. An unexpectedly high invoice never increases the confirmed customer quote. Provider spend details follow the existing owner-only Usage boundary. Customer-facing quote limits remain visible to the person reviewing a scan.

`POSTRIFF_RADAR_MONITORING=1` additionally allows owner opt-in on an active paid subscription. Default is off. It uses one Quick scan per local day, 08:00–22:00 in the chosen IANA time zone, with fresh owner/subscription/permission checks per batch. The existing cron advances one persisted batch per workspace per tick, bounded to ten workspaces and a 25-second dispatch window. Least-recently-checked workspaces rotate first, including after permission failures or quiet hours. A completed run may create one deduplicated in-app indication, subject to a two-per-day maximum. No email, push notification, social message or automatic publication is sent. Recurring credit-wallet spend is unavailable until specific recurring authorization exists; manual credit scans remain available.

## Validation and release gates

Local deterministic evidence verifies implementation behavior only. Real source precision, paid costs, publication impact and user adoption are not established. Release evaluation in `radar.core.release_gate` requires explicitly real data, unique scans with five relevance labels each, unique weekly users with draft outcomes, Precision@5 >= 0.6, weekly draft adoption >= 0.3, and every actual cost known and within its quote. Synthetic data cannot pass this gate. No live evidence was collected in this task.

Official adapter references checked during implementation:

- [Bluesky getPosts lexicon](https://github.com/bluesky-social/atproto/blob/main/lexicons/app/bsky/feed/getPosts.json)
- [Exa search contract](https://exa.ai/docs/reference/search)
- [YouTube videos.list](https://developers.google.com/youtube/v3/docs/videos/list)
- [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- [X recent search](https://docs.x.com/x-api/posts/search-recent-posts)

No data source or model is used for third-party model training.
