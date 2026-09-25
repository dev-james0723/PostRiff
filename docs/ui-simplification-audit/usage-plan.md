# Usage & plan — copy and information-density audit

Route: `/app/account/billing` · Source: `web/src/features/billing/*`

| Screen/component | Current copy (short) | Class | New copy / action |
|---|---|---|---|
| Page header | "What you have, what you have used, and what changes next." | REMOVE | Title only: **Usage & plan** |
| Plan card eyebrow | "Current plan" | REMOVE | Plan name is the heading: **Trial** |
| Plan card price (trial) | "$0 · no card on file · nothing converts automatically" | MOVE / REMOVE | "$0" moved to **Details**; "no card", "nothing converts" removed (info sidebar says "No card needed") |
| Plan card timeline | "10 days left · ends Oct 3, 2026" | COMPRESS | **10 days left**; exact end date only in Details |
| Plan card export | "Drafts stay exportable" / "Export status unavailable" | REMOVE | Removed. Export lives with the data (ledger CSV, workspace export) |
| Plan card footer | "Billing is not enabled on this deployment yet." | REMOVE | No button, no sentence |
| Plan card footer | "Payment method, invoices and cancellation appear here after your first subscription." | REMOVE | Nothing |
| Plan card footer | "Billing details are unavailable right now." | REMOVE | Nothing |
| Plan card footer | "Plan changes are made by the workspace owner." | MOVE | Once, in the Plans section: "Only the owner can change plans." |
| Plan card action | "Manage billing" | COMPRESS | **Manage plan** (portal) / **Choose a plan** (trial with checkout) / none |
| Lifecycle alert (separate panel) | "Trial ended on …", "Payment failed … Update the payment method in the billing portal before then.", "Your subscription ends … It will not renew. Changes to it are made in the billing portal." | MOVE + COMPRESS | Folded into the plan summary: **Trial · Ended · Publishing is paused · Choose a plan**; **Studio · Payment failed · Update payment by Oct 3 · Update payment** (announced as alert); **Studio · Ends Oct 3 · won't renew · Manage plan** |
| Lifecycle alert | "Drafts remain readable and exportable; choose a plan to resume publishing." | REMOVE | Removed from default; cancellation info in the info sidebar |
| Allowances header | eyebrow "This period" + "Allowances" + "No reset during the trial · ends Oct 3, 2026" | COMPRESS | **Usage**; "Resets <date>" only when a paid plan renews |
| Meter reading | "Not included in this plan" / "12 · plan total unavailable" | COMPRESS | "Not included" / "12" |
| Storage row | "500 MB included · usage is not measured yet" | COMPRESS | "500 MB" |
| Over-limit notes | "Above this plan's 3. Remove an account or change plan before connecting another." | COMPRESS | "Over your plan's 3. Remove one to connect another." + Channels link |
| Cost guard | "Model spend this month … Reserved $x · Provisional ceiling. Requests are refused before the ceiling would be crossed, never charged after." | COMPRESS (money kept) | "AI spend this month $x of $y" + bar + "Pauses at $y. Never charged over." / "Limit reached. Drafting is paused." Reserved amount stays in the bar's accessible value |
| Overage footnote | "When an allowance runs out, paid drafting stops and tells you. Nothing is charged silently." | MOVE | InfoTip beside **Usage** |
| Plans subtitle | "Checkout is not enabled on this deployment yet." | REMOVE | Nothing |
| Plans subtitle | "Checkout and invoices are handled by Stripe. Nothing is charged until you confirm there." | COMPRESS (money kept) | "Checkout by Stripe. Nothing is charged until you confirm." (owner, checkout available only) |
| Plans empty | "No plans are published on this deployment yet." | REMOVE | Section hidden |
| Plan card footers | "This is your current plan." / "Not yet available for purchase." / "Ask the workspace owner…" / "Switch plans from the billing portal." | REMOVE / COMPRESS | Current = badge only; unavailable = no footer; owner note once per section; "Switch in Manage plan" |
| Checkout return | "Waiting for the payment provider to confirm" + "This page checks again on its own, less often as time passes." | COMPRESS | "Confirming payment…" |
| Checkout return | "Your plan and allowances below are updated." | REMOVE | "Subscription confirmed" alone |
| Checkout return | "Still waiting for the payment provider" + "Refresh in a minute; nothing else is needed from you." | COMPRESS | "Still confirming payment" + "Refresh in a minute." |
| Checkout cancelled | "Checkout cancelled. Nothing was charged." | KEEP | Money |
| Ledger header | "Each run reserves an estimate, then settles to the real cost or is released if it failed." | MOVE | InfoTip beside **Recent usage** |
| Ledger empty | "No usage yet" + paragraph | COMPRESS | **No usage yet** + Start an idea |
| Ledger export | "Export 45 rows (CSV)" | COMPRESS | **Export CSV** (row count kept for screen readers) |
| Ledger footer | "Showing 20 of 45 · the workspace lists its latest 45 entries here (up to 100)" | COMPRESS | "20 of 45" only while truncated |
| Ledger filter empty | "No writing entries among the latest 45." | COMPRESS | "No writing usage" |
| Non-owner ledger | Heading + "Run-by-run costs are shown to the workspace owner." | REMOVE | Section not rendered for non-owners |
| Load error | "Usage could not be loaded" + "The workspace did not answer." + Retry | COMPRESS | **Couldn't load usage** · "Check your connection and try again." · Try again |
| Info sidebar | Four paragraphs ("How billing works") | COMPRESS | Four one-line facts (no overage charges, trial needs no card, drafts stay after cancelling, what a batch is) |

## Structural changes

- The three-column "plan card + allowances card" grid became one **plan summary** row (name, one line, one action) above one **Usage** section. The separate lifecycle alert panel is gone: its states live in the summary, so the same date is never shown twice.
- Heading levels are now h1 page → h2 sections (plan, Usage, Plans, Recent usage) → h3 plan cards (was h2/h3/h4 mixed).
- Meters sit in a two-column grid on wider screens instead of a tall single column; the cost guard lost its nested glass box and spans the grid.
- Sections that could only apologise (non-owner ledger, empty plan list) are not rendered.
- Loading skeleton matches the new, shorter page.

## Default state (trial, billing not set up)

Before: Current plan / Trial [Trial] / $0 · no card on file · nothing converts automatically / 10 days left · ends Oct 3, 2026 / Drafts stay exportable / Billing is not enabled on this deployment yet.

After: **Trial** / 10 days left / Details ▸
