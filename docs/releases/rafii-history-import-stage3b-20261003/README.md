# Rafii Stage 3B History Import release

Channels now has a consent-first History Import review/request/status panel and accurate analytics capability/disconnect copy, behind the existing server gate. Production is explicitly configured with **`POSTRIFF_HISTORY_IMPORT=0`**. Activation is a separate procedure in [ACTIVATION_CHECKLIST.md](ACTIVATION_CHECKLIST.md).

The feature reads connected Threads/Instagram accounts' own historical metadata and available current analytics. It preserves Direct analytics eligibility, interactive `manage_connections`, five requests/hour, one active run, bounded retries, opaque pagination, atomic progress and disconnect purge fencing. It enforces 25 entries/page, 12 pages/300 posts/run and the request-time 90-day window even with provider overdelivery. Caption text and hashes are never retained. Metadata completion and analytics completion are displayed separately. Uncertain POSTs reconcile with GET without automatic repeats.

Copy follows all ten Rafii display preferences: English variants, Traditional/Simplified Chinese, Japanese, Korean, French, German, Spanish and Brazilian Portuguese. Traditional Chinese includes HK/TW variants; other content-language locales explicitly fall back to English. Locale tests check every new consent/status/error key and matching placeholders/bounds.

## Validation scope

- Backend unit/WSGI: exact default-OFF gates, strict consent, sanitized metadata, request/status separation and 202 semantics.
- Disposable PostgreSQL: permission/tenancy, API tokens, Direct eligibility, throttle/deduplication/audit, hard pagination/window bounds, retries, revocation, late-write fencing, delayed purge recovery and preservation of Rafii-published data.
- Actual Channels browser/API/DB: unchecked consent, real 202/429/403 responses, retry/partial/purge status, viewers, lost-response reconciliation, unavailable/loading recovery, saved HK locale, mobile/keyboard/axe and actual disconnect. Provider responses/status seeds are synthetic; OFF and network faults are explicitly injected.
- CI discovers unit/PG suites and runs `python scripts/consumer_ready_browser.py --history-import` against the isolated production build.

The release receipt records final commands/counts, source/merge/deployment identifiers and the observed OFF response. This release performs no production history request, provider canary, migration or activation.
