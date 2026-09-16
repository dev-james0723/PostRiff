# X persistent in-app browser route receipt

Date: 2026-09-14

## Outcome

- Preferred route: `controlled_browser`
- Route driver: `x-in-app-browser/1`
- Account: `@jamesaucreates`
- Cost: no X API and no paid plan
- Session: persistent Codex in-app browser; identity is rechecked before every write
- Live test: `https://x.com/jamesaucreates/status/2099408232758252029`

Separate Playwright Chrome and Edge profiles were retired because their X login did not persist reliably. The route never reads, copies, exports, or injects cookies.

## Durable files

- Orchestrator route: `/Users/ouxianxing/.codex/skills/james-au-social-orchestrator/references/x-in-app-browser.md`
- Approval/idempotency ledger: `/Users/ouxianxing/.codex/skills/james-au-social-orchestrator/scripts/x_in_app_browser.py`
- Studio status store: `~/Library/Application Support/JamesAuStudio/x-browser/state.sqlite3`
- Studio UI: `/Users/ouxianxing/Documents/James-Au-Studio/studio/web/src/XConnection.tsx`

## Validation

- Ledger status and local preview passed.
- Five focused X safety tests passed.
- Studio TypeScript/Vite production build passed.
- Portable 33-channel project verifier passed.
- Studio restarted successfully at `http://127.0.0.1:4310`.

## Operation contract

Future requests such as “make me a post about … and post to X” reuse the signed-in X tab, create an exact approval hash, claim the submission before the final click, click once, and independently verify the permalink. Native scheduling uses X's own scheduled-post queue. If X itself expires the saved session, login becomes a private handoff; routine runs do not ask for login while the two account signals remain present.
