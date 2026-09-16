# Xiaohongshu container fallback amendment — candidate

**State:** `authenticated_route_test_required`  
**Prepared:** 2026-09-14  
**Parent manifest:** `xiaohongshu-live-route-setup-manifest-candidate.md`  
**Scope:** replace only the failed macOS execution layer for the already confirmed RedNote identity. This amendment authorizes no upload, schedule, test post, publication, comment, reaction, account switch, cookie reset, or product binding.

## Why this amendment exists

- The reviewed v2.5.0 Apple Silicon server and login binaries are installed and match the release SHA-256 digests.
- Their required vendor browser `148.0.7778.215/macos-arm64.dmg` matches the vendor checksum but fails macOS HFS CRC verification. The driver therefore fails closed before login or port binding.
- Upstream still lists v2.5.0 as the latest release. The current `main` branch retains the same browser version, URL, checksum flow, and extraction code. The five commits after v2.5.0 contain only CI and documentation changes.
- Upstream also publishes a v2.5.0 Linux/AMD64 container with the Linux browser bundle embedded and checksum-verified during its build. This avoids the damaged macOS disk image without disabling integrity checks or substituting an unreviewed system browser.

## Exact fallback artifacts

| Component | Pin | Purpose |
| --- | --- | --- |
| Homebrew `colima` | `0.10.3` | Local Linux VM runtime |
| Homebrew `docker` CLI | `29.8.0` | Pull and operate the pinned container |
| `xpzouying/xiaohongshu-mcp:v2.5.0` | `sha256:88e2603f324f567e0a254ed7a1e24d632a16eccc30e84ef3fb887e34a03d0fe3` | Upstream Linux/AMD64 MCP service and embedded browser |

The container is Linux/AMD64 only. This Apple Silicon Mac already has Rosetta, so Colima will use Apple's native `vz` virtualization with Rosetta translation for the AMD64 image. This avoids adding QEMU. Homebrew may install documented transitive dependencies for Colima/Lima. No paid service is involved.

## Isolation and secret handling

- The Colima VM will disable host filesystem mounts and port forwarding. The container will have outbound network access for RedNote and no published host port during private login or identity verification.
- Studio will invoke the allowlisted local API inside the container through the local Docker control socket. The untrusted MCP service will not be reachable from the LAN, public internet, or another ordinary host process.
- The existing Keychain bearer token remains protected and is not copied into Docker environment metadata, command arguments, logs, source files, or the container filesystem.
- Cookies remain opaque in a Docker-managed volume inside the isolated VM. Studio will not read, display, copy, reset, or send cookie contents to a model.
- The Studio adapter remains the only callable boundary. It exposes identity checks and later exact-approved image/video/schedule calls; engagement, product, account-switch, reset, and bulk tools remain blocked.

## Login and qualification sequence

1. Install Colima and the Docker CLI, create the isolated Apple-virtualization VM with Rosetta translation, and pull the exact AMD64 image digest.
2. Start the container without a host port and confirm the container health response.
3. Request one login QR through the container-internal allowlisted endpoint and show it only in the local Studio private-handoff UI.
4. James scans/completes any mobile confirmation. No password, MFA code, QR payload, cookie, or token is pasted into chat.
5. Studio verifies the signed-in account using both the RedNote ID `94556602041` and nickname `小红薯6AA7E810`.
6. Keep all mutations locked. A separately approved visible image-note test, video test, and native schedule test are required before their respective route capabilities can become publish-ready.

## Automation boundary

The MCP supports `schedule_at` for image and video notes from one hour to fourteen days ahead. Installing the route does not create a recurring automation or authorize unknown future posts. The James Au automation skill still requires a frozen recipe with trigger, source scope, target, cadence, approval mode, cost ceiling, representative dry run, and activation hash. The current local automation runtime also lacks queue dispatch and post-time verification, so automatic recurring posting cannot be reported as enabled until those components are implemented and validated.

## Requested approval

Approve installation and execution of Colima `0.10.3`, Docker CLI `29.8.0`, and the exact v2.5.0 container digest above; the isolated container/session configuration; and the private QR-login plus identity-read checks for RedNote ID `94556602041`. This approval does not authorize a test upload, scheduled test, live post, recurring automation, or any other external write.

## Execution receipt — 2026-09-14

