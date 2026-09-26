# Meta App Review package: Instagram and Threads insights and comments

Prepared 2026-09-25 for decision D6 of the growth-intelligence plan (v3, approved). Submission is an outward-facing action on James's Meta developer account, so James submits it; nothing here has been sent. Before submitting, check every field against the live App Review form, because Meta changes wording and requirements without notice.

## Why Rafii needs these permissions

Rafii's analytics capability for Instagram and Threads stays `Unsupported` until the app passes production review (`src/postriff_phase2/oauth.py`, capability matrix). Until then only accounts with a role on the app (James, testers) can use Creator Genome, post-mortems and Audience Miner. Review unlocks them for every creator who connects an account.

| Platform | Permission | Already requested by Rafii | What Rafii does with it |
|---|---|---|---|
| Instagram | `instagram_business_basic` | Yes | Identify the connected professional account |
| Instagram | `instagram_business_manage_insights` | Yes | Read reach, views, likes, comments, saves and shares for the creator's own posts, including posts from the last 90 days, to build their Creator Genome and post-mortems |
| Instagram | `instagram_business_manage_comments` | Yes | Read comments on the creator's own posts so Audience Miner can group recurring questions and requests; replies are only ever posted after the creator approves the exact text |
| Threads | `threads_basic` | Yes | Identify the connected profile |
| Threads | `threads_manage_insights` | Yes | Read views, likes, replies, reposts, quotes and shares for the creator's own posts, including the last 90 days |
| Threads | `threads_read_replies` | Yes | Read replies to the creator's own posts for Audience Miner |

Rafii does not request keyword search, hashtag search or any permission to read other people's content in this submission. Those belong to a later phase and a separate review.

## Use-case text (paste per permission, adjust to the form)

**instagram_business_manage_insights / threads_manage_insights.** Rafii is an AI assistant that helps creators and small businesses plan and write their own social posts. With the creator's permission, Rafii reads performance metrics for the creator's own posts, including posts from the last 90 days, and compares each post with the creator's own typical results at 1 hour, 24 hours and 7 days. The creator sees which topics, formats and openings work best for their audience (their "Creator Genome") and a short review after each post. Metrics are shown only to members of the creator's workspace, are never sold or shared, and are deleted when the creator disconnects the account or deletes their Rafii account.

**instagram_business_manage_comments / threads_read_replies.** Rafii reads comments and replies on the creator's own posts and groups them into recurring questions, requests and objections, so the creator can decide what to post next. Commenter names are not shown in the summaries; the creator can open the original comments in the app. Rafii never posts, likes or hides comments on its own; any reply is drafted for the creator and published only after they approve the exact text.

## Screencast script (one video per permission group, about 90 seconds each)

1. Sign in to Rafii with the review test account.
2. Open Channels, choose Connect Instagram (or Threads), and show the Meta consent screen listing the permissions.
3. Return to Rafii and open Brand → Creator Genome. Show the import of recent posts and the metrics table for each post.
4. Open one post's review card and show the 1 hour, 24 hour and 7 day readings compared with the creator's own median.
5. For comments: open Inbox → Audience Miner, show the grouped questions and requests, open one group to show the original comments, and show that a reply requires an explicit approval step.
6. Open Settings → Privacy and show disconnect and data deletion.

The Genome and Audience Miner screens are Phase 1 and Phase 2 work. Record the screencast only after those screens exist on a preview deployment; do not submit a video of mock-ups.

## Data handling answers

| Question | Answer |
|---|---|
| Where is data stored? | Rafii's PostgreSQL database (Supabase), in the workspace that connected the account, protected by row-level security |
| Who can see it? | Members of that workspace only |
| Is it shared with third parties? | Post text may be sent to AI model providers through Vercel AI Gateway with zero data retention enabled, only to analyse the creator's own content; metrics are not sold or shared |
| Retention | Kept while the account stays connected; deleted on disconnect, on request, or with the Rafii account |
| Data deletion | In-app disconnect and account deletion; data deletion instructions URL: fill in the production URL before submitting |
| Training | Not used to train any model |

## Items James must supply at submission

- Business verification status and the app's privacy policy URL, terms URL and data deletion URL on the production domain.
- A review test account with a connected Instagram professional account and a Threads profile that have real posts.
- The final screencasts described above.

## Consent copy change shipped in this phase

The analytics explanation shown when connecting now covers past posts, because Creator Genome reads the last 90 days. The explanation lives with the provider definitions (`EXPLAIN` in `src/postriff_phase2/providers.py`).
