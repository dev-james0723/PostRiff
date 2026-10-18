# Twitch native frontend engineering handoff

Status on 2026-10-18: implemented in the isolated Rafii worktree and validated offline. No live OAuth, Twitch mutation, production write, deployment, GitHub push, PR or merge was performed by the frontend agent. A successful offline test is not evidence of public release or commercial approval.

## Implemented user flows

- `/app/twitch` uses Rafii's existing authenticated workspace and API contexts. The workspace and selected connection key all React Query records and local form state. A workspace or connection change remounts pending review and sensitive state.
- Public connect and reconnect use the existing Twitch OAuth start endpoint. The user sees actual requested scopes and continues only through an exact HTTPS `id.twitch.tv/oauth2/authorize` URL. Server release flags determine whether connect is offered. Disconnect remains in the existing Channels management flow.
- Nine feature groups render the server's native operation registry: Channel/live; Schedule/markers; Chat/replies; Moderation; Clips/VOD; Community; Subscriptions/Bits/ads; Notifications; available Analytics. Nested arrays and objects support operations such as polls without accepting owner, moderator, role, scope or eligibility assertions from form fields.
- Reads are explicit user actions. Account verification refreshes the stored overview immediately, so verified account eligibility and live-state predicates can change availability. Stored overview polling never initiates a Helix read.
- A write prepares a server preview and displays the exact payload, account, effects, execution time and approval deadline. Approval requires an explicit checkbox, a server SHA-256 payload hash, the same signed-in actor, the current authorization generation, an unexpired draft and the current server availability. Editing content, scheduling or declarations invalidates the review.
- Marker creation requires the user's explicit Store past broadcasts declaration. The receipt must show that the declaration is included in the approval. Schedule entries and scheduling an API action never claim to start an encoder.
- Action history distinguishes approved, dispatching, accepted/provider processing, partially confirmed, confirmed, failed, paused, canceled, expired, revoked and unknown outcomes. No write is automatically retried. A saved clip receipt with a lookup confirmation can be reconciled by one explicit user click through the server's read-only provider lookup path.
- Stream keys and authorized clip download links use a separate interactive panel. Content rights are outside the native payload and must be included in the server-bound approval declaration. Server `interactiveAvailable` gates release access, workspace rights, scopes and any operator storage approval. Retrieval approves the exact hash and then calls the dedicated secret-access endpoint. It never downloads automatically or places a secret into the generic read result.
- Sensitive results live only in the component's memory, are masked by default for stream keys, expire after 30 seconds and are cleared when the tab hides or the component unmounts. A visibility generation discards responses that cross a hide/show boundary. Clip URLs must pass the same HTTPS Twitch/CDN host, credentials, port, fragment and control-character constraints as the native server.

## Agent and tenant boundaries

The complete Twitch workspace content body has `data-private`. Existing Site Agent screen-context and text-selection collectors honor that annotation. Result rows, raw receipts, exact payload previews and the complete sensitive panel also retain their own exclusion annotations. The only deliberately registered page context is the local connection ID and the current group/action names. Native Agent tools enforce their separate consent and output-projection policy; generic screen capture cannot expose chat, EventSub payloads, provider error text, account names, stream keys or download links from this page.

The frontend checks availability, actor and workspace permission for understandable controls. The backend remains authoritative for every tenant, role, OAuth scope, account-eligibility, exact-approval, resource-ownership and generation check. The frontend does not establish RLS or replace backend authorization evidence.

## API contract

All methods use `web/src/lib/api/client.ts`, including its current session bearer, same-origin app guard and encoded workspace/connection/action identifiers.

| Route after `/api/workspaces/{workspace}/twitch` | Method | Body |
| --- | --- | --- |
| root | GET | none |
| `/{connection}` | GET | none |
| `/{connection}/read/{action}` | POST | `{payload}` |
| `/{connection}/preview` | POST | `{action,payload,executeAt?,rightsConfirmed?,pastBroadcastsEnabled?}` |
| `/{connection}/actions/{id}/approve` | POST | `{payloadHash,confirmed:true}` |
| `/{connection}/actions/{id}/pause` | POST | empty |
| `/{connection}/actions/{id}/cancel` | POST | empty |
| `/{connection}/actions/{id}/reconcile` | POST | empty; server uses saved lookup evidence |
| `/{connection}/actions/{id}/secret-access` | POST | `{payloadHash,confirmed:true}` |

The server's action projection includes `actorId`, `generation`, `scheduled`, `declarations`, `executeAt`, `expiresAt`, `payloadHash` and durable `state`. `scheduled` distinguishes a requested future action from the worker timestamp for immediate work. Capability scope requirements preserve OR-of-AND alternatives. `verification:'verified'` alone never produces Verified without `liveVerified:true`.

## Validation

From the repository root, using the project's locked Node 24 dependencies in a free isolated runner:

```sh
node web/tests/twitch-native-controls.test.mjs
node web/tests/twitch-native-render.test.cjs
PYTHONPATH=src python web/tests/twitch-native-schema-fixture.py /tmp/rafii-twitch-native-fields.json
node web/tests/twitch-native-schema-contract.mjs /tmp/rafii-twitch-native-fields.json
node web/node_modules/typescript/bin/tsc --noEmit --incremental false -p web/tsconfig.json
web/node_modules/.bin/oxlint web/src/features/twitch web/src/app/app/twitch web/src/lib/api/client.ts
```

Observed results: 21 behavioral/API tests passed; 6 actual React/shared-component SSR tests passed; 112 native operation schemas, including optional fields, round-tripped through the native validator and browser parser; full project TypeScript check passed; targeted lint reported zero warnings and errors. The 112-schema run was repeated after native extreme-numeric-input hardening and is bound to `twitch_native.py` SHA-256 `a1faa848cd384e2c4770936a0f48d7e028589d44bebe294052bea8a1ea6f4022`. Regenerate the fixture if that module changes; the runner deliberately rejects a stale native-source hash. Frontend and backend Site Agent route manifests were byte-identical, and `git diff --check` passed.

The ordinary Node direct-file test commands report individual subtests in this runner. A harmless package-module-mode warning is emitted for direct TypeScript imports; no package manifest or dependency lock was changed to suppress it. No Next production build or Mac process was used. This validates rendering and contracts, not a deployed browser session or live Twitch behavior.

## Follow-up after authorized release work

Use a reviewed staging/live test account to validate OAuth callback, consent upgrades, eligible action execution, incoming EventSub and durable receipts only after the operator approval packet is accepted. Keep public connect, production verification, commercial clearance and content-storage approval independently truthful. Browser interaction and accessibility checks against the deployed/staging app remain unverified. An interrupted sensitive retrieval is not restored from browser persistence; inspect its saved action receipt and prepare a new explicit review when necessary.

The parent agent owns the backend, database evidence, integration commit and final mission handoff. The frontend agent made no commit or external publication.
