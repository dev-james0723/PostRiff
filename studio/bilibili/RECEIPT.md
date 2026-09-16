# Bilibili Studio integration receipt

State: installed locally; account connection and live upload not yet verified.

## Installed behavior

Studio > Channels > Bilibili > Open Bilibili connection and upload launches the isolated provider at http://127.0.0.1:4387. Browser verification reached the connection form and video preparation controls successfully.

Uses adapted upload_task.py from Misaka-Mikoto-Tech/bililive-auto-upload at 739896c55846c5cad4d61b2d741e7a49577e5e34 and its bilibili_api dependency at 7148fceba944c4a422f8c15e3758eb0933a4419f. Original source and GPL notices are retained. This is an unofficial session-cookie provider, not OAuth. No company registration or Xcode is involved.

The local wrapper provides encrypted session storage, fixed account identity validation, media staging, exact preview approval, job replay protection and independent BV/owner/title verification. Recorder automation, comments and updating existing videos are disabled. Failed chunks and network timeouts are bounded in the adapted provider.

Expected account UID: 3546856139262666 (JAMESAUCREATES). Credentials are entered only in the private local form. Secret storage is in the owner-only ~/Library/Application Support/JamesAuStudio-Bilibili directory, outside the repository. Encryption does not protect against other processes running as the same local user.

## Validation

- Six isolated bridge tests passed (mock provider; no real upload).
- Studio TypeScript/Vite production build passed.
- python3 -B scripts/verify_project.py passed.
- Running Studio UI button successfully launched the uploader and showed unconnected status.

## Remaining verification

User must enter SESSDATA and bili_jct privately and connect. No credentials have been supplied to this integration. Then select a specific video, cover and metadata and approve that exact public submission. Only a real platform response and independent matching record can establish live upload success. The pinned upstream is old; current server compatibility remains unverified until that test.

This is an on-demand local upload panel. It does not establish background scheduling or automatically integrate campaign delivery status into the main channel readiness card. The sidecar runs independently after launch.

## Files

Installed provider: /Users/ouxianxing/Documents/James-Au-Studio/studio/bilibili
Launcher: /Users/ouxianxing/Documents/James-Au-Studio/src/james_au_social/studio_bilibili.py
Studio changes: studio_api.py route registration and studio/web/src/ChannelSetup.tsx entry.
Candidate, upstream provenance and pre-installation backups: artifacts/bilibili-provider-candidate in the current worktree.
