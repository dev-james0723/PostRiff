# Standard Access video evidence

This directory contains an **actual 8-second Kynlo screen recording**, captured on 17 October 2026, of app 1615884's live Standard Access upgrade page.

[View the partial recording](standard-upgrade-form-partial-20261017.mp4)

It is preparation evidence only. It does not demonstrate OAuth, board discovery, Pin creation, scheduling, analytics, read-back or disconnection, and is **not suitable for submission**.

The current Pinterest form requires 20–60 fps and recommends MP4 under 2GB. ORC's connector rejects 20 fps because its maximum is 4 fps. The saved clip is H.264, 640×366, 4 fps, 8.000 seconds, 11,561 bytes. SHA-256: `808c0c217a5f614b29c42750a1c7909e3495397edcf85c68d8beef2d8818a1d8`.

The first frame and all 32 decoded frames were visually reviewed. They show only the relevant upgrade page; no tokens, codes, OAuth state, private email or unrelated application content appears. The unrelated Twin-window still observed during concurrent Chrome activity was not saved here.

A native-quality attempt launched QuickTime through CUA. That tool call remained blocked for about 686 seconds and was interrupted by the parent for a bounded handoff. Launch outcome is unknown; no QuickTime recording-start action was issued and no QuickTime video was produced. This is not evidence of a macOS permission denial or cancellation of the overall mission.

The current browser displayed workspace/profile labels whose exact actor/workspace identifiers were not verified. The earlier API pilot window expired at 20:40:56 UTC and the earlier grant was disconnected. Those facts block an honest full OAuth/API demonstration until the exact renewed consent and live-action scope is approved.

The same read-only browser review verified @jamesaucreates through its account/profile controls. Created shows “Create your first Pin”; Saved shows “You haven't saved any Pins yet”, with no board links or cards observed. No publishing destination or board ID is verified.

No upload, Standard Access submission, new OAuth grant, provider write, production change or paid call was performed by this recording agent.

Detailed observed form fields and status are in [the recording receipt](../evidence/standard-access-video-20261017.json). A complete submission video still needs actual OAuth, required functionality and provider read-back captured at native 20–60 fps after the bounded approvals in the parent release plan.

Parent reconciliation also returned an empty Kynlo app inventory despite known Chrome presence; a shell process read was denied. These observations leave QuickTime state unverified and establish an automation/inventory blocker. No blind retry or permission bypass was attempted.

## Bounded recorder investigation

Read-only installed macOS 27.2 help and man-page inspection found the native `screencapture` CLI, with video (`-v`), duration (`-V`) and window selector (`-l`) flags. `CGPreflightScreenCaptureAccess()` returned true for the current execution process without making a permission request. This does not establish QuickTime or Kynlo permission attribution.

A candidate bounded command can be reviewed by the parent using a fresh verified owned Chrome window ID, no audio flags and an owned output path. The interaction between video and window selection, actual frame rate and privacy isolation remain untested. No recording was started during this investigation.

The installed Apple SDK also documents a strict independent-window ScreenCaptureKit filter, configurable frame interval and native MP4 recording with system/microphone audio disabled. No helper was written, compiled or run. Actual 20–60fps acceptance remains `validation_unavailable` until an exact reviewed surface and method can be exercised and its real output inspected; metadata is not evidence of a compliant recording.


## Strict native recorder candidate — bounded compile timed out, not run

[StrictWindowRecorder.swift](StrictWindowRecorder.swift) is a local, dependency-free macOS 15+ candidate. It requests native 30 fps through Apple's ScreenCaptureKit, uses H.264 MP4, disables microphone/system audio and cursor, preserves the selected window's proportions at no more than 960 pixels wide, and has no display or alternative-window capture path.

Every run requires an explicit window ID, Chrome PID, exact window title, an observation timestamp no more than 30 seconds old, and a new MP4 destination directly inside this directory. It checks the Chrome bundle identifier, PID, selected window ID, title and on-screen state before capture and every 100 ms. A mismatch aborts. It captures nominally six seconds; a hard eight-second process watchdog removes only its newly generated private staging directory and exits on a stall. Output is never overwritten. Successful output remains explicitly unreviewed until video/privacy inspection.

