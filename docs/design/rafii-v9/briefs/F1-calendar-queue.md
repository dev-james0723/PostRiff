# Stream F1 — Calendar and Queue (Review & Publish)

Common brief: `F-page-migration-common.md`. Recipes: DNA §21.3 (Calendar/Agenda) and §21.4 (Queue / Review & Publish); prompt §10 table rows "Calendar/agenda" and "Queue/review/publishing".

Files: `web/src/features/calendar/**`, `web/src/components/application/calendar/**` (the calendar grid components: restyle cells/events quietly, keep behaviour), `web/src/features/queue/**`, `web/src/app/app/calendar/page.tsx`, `web/src/app/app/queue/page.tsx`. Keep `keyboard shortcuts`, event popovers with `ManifestPreview`, timezone handling, rescheduling safety (moving a scheduled item never publishes; drag has a button alternative), the schedule dialog chain, receipts, held/uncertain job categories, batch selection bar only while a selection exists, separate approve/schedule/cancel actions, filters and counts on state tabs (real counts only).
