# Rafii Context Navigation

## Scope and data contract

The workspace chat and Rafii panel continue to share `pr_conversations` and `pr_messages`. Existing `GET .../messages?cursor=` remains unchanged for callers. The conversation page uses a bounded window around the latest or a linked UUID, with older pages loaded on demand. No full conversation is downloaded to navigate a long thread.

| Route under `/api/workspaces/{workspaceId}/ideas/conversations` | Contract |
| --- | --- |
| `GET /navigation?cursor=&limit=` | Keyset page ordered by `(updated_at,id)`; title, 180-character latest meaningful excerpt, count, archived state, and `nextCursor`. Limit 1–60. |
| `GET /search?q=` | Up to 15 title and 30 turn matches scoped to the current workspace. Excerpt max 180 characters; no full bodies. Trigram GIN indexes support substrings and Chinese. |
| `GET /{id}/navigation?cursor=&limit=` | Sequence cursor page (max 200) of minimal marker metadata, total message count, and saved Moment markers. |
| `GET /{id}/window?anchor=&before=` | At most 100 full messages plus associated Moments. `anchor` accepts an exact message or Moment UUID, including one outside the first loaded page. `before` loads older turns. |
| `POST /{id}/moments` | Editor or higher; validates a ready video asset in the same workspace and a finite in-range timestamp, saves a durable Moment, and returns it. No publication. |

All routes pass through the existing verified workspace transaction. Conversation and message predicates include `workspace_id`. IDs from another workspace and missing IDs have the same unavailable behavior at the conversation boundary. Migration `041_context_navigation.sql` adds indexes and `pr_media_moments`; direct authenticated reads have workspace RLS, while writes remain service-role only. Migration 041 must be applied before the new routes are served in production.

## Thread map and search

Marker taxonomy: user request, Rafii response/decision, approval required, draft/artifact, media, research, automation, completion when an explicit completed status exists, error/blocker, and saved Moment. Classification uses stored message fields; it does not generate summaries. The rail caps visual density at 36 clusters while every exact turn remains available in the expanded cluster. The mobile control opens the existing Sheet primitive, with groups expanded on demand. Message visibility follows `IntersectionObserver`. Activating a marker sets `?turn=<uuid>` and opens the relevant message window, so reloads and shared links resolve the same turn. Reduced-motion preference controls jump scrolling. The KBar command palette queries the same backend search contract.

Conversation previews use the latest nonempty stored message excerpt, timestamp, archived state, and exact message count. They do not infer activity or summarise with AI.

## Now Playing and Moments

`useNowPlaying` is the single Rafii-owned playback state. A single `<video>` in the app shell continues across app routes; composer and Library video previews open this player, preventing duplicate streams. The compact bar exposes title/source, play/pause, progress, seek, expand, close, and Save moment. Browser Media Session metadata, play/pause and valid seek handlers/position state are guarded feature-by-feature. Unsupported browsers keep the in-app controls. Changing workspace clears playback. Asset playback URLs are fetched at user action time, not cached as persistent blob URLs.

A saved Moment stores source `rafii_asset`, workspace and conversation, validated asset UUID, title, seconds, human timestamp, creator, creation time and the adjacent message sequence. Its card can reopen playback at the saved second. “Ask Rafii” and “Make content” put context into the existing composer and attach the same Library video as a reference when attachment capability is enabled. Sending remains the user's action through the existing turn/consent/credit path. Saving a Moment never sends a turn, creates a draft, schedules or publishes.

Spotify playback state is absent from the current OAuth scopes and connector capability model, so no Spotify playback adapter is shipped. Any later adapter needs user re-consent for the official playback-state scope and capability checks. MusicKit public infrastructure is absent. The Electron shell has no supported provider-specific media bridge. Rafii does not claim to observe universal macOS/device media or private OS Now Playing APIs. Library playback without a selected conversation can play globally but cannot save a conversation Moment.

## Accessibility and verification

Markers, clusters, prev/next controls, sheet rows, player controls, and seek have labels and keyboard activation. Preview context is visible on focus as well as hover. Mobile receives a compact navigator rather than a squeezed rail. The rail reserves space in the thread and the Now Playing bar sits above the mobile tab bar, away from the composer. No automatic publication follows any navigation or save action.

Verification matrix: disposable PostgreSQL checks 1,101-turn pagination, many-conversation keysets, multilingual search, exact deep links, workspace isolation, viewer denial and Moment persistence; Node tests cluster identity and player/Media Session fallback; web typecheck, lint, production build and existing suites guard integration; local Playwright exercises laptop and iPhone viewports, long-thread jump, sheet, keyboard, reduced motion, player and Moment; live smoke separately checks deployed commit and reachable desktop/mobile behavior. Synthetic identity/media and local fixtures are labelled as such in the release receipt.
