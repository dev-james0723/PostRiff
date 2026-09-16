# Zhihu browser route

James explicitly selected browser automation using liuboacean/zhihu-automation-skill. Route `controlled_browser`; route_driver `zhihu-browser/1`. No OAuth/API onboarding for this route. This is a selective MIT adaptation at commit `9aca95da75ffd0238174ba9ed2438f4c519ce233`, not the upstream skill installed unchanged.

## Operate

Open Studio at http://127.0.0.1:4310 and choose Channels → Zhihu. Durable implementation: `/Users/ouxianxing/Documents/James-Au-Studio/src/james_au_social/zhihu_browser.py`. Use the dedicated browser sign-in button; after login, close its browser and verify the exact public profile. James selected `https://www.zhihu.com/people/tie4gka` in the 2026-09-13 task. This is a destination choice, not proof of authentication.

The user/project standing setup authorization covers starting this connection; do not restart first-run intake or request OAuth consent. Human-only password, phone/MFA, QR and CAPTCHA steps remain private handoffs. Do not observe login surfaces or export/read cookies. Browser session stays under owner-only `~/Library/Application Support/JamesAuStudio/zhihu-browser/profile`.

## Publishing pilot

Only immediate public text `zhihu.idea` (upstream `thought`) is implemented, with at most 1000 characters as a local pilot bound. Articles, answers, media, engagement and schedules remain unavailable through this driver. Prepare the full text and exact profile in Studio, show public visibility, immediate time and zero derivatives, then obtain content-bound approval. Approval is checked against the complete manifest hash. Do not click the approval checkbox or submit without James's exact instruction for the displayed content.

Two independent identity signals are required: authenticated header profile link and owner-only profile edit control. Unrecognized UI fails closed. A durable record is written before composition/final submission. Any uncertain attempt is retained and never resubmitted automatically. Reconcile using its attempt hash and public `/pin/<id>` permalink; independent read must match full text and author.

`local_preview`, fixture tests and an installed driver are not live success. `connected_identity` expires after 15 minutes and each post checks identity again. `published_verified` requires a fresh matching permalink read. This pilot never sets global/channel `publishReady` or enables recurring jobs.

Upstream crash recovery, cookie-export scripts, HTTP signature code and generic success reports are deliberately excluded. Review evidence and test receipt are in the source project's `artifacts/zhihu-browser-integration/`.