- The user approved this amendment in the Codex task before execution.
- Colima `0.10.3`, Docker CLI `29.8.0`, QEMU `11.1.1`, and Lima guest agents `2.2.0` are installed. The added QEMU path was required because the upstream Linux browser has no ARM64 build and the initial VZ/Rosetta browser process did not complete a QR request.
- The exact image digest `sha256:88e2603f324f567e0a254ed7a1e24d632a16eccc30e84ef3fb887e34a03d0fe3` was pulled into the dedicated `james-au-xhs-amd64` x86_64/QEMU profile.
- The fallback container has no published host ports or host bind mounts, uses a read-only root filesystem, drops all Linux capabilities, enables `no-new-privileges`, and stores data and media only in Docker-managed volumes. Its dedicated bridge has inter-container communication disabled and MTU `1400`, which was required for the Xiaohongshu TLS route.
- The container health endpoint passed, but its browser could not finish a QR request within 120 seconds under QEMU. It is retained as an installed recovery fallback and is stopped while the native route is active.
- Inspection of the checksum-valid upstream macOS artifact showed that the file named `macos-arm64.dmg` is served as a bzip2 block archive. Its official SHA-256 `b72f091e2e1a7583eed389c4b8e3534ed355e568af8c8bbf8fc30a25e23ca679` was verified before reconstruction. macOS mounted the recovered raw Apple partition image read-only, and the extracted `Chromium.app` is ARM64 and passes `codesign --verify --deep --strict` with upstream's ad-hoc signature.
- Studio now uses `local_mcp_browser` through the reviewed v2.5.0 native ARM64 binaries. The loopback service token remains in macOS Keychain, the native QR endpoint returned a valid four-minute private QR payload, and the cookie path is the private Studio session directory with Studio-enforced mode `0600` before verification.
- The confirmed public identity is nickname `小红薯6AA7E810`, RedNote ID `94556602041`, profile `https://www.rednote.com/user/profile/6aa748a9000000000301c840`. James completed the QR handoff twice. Each attempt wrote a bounded session file (`12040` bytes, mode `0600`), but the official helper ended with `登录流程完成但仍未登录`; a fresh MCP process returned `is_logged_in=false`, and `/api/v1/user/me` timed out. Post-auth identity matching therefore remains blocked and the route is not publish-ready.
- A cookie-blind browser-state diagnostic established the remaining cause: the installed upstream driver opened `www.xiaohongshu.com`, where the session remained `guest=true`. The connected Creator Center account is on `creator.rednote.com`. Upstream issue [#812](https://github.com/xpzouying/xiaohongshu-mcp/issues/812) and open PR [#798](https://github.com/xpzouying/xiaohongshu-mcp/pull/798) document that these domains use separate account sessions and that an overseas RedNote account must use the RedNote site route.
- Studio now has a separately versioned RedNote candidate based on upstream v2.5.0 commit `6583124dfda92312b6bc19a042a6acfae63fe498`, open PR #798 commit `b4cd95a55909c2d4ebed14013affe4258926191c`, and local compatibility commit `9f073e1bc31cdd5a6a304e8f09e7978b542f4d02`. The added compatibility work uses `https://www.rednote.com/login`, combines the documented logged-in selector with non-guest `__INITIAL_STATE__` identity evidence, and bounds QR lookup at 20 seconds.
- The installed candidate is `v2.5.0+studio-rednote.1`. Server SHA-256 is `3701f03de645de319b881ed55e8e85cf14897db9bbf3d35478934bebb5209ced`; login-helper SHA-256 is `803c32f0cf8d7741e384b92c9e2f8dbe205593572db04ed102d24261e103daee`. Both are ARM64, ad-hoc signed, and pass strict code-signature verification. The untouched upstream v2.5.0 binaries remain installed for rollback.
- A safe candidate test on `127.0.0.1:18061` passed health and returned a valid four-minute PNG QR from the RedNote login route without exposing the QR payload. Studio restarted healthy on `127.0.0.1:4310` and reports route driver `local_mcp_browser_rednote`, the patched version, protected loopback bearer, no RedNote session yet, and mutation lock enabled.
- James completed the RedNote-specific handoff. Studio first authenticated the protected session, then a separate direct MCP read returned `is_logged_in=true`, profile ID `6aa748a9000000000301c840`, nickname `小红薯6AA7E810`, and RedNote ID `94556602041`. The exact approved identity matches, and the route state is `authenticated_route_test_required` with `publishReady=false`.
- The RedNote cookie/session remains opaque and local. Its file is `7040` bytes with owner-only mode `0600`; no cookie or token value was read, logged, copied into application data, or exposed to the model.
- The user approved the three exact self-only route tests under `docs/xiaohongshu-route-tests/2026-09-14`, manifest `sha256:67d329f7b409ee6c40444bb9128bf65bef72727b75051932fef678be4f87b65a`. The owner-only approval receipt and SQLite attempt ledger were written before any submission.
- The first image attempt stopped before the final submit: the preserved form still showed `公开可见`, a `选择笔记` modal blocked the page, and the owner profile had no matching note. That outcome was reconciled as no submission. Studio then changed the automated driver from visible to headless mode to remove the browser location prompt that displaced the click; the focused Xiaohongshu suite passed `7/7` before the same job ID was retried.
- The self-only image note `Studio 圖文測試` is `verified_published`. The owner profile returned provider note ID `6aa7f403000000000e03c001`, type `normal`, exact author/profile identity, and the Creator Center note card independently matched the title and `仅自己可见` audience.
- The self-only video note `Studio 影片測試` is `verified_published` with provider note ID `6aa7f4f9000000000e03f400`. The owner profile matched the exact video note and author; a separate note-detail read confirmed a four-second video with an available stream; Creator Center matched the title and `仅自己可见`; and the provider review label cleared before the route was marked verified.
- The scheduled image submission was acknowledged, but Creator Center proves a timezone mismatch: it stored `2026-09-15 10:30 (GMT+8 Beijing time)`, equivalent to `2026-09-14 22:30 EDT`, instead of the approved `2026-09-15 10:30 EDT`. The ledger is `needs_user_action_wrong_schedule`, and `publishReady` remains false. No cancellation, deletion, edit, or replacement was attempted because the approved manifest explicitly excluded those actions. The heartbeat is paused pending exact correction approval.
- Automatic recurring posting is not active. Queue dispatch, scheduler binding, quiet-hour delivery, and independent post-time verification still need implementation and validation, followed by a frozen recipe and its scoped activation approval.
- Validation: the upstream-plus-RedNote Go suite passed all packages; Xiaohongshu identity/supervisor unit suite passed `7/7`; the repository verifier passed all required files, 17 JSON blocks, 33 adapter headings, five handoff markers, and secret-placeholder checks; the Studio web suite previously passed `70/70`; the production web build passed; the restarted Studio health endpoint reports `status=ok`.
