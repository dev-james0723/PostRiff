# Discord hourly ceiling: contract for the UI (owner decision, reply 16, 2026-10-28)

A workspace may have at most **300** approved, non-terminal Discord posts scheduled within any one hour. An approval that
would make the 301st is refused with a clear message instead of queued. Why: a hot workspace is served one post at a time;
measured on the hosted runner it sent 292 of 300 posts, and only 236 of 1,000 queued posts inside the one-hour approval window,
so the tail of a larger hour is held at expiry and the customer sees "approve again". This is admission control only: the lane,
the coordinator and the worker are unchanged.

Code: `src/postriff_phase2/discord/authorization.py` (`WORKSPACE_HOURLY_CEILING = 300`, `WORKSPACE_HOURLY_WINDOW_SECONDS = 3600`,
`WORKSPACE_HOURLY_CODE`, `assert_workspace_hourly_ceiling`). Tests: `tests/test_discord_hourly_ceiling.py` (offline) and the
real-lock race in `tests/phase2/postgres_discord_authorization.py`.

## The error

HTTP **409**, JSON body (every route renders it the same way):

```json
{"error": "This hour is full: a workspace can have at most 300 approved Discord posts scheduled within any one hour. Approve fewer posts in that hour, or spread them over more hours.",
 "code": "discord_workspace_hourly_ceiling", "limit": 300, "windowSeconds": 3600}
```

- Key the localized text on `code`. `limit` is the number to interpolate (do not hard-code 300; the owner may change it);
  `windowSeconds` is 3600. `error` is the English fallback for a locale that has no string yet.
- There is no `Retry-After` header and no `retryAfter` field, on purpose: waiting does not free a future hour. Do not show a
  countdown or an automatic retry. The person changes the plan.
- 409 (not 429) because it is a conflict with the workspace's own plan, not request throttling. Clients that auto-retry 429
  must not retry this.
- `web/src/lib/api/client.ts` `ApiError` keeps `status`, `code`, `message`, `requestId` and `nextAction`, not `limit` or
  `windowSeconds`; read them from the response body or hard-code the number in the locale string.

Suggested copy (English; three locales to follow): title "That hour is full"; body "A workspace can have at most {limit}
approved Discord posts in any one hour. Approve fewer posts in that hour, or spread them over more hours."; actions "Choose
another time" and "See the posts in that hour".

## Which actions can return it

| Action | Where | What the person sees | State after |
|---|---|---|---|
| Approve a prepared review (`p2_approve`) | the approve dialog | the error above | the review is still waiting; nothing changed |
| Approve up to 10 reviews (`p2_approve_many`) | bulk approve | the same error for the whole call | **all or nothing**: no post approved, no review changed. The response does not say which one crossed; keep the selection and let the person remove some |
| Approve an automation post (`raffi_run_decide`, decision "approve") | the run's post card | the same error | the post stays "Ready for review" |
| Queue commit of an approved automation post (`raffi_run_commit`, run by the scheduler 30 minutes before the publish time) | no direct request from the UI | the post card shows "It couldn't be queued: This hour is full: ..." after up to 3 attempts (a place can come free in between) | state "Failed" with the approved draft kept; the person approves it again for another hour |
| Approve a Discord reply (engagement) | the reply dialog | the same error | the reply review is still waiting |
| Move a post (cancel, prepare a new review, approve) | the Queue | the same error at the **approve** step | the old post is already cancelled (existing behaviour of a move); the review for the new time is still waiting. Moving a post inside an hour that is full works, because the cancel frees its place first |

Preparing a review (`p2_review`, or the reply preview) is not refused: it only drafts the approval. The site agent cannot
prepare or move a Discord post at all today (its proposal builds the review without a destination and Discord refuses that), so
it has no path to this error.

## What is counted

- The unit is the **scheduled time** (`manifest.timing.timestamp`), per workspace, across all servers, channels and members.
- The hour **slides**: no 60-minute window of scheduled time may hold more than 300. It is half-open: two posts exactly 60
  minutes apart do not share a window. Only windows that contain the new post are checked, so an hour that is already over the
  ceiling (queued before this rule) refuses new posts for that hour only and is not touched.
- Counted: Discord posts that are approved, scheduled, claimed or submitting, and an approved post that a preview deployment
  holds for dispatch. Not counted: sent (verified), failed, canceled, held (it needs a new approval, which must not be blocked by
  the old one), uncertain, and every other provider.
- An automation post a person approved but whose job is not made yet (it is made 30 minutes before the publish time) holds its
  place when a later automation post is approved, so the person is told at the click. Manual approvals count jobs only, not
  those reservations: the guarantee that no hour holds more than 300 posts is on jobs, at the moment a job is made. The
  consequence is rare and visible: if manual approvals fill an hour after an automation post was approved for it, that post is
  refused when it is queued (see the table) and its draft is kept.
