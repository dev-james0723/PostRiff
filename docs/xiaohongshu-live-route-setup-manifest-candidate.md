# Xiaohongshu live-route setup manifest — candidate

**State:** `awaiting_setup_approval`  
**Prepared:** 2026-09-13  
**Scope:** one owner-confirmed Xiaohongshu identity in James Au Studio; no content, asset, scheduled post, or remote submission is authorized by this document.

## Route

- **Route:** `browser`
- **Route driver:** `local_mcp_browser`
- **Provider:** self-hosted `xpzouying/xiaohongshu-mcp`; unofficial browser automation, never an official Xiaohongshu API.
- **Official-route review:** no current official creator-write route for this exact account and operation has been verified. A verified official route would supersede this candidate.

## Reviewed, quarantined artifacts

The following macOS Apple Silicon binaries were downloaded into an owner-only quarantine folder and have **not** been made executable or run.

| Artifact | Release | Commit | SHA-256 |
| --- | --- | --- | --- |
| `xiaohongshu-mcp-darwin-arm64` | `v2.5.0` | `6583124dfda92312b6bc19a042a6acfae63fe498` | `3e32e08c3403d22a5efef2f06aa52630b458819fc54474cba23e896c7092c38e` |
| `xiaohongshu-login-darwin-arm64` | `v2.5.0` | `6583124dfda92312b6bc19a042a6acfae63fe498` | `db5d07c03933b8192dab726d896a028721b096ea452f6e9967ef63a30618ba99` |

**Source:** `https://github.com/xpzouying/xiaohongshu-mcp/releases/tag/v2.5.0`  
**Quarantine location:** `/Users/ouxianxing/Library/Application Support/JamesAuStudio-Connections/xiaohongshu-mcp/quarantine/`

## Proposed local configuration

- Install to a non-synced owner-only application-support folder. The driver directory and session directory use mode `0700`; files use mode `0600`.
- Run only on `127.0.0.1:18060`, using the reviewed driver's `-port 127.0.0.1:18060` setting. No LAN or public binding.
- Generate a new MCP bearer token and retain it in macOS Keychain. The launcher receives it through `AUTH_TOKEN`; it is never passed on the command line, displayed, logged, stored in Studio data, or sent to a model.
- Use `COOKIES_PATH` to isolate the RedNote browser session under the owner-only session directory. Studio treats the session and all cookies/tokens as opaque: it may start a qualified service but will never read, display, copy, reset, or give them to an agent.
- Provide an internal Studio adapter only. It performs payload validation, exact account binding, idempotency, preview/approval checks, ambiguity reconciliation, and independent creator-centre/profile verification before any external write.

## Capability allowlist requested

| Capability | Candidate state | Additional requirement before use |
| --- | --- | --- |
| Login-status and current-user reads | enabled only after private login handoff | two independent identity signals must still match |
| Image-note media transmission and publishing | installed but blocked by default | exact immutable content/media/account/visibility approval and visible route test |
| Video media transmission and publishing | installed but blocked by default | separate exact test, including media decoder and rendered-result verification |
| Native schedule field | installed but blocked by default | separate schedule test, verified locally and at due time |
| Cookies and session persistence | enabled as opaque owner-only storage | no raw inspection, copying, reset, or agent access |
| MCP bearer token | enabled as Keychain-held service authentication | no raw inspection, copying, or client-side logging |

## Explicitly disabled

- comments, replies, likes, favorites, follows and notification writes;
- product lookup or product binding;
- account switching;
- cookie deletion/reset;
- any remote upload that is not attached to one exact approved post;
- automatic publishing, bulk publishing, headless first publish, and any publish/schedule request without a current per-artifact approval receipt.

## User handoff and account effect

The login helper must run visibly in a private handoff. The user completes QR/login/MFA/legal prompts themselves and does not paste any password, QR contents, cookie, bearer token, authorization code, or screenshot into chat.

The upstream documentation warns that a RedNote web session can displace another web session for the same account. This setup can sign out the currently open Creator Center/RedNote web session. Mobile-app verification remains available. After the sensitive page is closed, the user returns with `Xiaohongshu private login complete`; Studio then performs only the two non-secret identity checks.

## Costs, operations, and later gates

- No paid service, ad action, product binding, or content publication is included in this candidate.
- The browser runtime may download about 150 MB on its first launch.
- Installation and private login do not make the account publish-ready. Image, video, scheduling, and each actual post need their own qualified route test and exact approval.

## Approval requested

Approve only the following setup operations: install and execute the two reviewed artifacts above; configure loopback-only authenticated service access; create owner-only opaque session storage; implement the Studio allowlist/supervisor; and open a visible private login handoff for the already confirmed Xiaohongshu identity. This approval does **not** authorize any upload, schedule, test publish, or live publication.

## Execution receipt — 2026-09-13

- Approval was received for manifest hash `f7391763102e37a376a133391c046baff024e0654b67527119ddbfc900018a9f`.
- Both reviewed binaries were installed with their approved hashes and mode `0700`.
- The local bearer token was generated and stored in macOS Keychain without printing or placing it on a process command line.
- The Studio supervisor, exact operation allowlist, private-login handoff, and secret-blind identity verification were implemented and locally tested.
- The pinned driver failed closed before opening port `18060`: its vendor-provided browser DMG passed the upstream SHA-256 download check but failed macOS HFS CRC verification twice with `hdiutil: attach failed - image data corrupted`.
- No login window, remote upload, schedule, or publication occurred. A blocker record prevents automatic retries from repeatedly downloading the failed browser runtime.
- Continuing requires a separately reviewed driver artifact or a change to the approved route. Filesystem-verification bypasses such as `hdiutil -noverify` are not accepted.
