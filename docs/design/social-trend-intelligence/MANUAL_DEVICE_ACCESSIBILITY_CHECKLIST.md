# Trend Radar physical-device and VoiceOver acceptance

Status: **OPEN — human verification required.** Browser emulation, automated axe checks and keyboard automation do not satisfy this checklist.

Use one current iPhone-class device and one desktop Mac with VoiceOver. Test with Trends enabled only in an authorized non-production test workspace and with synthetic/stored evidence; do not activate providers, notifications or paid models.

1. On iPhone Safari, open Radar, an opportunity, the trust drawer, Ideas handoff, Weekly handoff, Campaign handoff and Opportunity Lab at default text size and 200% page zoom. Confirm no horizontal page clipping, unreachable controls or obscured dialogs.
2. With iOS VoiceOver, traverse the same path using swipe navigation and rotor headings/landmarks. Confirm loading, partial, unavailable, expired and error states are announced; observed/calculated/inferred/model-interpreted sections remain distinguishable.
3. Confirm restricted evidence is absent rather than merely visually hidden, and source links appear only when current policy permits them.
4. On macOS Safari with VoiceOver, complete Radar → trust drawer → Save to Ideas → Weekly/Campaign/chat handoffs using keyboard and VoiceOver commands only. Confirm dialog focus enters, stays contained, closes with Escape where supported and returns to the invoking control.
5. Confirm charts have equivalent text summaries, gaps are not announced as zero, units/windows/denominators are understandable, and color is never the only state cue.
6. Enable Reduce Motion and repeat drawer/card transitions. Confirm no information or control depends on animation.
7. Revoke the seeded receipt during the session. Confirm current content disappears or becomes an explicit unavailable state and VoiceOver announces the change without exposing removed text.
8. Record device/OS/browser/assistive-technology versions, pass/fail for each step, screenshots or screen recording where permitted, tester name, date and any defect IDs.

Acceptance requires all eight steps to pass. Until then, the 12 physical/manual-accessibility dependency rows remain open.
