# ADR: productivity connectors for chat references

- **Status:** Accepted as research. Nothing is built in this release. No OAuth app, client id, scope, token store change or background sync is authorized by this ADR.
- **Date:** 2026-09-26
- **Context:** chat-context SPEC §15, §16 Phase 3. The reserved chip kind `connector_item` already parses and is always reported unused `not_available_yet` (SPEC §6.7), so later clients degrade honestly.

## Decision

Connect productivity tools in this order, one at a time, each behind its own flag and James's approval:

| # | Connector | Scope and picker | Google/vendor review | Why this position |
|---|---|---|---|---|
| 1 | Google Drive | `drive.file` + Google Picker | Non-sensitive scope: brand verification only, about 2–3 business days. No security assessment. | Per-file consent matches "the person picks, the server re-checks". |
| 2 | Notion | Public OAuth integration, page picker (`owner=user`, refresh tokens); read with `GET /v1/pages/{id}/markdown` (`Notion-Version: 2026-03-11`). Hosted MCP (`mcp.notion.com`, OAuth 2.1 + PKCE + dynamic client registration) is the alternative. | No security audit. Optional gallery review 5–10 business days. | Page-level consent; common for briefs and programme notes. |
| 3 | Google Calendar | `calendar.events.readonly`, incremental authorization bundled with Drive | Sensitive scope: about 10 business days of verification, no security assessment. | Useful for event posts; read-only. |
| 4 | Gmail | Any read scope is restricted | Annual CASA assessment by a third-party lab (fee negotiated privately; secondary sources cite about USD 500–5,000), about 6 weeks, 100-new-user cap until verified. | Last, and only if people ask. Until then: paste the email as a text source; later a forward-to-Rafii address. |
| 5 | Dropbox Chooser / OneDrive Picker v8 | Chooser needs no OAuth approval (direct links expire in 4 hours); Picker v8 has more moving parts | — | Later. |

## Architecture

- **Tokens:** per-user OAuth, read-only scopes, stored in the existing `CredentialVault` (Fernet with key rotation, `oauth.py`). Connecting and disconnecting need `manage_connections`.
- **Trust boundary:** the first use of a connector's content as model input needs an owner-only `connector_egress` consent with a processor list, modelled on `research_egress` (`research.py`) and `media_egress` (`media_consent.py`).
- **Content path:** a picked item becomes a `document` or `link` source with `rewrite_approval` and per-source `egressConsent`, so only approved facts reach drafts (`source_policy.project_context`). Nothing from a connector bypasses source policy.
- **Chips:** `{kind: 'connector_item', provider, id}`. The server re-fetches by id with the person's own token; a stale or foreign id fails closed as unused (`turn_references`).
- **Metering:** fetches are metered, with the item ids inside the request body so the credit quote binds them (SPEC §3 S4).
- **Lifecycle:** no background sync. Cached excerpts (≤ 512 KiB) are deleted and tokens revoked on disconnect, account deletion and `invalid_grant`.
- **MCP:** Google's official Workspace MCP servers (Developer Preview) run on the developer's own OAuth client with the same scopes, so they don't avoid verification **(inferred)**.

## Verification effort before any build

| Step | Owner | Effort | Blocking |
|---|---|---|---|
| Google Cloud project, OAuth consent screen, brand verification (Drive) | James | 2–3 business days of Google review | Drive |
| Privacy policy: Google Limited Use disclosure (draft below) published | James | 1 day | Any Google scope |
| Calendar sensitive-scope verification | James | about 10 business days | Calendar |
| Notion public integration + optional gallery review | James | 0–10 business days | Notion |
| Gmail CASA assessment | James + third-party lab | about 6 weeks, recurring yearly | Gmail |
| `connector_egress` consent, metering, deletion paths, browser scene | Engineering | one wave per connector | Each connector |

## Draft Google Limited Use disclosure (for the privacy policy; not published)

> Rafii's use and transfer to any other app of information received from Google APIs will adhere to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.
>
> When you choose a Google Drive file or a Google Calendar event in Rafii, Rafii reads only that item, only when you ask, to turn it into a source you can review. Rafii does not read your other files, does not sync in the background, does not use Google data to train or improve general AI models, does not sell it, and does not use it for advertising. People at Rafii do not read it unless you ask us to for support, it is needed for security or to comply with the law. Text from a picked item reaches a writing model only after the workspace owner allows it and only as facts you approved. You can disconnect Google at any time; Rafii then revokes its access and deletes the excerpts it kept.

## Consequences

- No code, scopes or credentials change in this release. `connector_item` stays reported as `not_available_yet`.
- Each connector later adds its own consent, metering and deletion tests before its flag can turn on.

## Citations

- Google scope classes: https://support.google.com/cloud/answer/13464325
- Verification timings and CASA: https://support.google.com/cloud/answer/13463817, https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- `drive.file` and Picker: https://support.google.com/cloud/answer/13807380, https://developers.google.com/workspace/drive/picker/guides/overview
- Limited Use policy: https://developers.google.com/workspace/workspace-api-user-data-developer-policy
- Notion: https://developers.notion.com/docs/authorization, https://developers.notion.com/guides/mcp/build-mcp-client, https://developers.notion.com/guides/data-apis/working-with-markdown-content
- Google Workspace MCP servers: https://developers.google.com/workspace/guides/configure-mcp-servers
