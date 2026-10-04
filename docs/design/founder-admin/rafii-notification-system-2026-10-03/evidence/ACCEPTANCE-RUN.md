# Rafii Notification System acceptance run

Historical implementation run for `6a93656829beb392ac9ba674e8ca9617e8a85cbb`. The later integrated release run and its green Founder sweep are recorded in [RELEASE-ACCEPTANCE-RUN.md](RELEASE-ACCEPTANCE-RUN.md). This report's source hash refers to [SOURCE-MANIFEST-IMPLEMENTATION.sha256](SOURCE-MANIFEST-IMPLEMENTATION.sha256).

Date: 2026-10-03/04 UTC.
Execution: isolated local implementation worktree; disposable PostgreSQL and synthetic identities; no deployment or real provider dispatch.

## Source boundary

- Implementation branch: `codex/rafii-notification-system-20261003`.
- Canonical base selected before editing: `ead739245c09d9517cd5232ab2e430168433f01a` (`origin/consumer-saas`, merged PR #95 lineage at execution time).
- The seven required files in the supplied package were read, and `MANIFEST.sha256` passed 7/7 **before product edits**. The copied package's manifest still passes 7/7.
- `SOURCE-MANIFEST-IMPLEMENTATION.sha256` covers 32 product, fixture, test and configuration files for this historical run. Its SHA-256 is `c00d6eafc8bbce2e50e1c029ca2f3ac30ef2423114bd8265c1b1834b882170d9`. It passed 32/32 on the implementation commit with `LC_ALL=C LANG=C`.
- Final commit identity is recorded in the local `RELEASE-RECEIPT.md` created after the implementation commit and in the final task response.

## Implemented behavior and evidence

- Reuses the existing Motion notification stack, bell, card, attention, server and Founder notice contracts. The center sorts by severity/actionability and dedupes only on explicit stable source identity. The visible stack is bounded to three layers. See [presentation test](../../../../../web/tests/rafii-notification-presentation.test.cjs) and [browser result](system-browser/browser.json).
- The Live Pill follows actual agent run state; waiting human input is promoted through existing durable attention/notification data. Sonner handles lightweight local mutation feedback. Existing notification delivery history supplies the Activity Feed. The feed contains durable notification events, including emitted task completion events; it does not fabricate records for run types that have no notification event.
- Read and archive remain separate server-confirmed actions. A failed read stays available, and the SQL-backed notification is unchanged until a successful retry. Links use the existing safe app-route validators. The informational archive history and equal-timestamp cursor cases pass disposable PostgreSQL tests.
- Founder email, push, quiet hours and digest policy contracts remain unchanged. Founder notices use their existing read endpoint; Demo mode does not request a nonexistent notice stream.
- No database migration was needed. Existing delivery status and history represent read, dismissed and durable history states.
- Visual review covers desktop light 0/1/3, desktop dark 4, expanded cards, action-required with Review plus confirmed Mark read, security, partial source, mobile 375 px, Live running/waiting/success and reduced motion. The dev-only visual fixture is labeled synthetic and returns HTTP 404 in the production build. Its screenshots exclude only the Next development toolbar.

## Checks on this source

| Check | Result |
|---|---|
| `POSTRIFF_API_ORIGIN=http://127.0.0.1:4337 npm run build` | PASS, including Next TypeScript compilation. |
| `npm run typecheck` | PASS. |
| `npm run lint` | PASS, 0 errors; 2 existing warnings in unrelated `thread-navigator.tsx` and `contact-policy.ts`. |
| `node --test tests/rafii-notification-presentation.test.cjs tests/founder-nav.test.cjs tests/founder-comms.test.cjs tests/founder-pages.test.cjs tests/coworker-deeplink.test.mjs` | PASS, 52/52. |
| `PYTHONPATH=src:tests /tmp/rafii-notification-20261003-env/bin/python -m unittest discover -s tests/control -p 'test_founder_notifications.py' -v` | PASS, 22/22; same backend source and fixture configuration. |
| `/tmp/rafii-notification-20261003-env/bin/python scripts/rafii_control_pg.py --pattern test_founder_notifications_pg.py` | PASS, 3/3 on disposable PostgreSQL; same backend source. |
| `/tmp/rafii-notification-20261003-env/bin/python scripts/rafii_pg_private.py postgres_unified_notifications` | PASS on a fresh disposable PostgreSQL database; same backend source. |
| `node tests/rafii-notification-system-browser.cjs` | PASS: Chromium actual UI/API/SQL failure/retry, priority, history, partial source; WebKit 375 px touch/keyboard/axe; synthetic visual states. [Machine result](system-browser/browser.json). |
| `RAFII_WEB_URL=http://localhost:3397 RAFII_PYTHON=/tmp/rafii-notification-20261003-env/bin/python RAFII_HARNESS_PG_PORT=55437 RAFII_NOTIFICATION_EVIDENCE_DIR=../docs/design/founder-admin/rafii-notification-system-2026-10-03/evidence/existing-browser node tests/unified-notifications-browser.cjs` | PASS: Chromium and WebKit, desktop/mobile, light/dark, axe, fake phone/push/SMS, zero real calls. [Machine result](existing-browser/browser.json). |
| `node tests/rafii-founder-notification-browser.cjs` | PASS: real local Founder notice, touch expansion, confirmed read, Demo separation/no Demo header notice request, axe. [Machine result](founder-notification-browser/browser.json). |
| Existing `node tests/founder-browser.cjs` full 1440/768/390 sweep | **1064/1068 PASS; 4 FAIL.** At 390 px, unrelated Demo overview returned one HTTP 500 and Demo workspace query returned one HTTP 503; each also caused its paired console-error assertion. All notification-specific and other sweep checks passed. A fresh-browser replay of those two Demo routes had no failed requests, while a separate 390-only sweep under host load still saw other transient Demo 500/503 responses. [Exact failures](founder-browser/founder-browser.json). This broad regression gate is **not green**. |
| Production fixture route `/dev/notification-system` | HTTP 404, PASS. |

### Visual evidence

- [Actual desktop 3-card collapsed](system-browser/desktop.light.collapsed.3.png), [actual expanded](system-browser/desktop.light.expanded.3.png), [actual WebKit 375 px expanded](system-browser/mobile.webkit.expanded.375.png), [actual partial source](system-browser/desktop.partial-source.png), [actual failed action](system-browser/desktop.failed-action.png).
- [Synthetic dark stack](system-browser/visual.desktop.dark.collapsed.4.png), [two-action card](system-browser/visual.action-required.two-actions.png), [security card](system-browser/visual.critical-security.png), [reduced motion](system-browser/visual.reduced-motion.png), [Live running](system-browser/visual.live.running.png), [waiting](system-browser/visual.live.waiting.png), [success](system-browser/visual.live.success.png), [mobile layout](system-browser/visual.mobile.375.expanded.png).
- [Founder mobile expanded](founder-notification-browser/founder.mobile.live.expanded.png), [read confirmed](founder-notification-browser/founder.mobile.read-confirmed.png), [Demo separation](founder-notification-browser/founder.mobile.demo.png).
- Remaining required 0/1 desktop and visual partial screenshots, plus existing notification and Founder shell screenshots, are in the corresponding evidence directories.

## Release boundary

This is a committed local implementation candidate. The full Founder shell regression gate remains open at 1064/1068; its two intermittent Demo requests need a stable fixture/host rerun before a green release claim. No real email, push, SMS, phone call, paid model/provider action, PR merge, or deployment was performed. Existing Founder/Pricing worktrees were not reset, stashed, cleaned, overwritten or edited.