The exact-title guard is deliberate: a navigation that changes the title aborts this version. This helper can capture separate short approved segments; it does not yet support a continuous OAuth sequence across titles. It performs no navigation, clicks, OAuth, provider action, upload or submission.

Source inspection and installed Apple SDK headers informed this candidate. **Compilation, runtime behavior, actual frame rate, finish-callback behavior and privacy isolation are unverified.** Static guard inspection is not an execution test. Do not use the unverified CLI video/window combination as a fallback.

Before any run, the parent must:

1. Review the source, the specific relevant browser window and the exact content to record, including actor/workspace where applicable. Exclude unrelated tabs/content and authentication codes/state from the approved surface.
2. Review the actual bounded native-only compile attempt below. A narrow Mac-only check was allowed by the cloud-build-router exception, but did not complete within its resource budget. No paid/cloud job, full app build or dependency installation was started. A further attempt requires a concrete diagnosis and a reviewed permitted resource budget.
3. After compilation, obtain a fresh exact window/PID/title observation and ensure the helper's own no-prompt preflight succeeds. Any denial stops the attempt; do not open settings, request permission, switch capture surface, or retry blind.
4. Run only the reviewed short segment, then inspect every frame and verify actual media format. Do not upsample the existing 4 fps clip to claim native compliance. Reject a changed-title or contaminated capture.
5. Keep full OAuth/live API work behind the exact renewed consent, live-action and recording-surface scope. Review the final complete video before any separately approved upload/submission.

Proposed compilation command, **not executed**:

~~~sh
xcrun swiftc -parse-as-library -swift-version 5 -Onone \
  -framework ScreenCaptureKit -framework AVFoundation \
  -framework AppKit -framework CoreGraphics -framework CoreMedia \
  StrictWindowRecorder.swift -o strict-window-recorder
~~~

Proposed run shape, **not executed**; placeholders must be replaced with a fresh reviewed observation:

~~~sh
./strict-window-recorder \
  --window-id 'FRESH_EXACT_WINDOW_ID' \
  --chrome-pid 'FRESH_EXACT_CHROME_PID' \
  --title 'EXACT_OBSERVED_WINDOW_TITLE' \
  --observed-at 'FRESH_UTC_ISO8601_WITHOUT_FRACTIONAL_SECONDS' \
  --output '/Users/ouxianxing/Documents/.agent-worktrees/rafii-pinterest-production-prep-20261014/docs/pinterest-production-20261014/standard-access-video/NEW_UNREVIEWED_FILENAME.mp4'
~~~

After an approved successful run, use lightweight local media metadata/decode inspection to verify H.264, no audio, frame rate 20–60 fps, duration at most eight seconds, expected dimensions, and all-frame privacy. This candidate does not itself establish any of those output acceptance results.

## Actual bounded native-only compile attempt

The cloud-build-router skill permits narrow Mac-bound native checks (lines 22 and 49). Exactly one low-priority, single-worker, unoptimized compile of this 10KB helper was attempted using the existing Apple Swift 6.4 compiler and installed frameworks, with a 12-second wall budget and 8-second per-process CPU soft limit. This was not a full Swift app build, JS build or dependency installation.

**Result: `validation_unavailable`**. The attempt reached its wall deadline at **12.072 seconds** and its own process group was terminated with SIGTERM (**exit -15**). Stdout/stderr were empty and no binary was created. No compiler source error was identified, so no speculative source repair or blind retry was made. The earlier compiler-version probe itself took 9.952 seconds under the current load; this is context, not proof of the precise compiler stall cause.

[Exact command and actual attempt receipt](native-compile-attempt-20261017.json). Source SHA-256 remained `16206868d81127b39db5d1fb267ed368f13dff78bd249a5aa4f3088847facd5a`. The helper was not executed; no window was captured and no permission, provider or production operation occurred. This result does not diagnose an OS permission issue.
