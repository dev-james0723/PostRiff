# Rafii Trend Stage 2 production activation — 2026-10-03

Owner approval: explicit production activation approval in the ChatGPT release session on 2026-10-03.

## Scope

Production project: `postriff-phase2-private` / Supabase `buoyhkbodnhzngaotoel`.
Initial rollout workspace: `267f7d90-b11c-470c-9880-733ea7c1d483`.
Acquisition operation: `bluesky:live_sample`, using the pinned Jetstream protocol and exact reviewed endpoint.
Cron remains bounded to the existing one-minute worker schedule; each source sample is separately bounded by the source policy.

## Enabled Stage 2 product surfaces

Trend Intelligence, Radar, Trust Receipts, provider operations, analytics retention, calibration, stage claims,
model enrichment, notifications, graph genome, saturation, whitespace, Opportunity Lab, multimodal analysis and
forecasts are enabled for the allowlisted workspace. Owned-post metric reads and history-import scheduling may be
enabled globally, but they remain fail-closed unless a connected account has the required native analytics rights.

## Source-use boundary

For the approved workspace scope, the live sample may be retrieved and used for raw/metric storage, display excerpts
and links, embeddings, bounded model analysis, metric derivation, cross-source combination and retained derivatives.
Raw retention is capped at 7 days. This approval does **not** grant third-party authors' rights that the owner does not
possess: `train_or_finetune` and `share_across_workspaces` remain denied. Any future shared-scope use or model training
requires a separate rights review.

## Cost and execution bounds

Bluesky live sampling is configured as `unmetered_live_bytes_bounded` with a zero-dollar acquisition reservation.
Model enrichment uses the existing production Vercel AI Gateway evaluation route and retains the runtime's hard
one-attempt / three-second / 8k-pack bounds. Production model enrichment is capped at USD 100 total for the 30-day
activation window, enforced independently at system, provider, and workspace budget dimensions. An individual model
attempt may reserve no more than USD 0.25.

The activation window is 30 days. Provider/source review and budget rows expire at the end of that window; renewal
must be a new immutable review record. The source schedule samples for 5 seconds every 5 minutes, up to 10,000 slots.

## Rollback

Set provider operations, model enrichment, notifications, multimodal analysis and owned-post metric/history reads off
first. If needed, disable Radar / Intelligence / Trust Receipts. Do not delete retained evidence as a rollback shortcut;
normal revocation and retention cleanup must continue.
