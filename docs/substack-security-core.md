# Substack provider security core

Research reference date: 2026-10-18. This document describes the provider core,
hosted draft boundary, and in-app handoff reminder in `src/postriff_phase2`.
Implementation and test sources are separate from live provider acceptance,
deployment receipts, and commercial-access grants.

## Access boundaries

Four modes remain distinct: `public_feed`, `official_mcp_analytics`,
`official_authorized`, and `official_partnership`. Adding a public publication URL
does not authenticate a Substack user or prove publication ownership. The feed
reader explicitly returns false for account, ownership, analytics, and publishing
claims.

The official MCP article describes Admin/Bestseller analytics and excludes writes,
profile data, and Notes. This version has no verified OAuth discovery, tool names,
field schemas, token contract, or Rafii SaaS-use agreement. It consequently cannot
produce an authenticated MCP connection. A passed `approved`, `scopes`, or
`account_authenticated` flag cannot manufacture implementation support. Provider
eligibility is never guessed from an invented paid-subscriber threshold.

Substack has announced a Typefully integration partnership. Notes publishing is
therefore `requires_official_approval` for Rafii, not universally impossible. No
other partner's application identity, credentials, permissions, or unpublished
endpoint assumptions are reused.

## Public feed request policy

- Only an ASCII `https://publication.substack.com` root or `/feed` URL is accepted.
  The canonical request is always `GET /feed` at port 443.
- Credentials, fragments, query strings, explicit ports, service/auth domains,
  IP literals, custom domains, nested subdomains, ambiguous backslashes, control
  characters, and encoded hosts are rejected before the transport runs.
- The real transport resolves DNS once, validates every result as public unicast,
  and opens a socket to a validated numeric address. TLS verifies the original
  hostname with the platform default trust store. There is no second hostname
  lookup at connection time.
- Known IPv6 transition forms also have their embedded IPv4 addresses checked;
  a globally labelled NAT64 prefix cannot hide a loopback or private destination.
- Redirects are not followed. The transport never accepts a caller's cookie,
  Authorization header, or upload body. Only a public anonymous GET is possible.
- Socket operations have a ten-second timeout; response reading is capped at
  1 MiB. XML content types are required, compressed bodies are rejected, and HTML
  returned with HTTP 200 is not treated as successful provider integration.
- DTDs and entity declarations are rejected before parsing. UTF-8, element-count,
  item-count, and excerpt-size limits bound the response. No external XML resources
  are resolved. Full `content:encoded` bodies are excluded from stored excerpts.
- Only article links on the same accepted publication host are retained. No
  article URL is fetched. Links to private, foreign, scripted, or token-bearing
  destinations are omitted. RSS/Atom descriptions become inert plain text.

The hosted route is responsible for user/workspace authorization, request and
refresh rate limits, retention, connection-ID binding, and storage. The injected
transport is a unit-test seam, never an endpoint-supplied function or URL override.
Custom-domain support should reuse the DNS pinning policy only after a separate
domain and ownership design is implemented and tested.

## Draft and manual handoff contract

The handoff builder accepts bounded text/Markdown content. Its body must render as
a text node, textarea, or preformatted text; raw HTML-enabled Markdown rendering is
not permitted. An escaped preview is supplied for HTML display. Content is treated
as user data, not agent instructions.

Article and Note handoffs contain text. Podcast/video choices prepare text such as
show notes and require the customer to add/review actual media in Substack;
`mediaPreparationRequired: true` and the manual instructions make that boundary
explicit. They do not claim a created video, uploaded audio, or published episode.

The SHA-256 digest binds normalized publication URL, title, body, content type,
format, audience, and the optional timezone-qualified target handoff time.
This digest is an integrity identifier; it is neither an authentication signature
nor evidence of approval. The hosted service must additionally bind approval to
workspace, destination connection, actor, and immutable draft revision, enforce
role/consent rules, and record audit events.

Every exported package has `status: manual_action_required`,
`autoPublished: false`, `providerScheduled: false`, and `providerReceipt: null`.
Caller-supplied published/approved flags cannot alter those values. Rafii stores
the optional target handoff time and reports whether the manual queue item is
due. Queue and Calendar present this as manual work. The in-app reminder described
below can alert an eligible reviewer when an approved target becomes due; no
Substack API post is scheduled and no external email is sent by this reminder.

## In-app handoff reminder

`src/postriff_phase2/substack_notifications.py` runs through a separate, bounded
step in the existing `NotificationService.cron`. It checks due targets even when
the workspace revision has not changed. Both the hosted Substack feature and
notifications feature must be enabled. A disabled feature opens no database
connection in this scan. Missing notification or account-block tables fail
closed; the reminder introduces no migration.

The scan locks the workspace and reads its current state again before emitting.
It rejects sample, frozen, deleting, or mismatched workspaces; canceled or prepared
jobs; inactive destinations; malformed identifiers; and stale content. The draft,
approval, queue hash, destination connection, canonical UTC target, and recomputed
content digest must agree. The exact draft must still pass manual-handoff
validation. An unscheduled draft does not create a due-time reminder.

