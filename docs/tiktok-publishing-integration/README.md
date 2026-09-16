# Studio TikTok integration receipt

Integration target: `/Users/ouxianxing/Documents/James-Au-Studio`.

New TikTok panel: Settings / channel setup → TikTok. Prepare an MP4 snapshot, choose visibility and immediate/scheduled timing, preview the video and resolved local/UTC time, and approve the immutable review. Approval authorizes one submission only. Review preparation uploads nothing to TikTok.

Queue: persistent SQLite and private media copies at `~/Library/Application Support/JamesAuStudio/tiktok-publishing`. Worker runs in the Studio service, even if the browser tab is closed. Studio must be running and the Mac awake. A queued job more than five minutes late needs a new review. Pause affects unsent jobs; cancel cannot recall an in-progress or submitted post. Uncertain jobs never auto-retry. Acknowledged submissions remain submitted until independently checked on TikTok.

Transport: pinned TiktokAutoUploader commit d29b4366edf0de705e87f265298a06b64a00d7dc with local encryption/retry/privacy fixes. Runtime is copied into installed Studio under `studio/tiktok-runtime`; it does not depend on this worktree. Existing encrypted @jamesaucreates session remains outside source. Each dispatch checks own-profile navigation and Edit profile before invoking the uploader. No raw secrets appear in Studio JSON or logs.

Validation: 16 synthetic queue/API tests passed, including future dispatch, restart persistence, stale recovery, idempotent approval, tampering, cancellation and cross-origin rejection. The uploader has 13 passing synthetic hardening tests. Frontend TypeScript and Vite build passed. These tests create no live posts. The earlier 32-second private test remains the only approved/live upload in this session; no live scheduled post was authorized by this integration request.

Limitations: unofficial route can break or encounter CAPTCHA. Browser identity checks can open a temporary Chrome window at dispatch. Public posting is offered but only private posting has been live-tested. Studio's existing Backup feature does not include the separate TikTok queue/media directory; preserve that directory separately for recovery. No launch-at-login or wake-from-sleep service was added.

Modified pre-existing files are backed up under `backup/`, with baseline hashes in `baseline.json`. New source and UI files are in `candidate/`. Keep these changes when replacing Studio with another installer build.

Installed and verified 2026-09-13: service restarted successfully, owner-authenticated API reports workerRunning=true, paused=false, jobs=[]. Live browser verified Channels → TikTok → Schedule and the local timezone field. Built from current installed frontend sources to preserve concurrent Studio changes. Updated App route labels and service CLI capability descriptions; six installed source files recorded in installed.json. Project verifier passed. No additional upload or schedule was submitted.
