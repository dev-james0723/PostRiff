# Substack release gate

Status: engineering candidate, 2026-10-18. **NO-GO for full public official integration, authenticated Substack connection, private analytics or automatic publishing.**

RAFII_SUBSTACK_ENABLED defaults to 0. The flag only exposes the implemented public-feed/editorial/manual workflow; it does not create provider authority.

## Implemented

Existing hosted workspace transactions, role checks, audit and RLS back public-feed enrollment, consent, safe preview, local article/Note/media text drafts, exact-content review, a durable manual queue, stable handoff export, cancellation and deletion. Connections, Queue, Calendar and in-app-only due reminders share these records. Three bounded Agent tools can inspect and prepare local drafts but cannot approve or publish them.

## Verified engineering evidence

85 dedicated Python tests; the same 33 real disposable PostgreSQL cases on both 16.2 and upstream 17.6 with synthetic identity/provider data; 14 Connections and 4 Queue/Calendar Chromium scenarios; 12 frontend contract and 7 manual projection tests; full web TypeScript and named existing permission/notification/token regressions. One optional SDK-binding registry test was skipped. See the source tests and ../substack-security-core.md for the tested boundaries.

No production or live Substack authorization/publishing acceptance is claimed. Anonymous provider connectivity was not accepted in the execution environment. PostgreSQL validation covers upstream 16.2 and 17.6; it does not establish equivalence with the deployed Supabase build, extensions or migration state.

## Before a limited editorial release

- Pin and review the exact commit; prove the deployed artifact's source revision and preserve unrelated concurrent work.
- Verify the deployed network can fetch an allowed real public feed and that production-equivalent roles, isolation, retention and deletion behave correctly.
- Review applicable feed/commercial/data terms and precise customer-facing disclosure.
- Deploy with the flag off, known rollback artifact and no new provider credentials; approve an exact accepted surface before enabling it.

This limited release would not complete the full official integration goal.

## Before official provider modes

Obtain applicable Rafii commercial permission and real client/key registration, issuer/resource metadata, scopes, eligibility, publication-role binding, quotas, retention/AI limits and token lifecycle. Implement the provider's actual protocol, encrypted credentials, revoke/reconnect, operation-specific authorization and verifiable receipts. Validate with independent consenting customer tenants, including denial, revocation, role change, expiry, timeouts and duplicate prevention.

Substack's [MCP guide](https://support.substack.com/hc/en-us/articles/50834026608916-How-to-connect-Substack-to-your-AI-Assistant) describes eligible read-only publication access. [Developer API terms](https://substack.com/api-tos) do not provide a publishing/private-data grant. [Publisher API](https://substack.com/startups) is advertised, and an [official Notes partnership](https://on.substack.com/p/new-on-substack-creator-match-audience) exists; neither establishes this client's entitlement. Unofficial session/cookie APIs must remain excluded.

Rollback: disable RAFII_SUBSTACK_ENABLED and return to the previously accepted deployment. Preserve authored drafts. There is no new migration in this change.
