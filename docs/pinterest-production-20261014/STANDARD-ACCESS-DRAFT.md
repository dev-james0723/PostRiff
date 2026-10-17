# Standard Access application draft — DO NOT SUBMIT

App: Rafii, https://rafii.io, Pinterest app 1615884. Trial access was observed active in app1615884 developer console2026-10-17; no Standard application submitted. Standard status: **NOT RUN / no approval evidence**.

## Proposed description

Rafii helps creators and small businesses draft image Pins in their own brand voice. Customers connect their own eligible Pinterest accounts through Pinterest's official OAuth flow. Rafii reads identity and available publishing destinations, presents the image, title, description, HTTPS destination and board/section for review, and executes an approved publication immediately or at the customer's selected time. Customers can reconnect, cancel future work, pause automation and disconnect. Trial/Sandbox demonstrations are labeled and do not assert public visibility.

Identity consent: `user_accounts:read`. Image publication/reconciliation: `user_accounts:read,boards:read,pins:read,pins:write`. No boards:write, advertising, billing, private-resource scopes or password/cookie access. The hosted UI also offers a dedicated profile/boards consent path with only user_accounts:read and boards:read. The private read-only pilot cannot publish, read sections or obtain Pin scopes.

## Data handling to verify before final wording

Token exchange is server-side; access/refresh envelopes are encrypted in the tenant vault and bound to app/environment, with stable provider ID in the access envelope. Access/refresh tokens remain server-side. Authorization code/state transit the official browser callback and authenticated app completion; exclude them from logs, Agent context, recordings and evidence. Agent destination reads require an explicit current-turn request and connection-domain authorization; returned board data is untrusted input. Public candidate uses server-only rate counters with hashed app/account identifiers. Disconnect removes local credentials and stops future approval authority; Pinterest account settings must remove provider consent where no official revoke operation is available.

Policy/terms reachability was independently HTTP-checked at `https://rafii.io/privacy` and `https://rafii.io/terms`; see evidence/public-policy-reachability.json. Reachability does not certify policy substance. Review actual Pinterest-data retention, disconnect deletion, support process and AI/model handling against [Developer Guidelines](https://policy.pinterest.com/en/developer-guidelines) and [Developer/API Terms](https://policy.pinterest.com/en/developer-terms) before submission. No policy was edited or published.

Current guideline review found restrictions on API-data storage/sharing and visual imitation. The candidate now uses a Rafii-native review card and keeps Agent provider-data access behind a separate disabled permission gate. Exact retention and third-party/model processing need provider clarification. The official Terms article was unavailable through the inspected URLs; this package does not certify compliance or claim provider permission.

## Actual video and evidence checklist

No actual OAuth/application recording exists. Do not substitute the synthetic screenshots or gallery for a working demo. After approval of the exact test infrastructure, account and live-consent scope, record the actual environment accurately. The approved private Trial uses existing shared production hosting and the official API. Real code exchange and business identity read-back succeeded; Pinterest reused existing consent automatically, so there is no fresh consent-screen footage. A later explicit reconnect showed the actual official two-read-scope consent screen, awaiting human Give access. Local disconnect was verified after normal MFA. Boards/refresh/reconnect acceptance and recorded video remain incomplete. The initial read-only pilot cannot complete the Pin/section/scheduling parts below; those need later scoped approvals:

1. Rafii login and Connect Pinterest entry on the approved actual environment.
2. Official provider consent screen and exact registered redirect; protect account details.
3. Successful callback/server exchange and connected stable account ID (redacted display).
4. Actual boards/section discovery, with accurate eligibility errors.
5. Draft/review showing exact asset, metadata and destination.
6. Separately approved live API action; for a Pin, obtain its frozen action approval first.
7. Provider Pin ID, exact GET read-back and separately recorded visibility/tier.
8. Refresh/reconnect recovery, scheduling when authorized, and disconnect stopping future jobs.

Record environment, tier, source/deployment SHA, date and authorized account/workspace for each take. Hide tokens, codes, state, private boards and unrelated users. Present final recording and application fields to James before submission. Preserve the provider's actual pending/approved/rejected status; approval timeline remains unknown.

## Controlled Pin approval template — currently incomplete

Account/stable ID, Rafii tenant/connection, board and section/privacy, exact image/source/hash/MIME/bytes/rights/alt, title, description, HTTPS link, timing/time zone, access tier/host, visibility, exact `POST /v5/pins` payload, allowed read-back, and deletion/rollback proposal. These facts must be verified together before approval. No account/board/image has been chosen or approved for a real Pin.
