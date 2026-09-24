# Real-world checks (need James)

Everything below has external effects or needs James's own devices and accounts, so none of it was
run by an agent. Each item says what to do, what to look for, and what it proves. Stop at the first
surprise and note it; the local evidence already covers the same flows with synthetic providers.

## 1. Real phones (no external effects)

On an iPhone (Safari) and an Android phone (Chrome), signed in to production:

- Home: type an idea, open Channel Bloom, pick a folder, open the Content Library, change a language.
  Look for: text at 16px (no zoom on focus), bottom sheets that reach the screen edge, nothing cut off.
- Automations: New automation → go through all four steps with a template; Save as draft; then
  Cancel it. Look for: weekday and day buttons easy to hit, the time and date pickers native.

## 2. A real writer (costs money: keep the limit small)

- Home: draft one idea with a cloud writer. Check Account → Billing shows the charge.
- Automations: one automation with the same writer, a $0.10 limit and a time five minutes away.
  After it runs, check the run history shows the cost and the drafts read well. Cancel it.
- Proves: cost limits, recorded spend, and drafting quality with a real model.

## 3. Live accounts (OAuth; changes connected accounts)

- Connect a real Threads or LinkedIn account; add it to an automation; disconnect it; let the next run
  happen. Look for: "skipped: no longer connected" on that run, and no draft for that account.

## 4. Publishing (posts publicly)

- Approve and publish one real Threads post from a draft an automation prepared.
- A few days later (Threads insights arrive), check Analytics. With three or more comparable posts,
  a "Follow up a strong post" automation can start; its run shows the observation it used.

## 5. Email (sends mail)

- Needs a mail transport configured in production. Opt in to "Email me when its drafts are ready"
  on one automation and wait for a run. Look for exactly one email with a link to the drafts.

## Before any of this in production

Run the read-only migration check in `migrations-review.md`; Automations need migration 018.