Recipients are individually selected from active members with the existing
`approve` permission. Deleted profiles and active user, workspace, or inherited
workspace blocks are excluded. Shared profile and membership locks protect the
selection, with `SKIP LOCKED` avoiding interference with a concurrent account or
membership change. Notification visibility continues to use the existing
recipient/workspace isolation and membership checks.

Each `substack.manual_handoff_due` event has an actor-specific dedupe key containing
the job ID, content hash, and recipient ID. Its mandatory
`channel_filter: ('in_app',)` is applied by the existing outbox before delivery
rows are inserted. Email, push, SMS, telephone, and digest preferences cannot
promote it to another channel. The event contains fixed text and an internal
draft link; article titles, bodies, subscriber records, and credentials never
enter its payload. Its wording records that a target was reached and asks the
reviewer to check the current state, preserving the distinction when the draft
is subsequently edited or canceled.

Candidate queries exclude already-recorded recipient keys before applying their
limit. Additional keyset pages run within the same time budget, so invalid or
locked early candidates do not consume the delivery-attempt allowance. A
process-local cursor is an optimization, not the source of correctness. The scan
defaults to 50 delivery attempts and a two-second budget, with bounded SQL
statement timeouts and savepoints around individual outbox writes. Failed
attempts remain retryable, and a failed transaction is not reported as committed
notification creation. No provider job or Substack write is created.

## Metric provenance

| Provenance | Meaning | This version |
| --- | --- | --- |
| `verified_official` | A field read from an authorized official provider with a verified schema and receipt | Reserved; no function creates this label |
| `imported` | A customer-supplied export with source and observation time | Validated normalization helper; hosted import workflow remains unavailable |
| `derived` | A documented calculation over identified input observations, with formula and time window | Reserved until the calculation and input lineage are implemented; never relabeled official |
| `unavailable` | No authorized verified value | `value: null`; absence is not fabricated as zero |

Public-feed excerpts are tagged `public_feed` as content provenance and do not
become subscriber counts, revenue, Notes activity, ownership proof, or analytics.
Imported subscriber PII requires an explicit processing purpose, consent,
workspace-scoped storage, deletion, and a separate email-send permission; this
core implements no subscriber-record import or email transmission.

## Verification and remaining gates

`tests/test_substack_provider.py` uses mocked transports, resolvers, sockets, and
TLS objects. It checks mode restrictions, forged grants, invalid URLs, mixed/private
DNS answers, single-resolution TLS pinning, no redirects or credential forwarding,
malformed/oversized feeds, content injection, false publish receipts, draft digest
binding, and metric provenance. It does not contact Substack.

Hosted authorization/RLS, actual browser rendering, hosted queue lifecycle, and
the real notification SQL have separate test sources and execution reports. See
`tests/phase2/postgres_substack.py` and the integration's `TEST-RESULTS.md` for the
final database result; this security document does not assert a PostgreSQL test
count. Live public-feed acceptance, OAuth, refresh/revoke, official MCP tool
enumeration, partner write APIs, and production rollout also need their own
evidence. Offline tests cannot stand in for those provider and rollout gates.

`tests/test_substack_notifications.py` checks current-state and destination
validation, exact due-time boundaries, workspace restrictions, bounded scans,
cold-start pagination, per-recipient error isolation, failed-commit accounting,
and the mandatory in-app filter. Its outbox checks include the real planner with
immediate email/push preferences and injected phone/SMS plans. These are offline
boundary tests; the database suite separately checks actual delivery rows,
membership rules, RLS, and deduplication.

`tests/test_substack_agent_tools.py` exercises the registered tools through the
real agent adapter and real `HostedSubstackService`, with an in-memory repository
transaction seam. It checks tool scope, modality, feature gating, revoked/current
membership, wrong principals, foreign destinations, rejection of injected
approval/tenant/credential parameters, revision replay, readback mismatch, no
provider jobs, long-article protection, and output/pagination bounds. That seam
does not validate PostgreSQL behavior; the hosted database suite remains separate.

The agent only receives workspace metadata and separately requested complete
drafts that fit the model-output budget. A full draft is never silently truncated
and then made editable. Article bodies stay out of the workspace-summary tool.
Neither approval nor manual-handoff preparation is registered as an agent tool.
New tool declarations use capability generation 3 so legacy grants are not
silently extended.

Run the focused checks from the repository root:

```sh
python -m unittest discover -s tests -p 'test_substack_provider.py' -v
python -m unittest discover -s tests -p 'test_substack_agent_tools.py' -v
python -m unittest discover -s tests -p 'test_substack_notifications.py' -v
```

## Primary sources

- [Substack Developer API terms](https://substack.com/api-tos)
- [Official MCP documentation](https://support.substack.com/hc/en-us/articles/50834026608916-How-to-connect-Substack-to-your-AI-Assistant)
- [Publisher API product reference](https://substack.com/startups)
- [Substack partner announcement](https://on.substack.com/p/new-on-substack-creator-match-audience)
- [Official publication RSS guide](https://support.substack.com/hc/en-us/articles/360038239391-Is-there-an-RSS-feed-for-my-publication)
