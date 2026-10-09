# Rafii Notification System integrated release acceptance

Date: 2026-10-04 UTC. Source: `codex/rafii-notification-release-20261003`, based on canonical `origin/consumer-saas` commit `7156703b3725156c6041b059040007ab2ea63fab` with implementation commit `6a93656829beb392ac9ba674e8ca9617e8a85cbb` applied. Final integrated commit is recorded in the release receipt. This is a local acceptance run against a production build, a disposable PostgreSQL database, synthetic accounts and fake transports. It is not a live-provider test.

## Source boundary

- The supplied package `MANIFEST.sha256` passed 7/7, including both visual files, before product code changed in the original isolated worktree and again on this integrated tree.
- [SOURCE-MANIFEST.sha256](SOURCE-MANIFEST.sha256) covers the 32 product, fixture, test and configuration files in this integrated release; its SHA-256 is `5a6fa78b8ad4cb11dddbb0970cfb3610ec6abb28a854032a43173c25aebee348`. Every listed file passed SHA-256 verification on this tree.
- The original implementation evidence and its earlier 1064/1068 regression result remain in [ACCEPTANCE-RUN.md](ACCEPTANCE-RUN.md), with its original source list in [SOURCE-MANIFEST-IMPLEMENTATION.sha256](SOURCE-MANIFEST-IMPLEMENTATION.sha256). The integrated run below supersedes that release gate, while retaining its historical result.
- No migration was added. Existing notification delivery status and history represent the required durable states.

## Integrated validation

| Check | Result |
|---|---|
| `POSTRIFF_API_ORIGIN=http://127.0.0.1:4338 npm run build` | PASS, including Next TypeScript compilation. The dev-only notification fixture returned HTTP 404 in this build. |
| `npm run typecheck` | PASS; [log](release-checks/typecheck.log). |
| `npm run lint` | PASS, 0 errors and 2 existing unrelated warnings; [log](release-checks/lint.log). |
| Notification adapter, Founder navigation/comms/pages, coworker deep link and Rafii thinking-orbs Node tests | PASS, 60/60; [log](release-checks/web-unit.log). |
| Founder notification policy unit tests | PASS, 22/22; [log](release-checks/founder-policy.log). |
| Founder notification PostgreSQL tests | PASS, 3/3; [log](release-checks/founder-policy-pg.log). |
| Unified notification PostgreSQL tests | PASS on fresh disposable PostgreSQL, real SMS 0; [log](release-checks/unified-notifications-pg.log). |
| Full Founder 1440/768/390 browser regression | PASS, **1072/1072**, failures 0; [machine result](release-founder-browser/founder-browser.json) and [run log](release-founder-browser/run.log). |
| New notification browser acceptance | PASS: Chromium actual UI/API/SQL action failure and retry, priority, history and partial data; WebKit 375 px touch, keyboard and axe; synthetic visual states. Provider calls 0. [Machine result](release-system-browser/browser.json). |
| Existing unified notification browser regression | PASS: Chromium/WebKit desktop and mobile light/dark, accessibility, fake phone/push/SMS, real SMS and calls 0. [Machine result](release-existing-browser/browser.json). |
| Founder notification browser acceptance | PASS: real local in-app notice, 390 px touch expansion, confirmed read, Demo separation and axe. Email/push not sent. [Machine result](release-founder-notification-browser/browser.json). |
| Browser script syntax and diff whitespace | PASS. |

The first integrated Founder sweep stopped at 4/14 because its fresh harness initially allowed the backend port but not the new web origin. That local configuration was corrected and the full 1072/1072 sweep above ran against a fresh PostgreSQL instance. Its partial output is retained locally but excluded from release evidence.

## Visual evidence from this source

- Actual interaction: [desktop three-card collapsed](release-system-browser/desktop.light.collapsed.3.png), [desktop expanded](release-system-browser/desktop.light.expanded.3.png), [WebKit mobile expanded at 375 px](release-system-browser/mobile.webkit.expanded.375.png), [partial source](release-system-browser/desktop.partial-source.png), [failed action](release-system-browser/desktop.failed-action.png).
- Clearly labeled synthetic component fixture: [zero](release-system-browser/desktop.light.collapsed.0.png), [one](release-system-browser/desktop.light.collapsed.1.png), [dark stack depth](release-system-browser/visual.desktop.dark.collapsed.4.png), [two direct actions](release-system-browser/visual.action-required.two-actions.png), [critical security](release-system-browser/visual.critical-security.png), [reduced motion](release-system-browser/visual.reduced-motion.png), [Live running](release-system-browser/visual.live.running.png), [waiting](release-system-browser/visual.live.waiting.png), [success](release-system-browser/visual.live.success.png), [mobile layout](release-system-browser/visual.mobile.375.expanded.png).
- Founder: [390 px expanded notice](release-founder-notification-browser/founder.mobile.live.expanded.png), [confirmed read](release-founder-notification-browser/founder.mobile.read-confirmed.png), [Demo separation](release-founder-notification-browser/founder.mobile.demo.png). Existing notification settings include [WebKit mobile dark](release-existing-browser/webkit.dark.375.settings.png) and [desktop light](release-existing-browser/chromium.light.1280.settings.png).

All release screenshots above were captured against this integrated tree. The synthetic fixture is visibly labeled and makes zero provider calls. Existing Founder/Pricing worktrees were not reset, stashed, cleaned, overwritten or edited.
