# Bluesky copy audit, error catalogue, banner and FAQ (E3, D7)

## Strings that describe Bluesky capability

| Place | Text after this release | Matches capability |
| --- | --- | --- |
| Channel directory (`web/src/config/channels.ts`) | "Text posts with one image on your Bluesky account. Links stay clickable." · status "publishing opens after testing" · notes add "Connecting confirms your identity only. Rafii asks again, and you approve each post, before anything is published." | Yes: identity Direct, publish not yet open |
| Publishing support (`publishing-support.ts`) | "Text or one image with alt text; links stay clickable. Connecting confirms your identity only; publishing needs a separate permission and your approval of each post." | Yes; guarded by `web/tests/publishing-support.test.mjs` |
| Channels card badge (`state.ts`) | "Identity connected" for an identity-only Bluesky grant | Yes; guarded by `channel-list.test.cjs` |
| Channels card message (`channel-card.tsx`) | "Bluesky identity connected — publishing permission required" with "Grant publishing…" | Yes |
| Directory capability chips (`identityOnly`) | identity Direct, publish Assisted, schedule Assisted | Schedule is Unsupported at runtime until REVIEWED; shared constant with other channels, left unchanged |

## Connect errors a customer can see

| When | Message (HTTP) |
| --- | --- |
| Bad handle | "Enter your Bluesky handle, for example name.bsky.social." (400) |
| Handle not found | "That Bluesky handle could not be found." (404) |
| Handle does not point back to its account | "That handle doesn't point back to its Bluesky account." (409) |
| Account has no reachable server | "This Bluesky account has no server Rafii can reach." (502) |
| Server offers no app sign-in | "This Bluesky server does not offer sign-in for apps." (502) |
| Bluesky or plc.directory slow, after one retry | "Bluesky is slow right now. Try again in a minute." (503) |
| PAR refused | "Bluesky did not start the sign-in. Try again." (502) |
| Too many starts | "Too many attempts. Wait a minute and try again." (429) |
| Signed in as another account | "The Bluesky account that signed in isn't the one you entered." (409) |
| Plan full | "This plan has no remaining connected-account slots." (402) |
| Grant ended at Bluesky | Card shows Reconnect; "Bluesky access expired; reconnect the account." (409) |
| Paused by operator | "This platform is paused for now. Your post history stays available." (503) |

## Banner if connect is paused

"Bluesky connections are paused for a moment while we fix a problem. Accounts you already connected are safe. Please try again later."

## FAQ

- **What does Rafii get when I connect Bluesky?** Proof of which account you own. Rafii cannot post or upload with that connection.
- **Can Rafii post for me?** Only after you grant publishing separately, and only the exact post you approve. Rafii never posts on its own.
- **Do you see my password?** No. You sign in on your own Bluesky server; Rafii receives a token, stored encrypted.
- **How do I disconnect?** Channels → Bluesky → Disconnect. Rafii asks Bluesky to revoke access and stops using it.
- **Does Rafii read my DMs, likes or followers?** No.
