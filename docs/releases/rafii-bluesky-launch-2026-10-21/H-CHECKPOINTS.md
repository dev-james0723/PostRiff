# Human checkpoints for James (H1, H2, H3)

Prepared 2026-10-22 ~05:50Z. Each is one message; nothing below has been executed.

## H1 Baseline connect test on today's production code (about 10 minutes, then one click 20 minutes later)

Purpose: prove the live Bluesky connect works at all before anything ships (A2, gate G0). Today's live code is `dpl_C57zH6ZP…` (`d3366822`), which still asks for the broad `transition:generic` scope and has the Reconnect display trap, so the test records the before-picture.

1. Use a dedicated Bluesky test account you own, not your main account. Tell me its handle.
2. Open https://rafii.io/app/channels while signed in to Rafii, choose Bluesky → Connect, and type the test handle.
3. On the Bluesky page, sign in yourself (I never type passwords) and approve.
4. Back on Rafii, leave the tab. After 20 minutes, reload Channels and tell me what the Bluesky card says.
5. Click Disconnect on the Bluesky card. This must happen before H2's client-identity change, because the grant was made under the old client_id.

I watch read-only with `WATCH.sql` (W1–W3) and runtime logs; no production setting changes.

## H2 One batched approval (after H1 and the green candidate)

Reply "approve H2" or strike any line:

a. **Build one release candidate** (billable, one Vercel production build of about 2.5 to 4 minutes; no second build for the same SHA). Built by the deploy owner (the Mastodon session) or by me, from a clean checkout of `01cf90a3` = `d3366822` + Bluesky:
   `vercel deploy --prod --skip-domain --scope jamesau0723-6572s-projects` (after confirming the linked project is `postriff-phase2-private`).
b. **Move the Bluesky client identity to rafii.io** (production env, applies from the build in a):
   `POSTRIFF_BLUESKY_CLIENT_ORIGIN = https://rafii.io` (today it pins the vercel.app origin; 0 real grants exist).
c. **Promote that same build**: `vercel promote <staged-deployment-id> --scope jamesau0723-6572s-projects`, then I run the connect acceptance (G2) on rafii.io with the test account (you sign in once more).
d. **Conditional rollback**: if any kill criterion K1–K6 trips, I run `vercel rollback dpl_C57zH6ZPWejerDrysB864XDEw3Qo --scope jamesau0723-6572s-projects` at once and report.
e. **Confirm**: T0, the legal approver for `/privacy` and `/terms`, and that launch is connect-only (DEC1).

Evidence pack for H2: CI `td07wtg4xp` exit 0, PR #221, `PATCH-MANIFEST.md`, `LOADTEST.md`, `ROLLBACK.md`, the independent review result.

## H3 Publish acceptance (stretch, only if C1–C6 can finish 3 hours before T0)

a. A second build of the same SHA with `POSTRIFF_OAUTH_BLUESKY_REVIEWED=true` (RC-B), promoted for the test window only (billable).
b. On the test account, click "Grant publishing" and sign in.
c. Approve the exact test post texts I send (text only; text plus one image with alt text; a link; a 300-grapheme post). I delete them afterwards.
