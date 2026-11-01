# Rafii Twitch developer app and commercial review

**DRAFT — NOT SUBMITTED. No Twitch app has been created by this work. No secret has been generated or collected.**

## App worksheet

| Field | Prepared value or required verification |
| --- | --- |
| Product | Rafii |
| Product URL | `https://rafii.io` |
| Proposed app name | Rafii; Twitch uniqueness must be checked in the console |
| App ownership | Company-controlled Twitch developer account selected by James |
| Client type | Confidential server application; never expose the Client Secret in frontend code |
| OAuth callback | `https://rafii.io/api/oauth/twitch/callback` exactly |
| Callback current state | Production returned 404; candidate route is implemented and tested offline |
| Category | Select the console's current category matching creator/account management; confirm the exact offered label at registration |
| Initial scope | Identity with no optional Twitch scope; progressively request only the selected action's documented scopes |
| Identity verification | `/oauth2/validate` plus authenticated Helix `/users`, with Client ID and subject binding |
| Privacy / deletion pages | Confirm actual public URLs and Twitch-specific disclosure before submission; do not invent working routes |
| Client secret destination | Approved server secret store as `POSTRIFF_OAUTH_TWITCH_CLIENT_SECRET`; value never in Git, chat or documents |
| Release controls | Four separate default-off flags in `.env.example` |

Registration follows the [official app-registration guide](https://dev.twitch.tv/docs/authentication/register-app/). Twitch may require verified email, two-factor authentication and CAPTCHA. James should complete secure login in the browser once the concrete registration step is ready. The OAuth adapter does not invent PKCE support or request `openid`/email merely to identify a Twitch user.

The [official token-validation guidance](https://dev.twitch.tv/docs/authentication/validate-tokens/) requires validation at startup and at least hourly. Per-use checks supplement, rather than replace, the durable idle-connection sweep. Production sweep capacity has not yet been proven.

## Data, retention and purpose proposal

| Data | Candidate behavior | Requested authorization / outstanding work |
| --- | --- | --- |
| OAuth credentials | Server-side encrypted custody; no browser/Agent secret access; validation and rotating refresh | Confirm app custody and user-facing privacy disclosures |
| Account/live facts | Minimum source-backed context cached briefly; no deprecated profile view count | Confirm allowed creator-management use and disclosures |
| Exact action drafts/receipts | Actor/tenant/generation-bound encrypted payloads, narrow audit metadata; completed raw content purged on bounded retention | Confirm action audit and retention purposes; deployed erasure verification remains pending |
| EventSub viewer content | Separate storage gate; encrypted at rest; 24-hour maximum TTL; no generic Agent context; immediate purge path on revoke or scope loss | Request written authorization and approved retention; do not infer third-party sharing from a cache exception |
| Official clip URLs | Per-action rights assertion and ownership checks; transient human delivery; no automatic media download | Confirm download, storage and explicitly authorized cross-platform reuse rights |
| AI assistance | Separate purpose flag; minimal numeric facts and human-directed draft proposals; no approval or secret tools | Name actual model providers/subprocessors, retention and training arrangements; request written confirmation |
| Monetization | Only official reads/actions with required scopes and current eligible broadcaster state | Twitch account/app approval is still required; no purchase or arbitrary points-grant API is fabricated |

The API token does not grant copyright in third-party music or video, commercial marketing authorization or permission to share viewer content with a model provider. The current default-off controls reflect that distinction.

The current [Twitch Developer Services Agreement](https://legal.twitch.com/en/legal/developer-agreement/) was verified from indexed official English text, which reports a 2024-12-04 modification; direct retrieval returned a navigation shell. Schedule 1.B and 1.C are particularly relevant to marketing/campaign analysis, publication preview, permission minimization, storage and deletion. Rafii's intended commercial marketing role should be reviewed under those provisions. This engineering record is not legal approval or a claim that Twitch has accepted the product.

## Formal request ready for review

**Recipient:** verified official Twitch developer/business review channel, to be selected before sending.

**Subject:** Commercial API and partnership authorization request — Rafii public multi-tenant Twitch integration

Hello Twitch Developer Relations team,

Rafii, available at https://rafii.io, is preparing an opt-in public Twitch integration for independent broadcasters and their authorized workspace teams. Our goal is to offer paid creator-management and marketing workflows using only documented Twitch APIs, with each consequential account operation separately approved by the connected user.

We request guidance on the separate agreement and approval process applicable to this use, including Schedule 1.B and Schedule 1.C of the Twitch Developer Services Agreement. The product would support channel information, native stream schedules, live chat and moderation, clips and permitted VOD actions, polls, predictions, raids, custom rewards, eligible subscriptions/Bits/ads functions, EventSub notifications and source-attributed metrics. We do not propose APIs for arbitrary text-feed posts, automatic encoder start, arbitrary Channel Points grants, full-VOD downloads or unavailable Creator Dashboard analytics.

Please confirm the permissions and conditions for the following purposes:

1. Public OAuth for a paid multi-tenant creator/marketing SaaS, including account qualifications, app review, marketing/campaign-management restrictions and any required commercial agreement.
2. Permitted analytics and reporting, including broadcaster-authorized aggregation, allowed retention and whether game/extension developer analytics need separate approvals. We will not present unavailable revenue, watch-time, retention or unique-viewer values as API results.
3. Broadcaster-owned clips and content reuse, including official temporary clip download URLs, embedding, storage and explicitly authorized cross-platform publication. Please identify any additional Twitch written authorization and third-party rights requirements.
4. EventSub data retention, viewer-content handling, deletion after revocation or scope reduction, required disclosures and applicable limits on caching and sharing.
5. AI assistance using specifically disclosed subprocessors: bounded numeric analysis and draft preparation, with a distinct user preview and per-action human approval before Twitch mutations. Please confirm any restrictions on inference, model-provider retention, training, viewer-data processing and autonomous actions. We will provide the actual provider and data-processing details before requesting activation.
6. Security review, rate limits, token validation, app/broadcaster eligibility, required public privacy/deletion documentation, contractual terms and any fees.

Our candidate implements server-side encrypted access/refresh custody, strict workspace isolation, exact actor-bound approvals, current permission and authorization-generation checks at dispatch, immutable audit metadata, signed EventSub authentication, bounded encrypted retention, revocation-driven purge and separate controls for encoder keys and clip links. Our Agent cannot approve its own actions or obtain credentials. We are currently performing offline and synthetic acceptance; no live acceptance or Twitch authorization is being claimed.

Please direct us to the appropriate official review process and specify what written authorization is required before general availability. We can provide the endpoint/scope inventory, architecture, test evidence, data-flow and retention proposals, subprocessor information and user-consent screens.

Kind regards,

Rafii Team

https://rafii.io

## Complete before sending

James must supply or confirm the Rafii legal entity and authorized business contact, the official submission destination, actual privacy/deletion URLs, actual subprocessors and the intended commercial/storage/AI purpose details. These are material application facts and have not been fabricated. Submitting this draft or accepting a contract/fee requires separate approval.
