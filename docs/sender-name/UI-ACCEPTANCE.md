# Customer Discord sender names: UI acceptance

Branch `claude/discord-rc2-sendername-ui-20261023`, head `da378659`, 2026-10-28. Written against the backend head `9f170585` (its contract text, `docs/sender-name/UI-API-CONTRACT.md`). Author: web/UI engineer.

## 1. What this is

The checklist for the owner's decision 7: users set the name, preview what Discord actually shows, and clearly know when the bot nickname cannot be changed. Each row says how it was verified, what the result was and where the evidence is. Anything that was not verified says so (section 4). **This document does not say the feature passes as a whole.** It says what the web UI does and how that was checked, against synthetic data. The preview is an imitation of Discord, not Discord; the checks only the owner can make are in section 5.

## 2. Summary

| Check | Result |
| --- | --- |
| Web unit tests, sender names (`web/tests/discord-sender-name.test.cjs`) | 39 of 39 pass |
| All Discord node tests (`node --test tests/discord-*.test.cjs`) | 66 of 66 pass |
| Contract test against the real validator (`tests/test_discord_sender_name_ui_contract.py`) | on the backend tree: 4 pass; on this tree: 1 pass, 3 skipped (this tree has no `name_problem`, so the verdict checks skip with a message) |
| Type check (`tsc --noEmit`) / lint (`oxlint src`) | exit 0 / 0 errors, 37 warnings (the baseline count) |
| Browser acceptance (`web/tests/discord-sender-name-browser.cjs`, synthetic API, Chromium 141.0.7390.37) | pass: 4 runs (en-1280, en-390, zh-Hant-390, zh-Hans-1280) of 86 cases each, plus 5 once-per-run cases (dark-scheme-follows-app, axe-editor-light, axe-editor-dark, axe-blocked-state, evidence-screenshots); about 15 minutes |
| Locale catalogue / locale tests | Python locale tests 23 pass; web locale core tests 3 pass; copy audit 0 banned phrases. Running the catalogue builder rewrote 4 lines in each of two generated files; the script takes language names from the running Node (ICU 77.1, CLDR 47.0), which most likely differs from the one the committed files were built with, and the copy file is not an input of it. The rewrite was reverted and nothing of it is in this branch |
| Offline secret scan | full-tree scan: FAIL with 9 findings in 6 test files this branch did not touch (`tests/discord_ops_drills.py`, `impact_scenario.py`, `rc2_shared_path_scenario.py`, `test_customer_impact_dependencies.py`, `test_impact_compare.py`, `test_rc2_shared_path_fixes.py`); the same 9, with identical hashes, as on the base commit; 0 findings in any file this branch added or changed (also checked file by file before every push) |

## 3. Checklist

| Item | How verified | Result | Evidence |
| --- | --- | --- | --- |
| **A. Setting the name** | | | |
| Webhook: type a custom name, save; the request carries no shared-server flag | browser cases `webhook-edit-save`, `webhook-body-has-no-shared-flag` | pass, 4 of 4 locale/width runs | `ui-evidence/en-1280-webhook-editor-light-preview.png` |
| Bot: the nickname needs the "everyone in this server will see it" confirmation; the request carries it | browser cases `bot-shared-confirm-save`, `bot-body-has-shared-flag` | pass, 4 of 4 locale/width runs | `ui-evidence/en-1280-bot-editor.png`, `ui-evidence/zh-Hant-390-bot-editor.png` |
| Webhook: "Use the webhook's own name" removes the custom name; a second click while it is pending sends nothing; focus moves on; never offered for a bot | browser cases `webhook-reset`, `webhook-reset-focus-and-no-double-post` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Webhook that has no name of its own (`observedName` null): the form works | browser cases `webhook-without-own-name-works` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Bot: "Verify connection" with its reason (it records the nickname the freeze and hold rely on), a result in words, "try again" when the server says verification was unavailable | browser cases `bot-verify-action` | pass, 4 of 4 locale/width runs | `ui-evidence/en-1280-bot-editor.png` |
| **B. The preview** | | | |
| Webhook preview: author per post, APP tag, avatar placeholder with the "cannot be customised" note, time, line breaks, dark and light | browser cases `preview-webhook`, `preview-theme-toggle`; the preview tests | pass, 4 of 4 locale/width runs; pass, unit tests | `ui-evidence/en-1280-webhook-editor-light-preview.png`, `ui-evidence/en-1280-webhook-editor-dark-preview.png`, `ui-evidence/zh-Hans-1280-webhook-editor-light-preview.png` |
| Bot preview: everyone using the bot in the server sees the nickname, not a name for one post; "as last checked"; the held-if-changed note; the bot's own username when it has no nickname; a rename by someone else is shown as theirs | browser cases `preview-bot`, `bot-hold-note-and-warning` | pass, 4 of 4 locale/width runs | `ui-evidence/en-1280-bot-editor.png` |
| The preview follows what is typed and says it is not saved | browser cases `preview-live-update` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Contrast measured on what the browser drew, light and dark; the app's dark scheme is followed | browser cases `preview-contrast`, `dark-scheme-follows-app`; the contrast table test | pass, 4 of 4 locale/width runs; pass, once per run (English, 1280 px); pass, unit tests | `ui-evidence/en-1280-webhook-editor-dark-app.png` |
| Screen reader: the message is one named group described by the notes that say what the picture cannot show; the avatar is hidden; a name is text, never markup; state changes ride a polite live region and failures an alert | browser cases `axe-editor-light`, `axe-editor-dark`, `state-blocked-controls-explain`; the preview tests (group, label, notes id, hidden avatar) | pass, 4 of 4 locale/width runs; pass, once per run (English, 1280 px); pass, unit tests | harness receipt, no picture |
| Schedule dialog preview: webhook name, bot name unknown (never invented), bot nickname when known, time and line breaks | browser cases `schedule-preview-webhook`, `schedule-preview-bot`, `schedule-preview-bot-nickname`, `schedule-preview-lines-and-time` | pass, 4 of 4 locale/width runs | `ui-evidence/en-1280-schedule-dialog-preview.png`, `ui-evidence/zh-Hant-390-schedule-dialog-preview.png` |
| Review cards of approved posts: the webhook name; the bot nickname recorded at approval (or "no nickname") with the held-if-changed sentence | browser cases `review-preview-webhook`, `review-preview-bot`, `review-preview-bot-recorded-nickname` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Approval dialog of an automation run | type check | type check passes; not run in a browser | typecheck only, see section 4 |
| **C. Validation, the server's rules before saving** | | | |
| Every rule has its own message (empty, spaces at the edge, not normalised, too long, control or format, spacing, invisible, forbidden characters, web address, reserved words); counter shows the binding length; emoji count 2; zero width joiners only where the server accepts them | browser cases `validation-too-long`, `validation-surrounding-space`, `validation-spacing`, `validation-forbidden-character`, `validation-url-like`, `validation-reserved-word` and 7 more; 125 shared verdicts, same first reason as the real validator | pass, 4 of 4 locale/width runs; pass, unit tests | harness receipt, no picture |
| A webhook name and a bot nickname refuse different reserved words (Discord, Clyde, everyone, here are webhook-only) | browser cases `validation-reserved-by-kind`; the reserved-word test | pass, 4 of 4 locale/width runs; pass, unit tests | harness receipt, no picture |
| The server disagrees with the browser: its reason is shown and the form stays with the same fingerprint | browser cases `failure-server-rule-keeps-form` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| **D. Availability: why the name cannot be changed (one state each; text in Appendix A)** | | | |
| The 21 states, each with title, what it says, what you can do, a stable test id, focus on the explanation, Save explained | browser cases `state-sender_names_disabled`, `state-bot_nickname_disabled`, `state-provider_unavailable`, `state-not_authorizing_member`, `state-session_reverification_required`, `state-person_missing_manage_nicknames` and 16 more; the states and copy tests | pass, 4 of 4 locale/width runs; pass, unit tests | `ui-evidence/en-1280-state-person-missing-manage-nicknames.png`, `ui-evidence/en-390-state-bot-nickname-disabled.png`, `ui-evidence/zh-Hant-390-state-edit-pending.png` |
| Several reasons at once keep the server's order; Check again is a read; a pending change shows its wait and wakes at its time | browser cases `state-several-reasons`, `state-check-again-is-a-read`, `state-pending-countdown` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| A read-only view found on open is quiet: no alert, no error styling, no retry, no polling; focus returns to the Edit button | browser cases `read-only-view-is-quiet` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Writes that fail are said in words and never resent: stale, fresh sign-in, a reason found at write time | browser cases `failure-stale-reload-no-retry`, `failure-reload-uses-new-fingerprint`, `failure-fresh-session`, `failure-post-unavailable` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| **E. The cards** | | | |
| Every switch off (the opening): no button, no note, no request on the connections page | browser cases `card-nothing-when-off`; the provider-flag test | pass, 4 of 4 locale/width runs; pass, unit tests | harness receipt, no picture |
| No flag, no provider, or only the webhook connect route open: nothing either | browser cases `card-nothing-without-flags` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Flags on: the Edit button on exactly the cards of the kind the flag names; the page reads no sender name | browser cases `card-offered-when-on`, `card-flags-are-per-kind` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| **F. A held bot post** | | | |
| Queue: the held line, an explanation in the person's language, "Verify connection", the result; no action for another reason or for a webhook post | browser cases `queue-hold-verify-action`; the hold-line test | pass, 4 of 4 locale/width runs; pass, unit tests | `ui-evidence/queue-held-nickname.png` |
| **G. Interaction, layout, accessibility** | | | |
| Pending and repeated actions: double click, Enter twice, Close and Escape while saving | browser cases `protect-double-click`, `protect-enter-twice`, `protect-pending-close`, `protect-escape-while-saving` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| Keyboard: open, type, save, Tab order, Escape returns focus, blocked-state actions; focus lands on the field or the explanation | browser cases `keyboard-open-type-save`, `keyboard-tab-order`, `keyboard-escape-returns-focus`, `keyboard-state-actions`, `focus-on-field-after-load`, `focus-returns-to-trigger` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| No horizontal overflow at 390 px and 1280 px; long unbroken names wrap; reduced motion honoured | browser cases `no-horizontal-overflow`, `long-values-wrap`, `reduced-motion` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| axe-core (WCAG 2 A and AA) on the editor in light and dark and on a blocked state | browser cases `axe-editor-light`, `axe-editor-dark`, `axe-blocked-state` | pass, once per run (English, 1280 px) | harness receipt, no picture |
| Only the sender-name routes (and the verify request) were called; nothing left the isolated app | browser cases `no-unexpected-requests` | pass, 4 of 4 locale/width runs | harness receipt, no picture |
| **H. Wording and tests** | | | |
| Three locales: same keys and placeholders, Traditional and Simplified script hygiene, every state has all three lines | 39 tests in the sender-name file | pass, unit tests | unit test run (section 2) |
| CI wiring: the gate runs the harness and a failure fails the job; the harness fails on a missing case | the five CI wiring tests of the sender-name file: the cloud script runs the harness as a gate, a failing gate makes the script exit non-zero, the real harness failing makes the real gate fail, the workflow lets a failed gate fail the job, the harness checks its own case list | pass, unit tests | unit test run (section 2) |

## 4. Exceptions, limits and what was not verified

Nothing here is hidden behind a pass. Each line is a reason not to read the table above as "the feature passes".

1. **No live Discord.** The preview is an imitation of Discord's layout, written from Discord's documented display rules and checked in a browser against those rules. It has never been compared with a real Discord client, and this sandbox cannot do that (no network to Discord, no credentials). Section 5 lists the checks the owner can make in the tester server.
2. **At the opening a customer sees no sender-name editing.** Every sender-name switch is off unless the server sets it to the exact string `true`, so the provider view says `false` for the bot nickname and for the webhook name, and the card shows nothing: no button, no note, no request (tested: `card-nothing-when-off`). The webhook connect route is off too, so no webhook connection can be created. The editable form is therefore exercised by the tests and by the owner's tester server only. The same holds for a provider view that carries no flag or no Discord entry: nothing is shown.
3. **The bot nickname cannot be made per post, and the UI says so.** The nickname belongs to the bot in a whole server. The preview says everyone who uses the bot there sees it and that Rafii cannot freeze it per post. An approval records the nickname only once Rafii has observed it (a verification of the connection, a verified save in the editor, or a read that settled an earlier change; installing the bot records none); from then on a post is held, and nothing is sent, if Discord shows another nickname when it is due. Posts approved before the first observation carry no such guard. The editor says both and offers "Verify connection"; saving a new nickname holds every post approved under the old one, and the editor warns about that before the person saves. The UI cannot say how many posts that would be.
4. **`nickname_authority_other_workspace` follows the implemented rule, not the owner's wording.** The owner wrote that another workspace manages the nickname. The backend lets NEITHER workspace change it while both have the server connected, and the copy says exactly that, without naming the other workspace.
5. **The counter is UTF-16 units, not code points.** The task text and the contract say "characters" (code points). The server also keeps UTF-16 units within the limit, so an emoji counts 2 and a family emoji counts 8. The counter shows the binding number so it never disagrees with the server.
6. **Unicode versions.** Character categories come from the browser's tables (Unicode 16.0 here) and the server's Python (15.1.0 in the interpreter used for the shared fixture). Code points assigned only in Unicode 16.0 are accepted by the editor and refused by a server that runs Unicode 15.1 (the server's reason is then shown and the form stays); 36 other code points (outlined letters, U+1CCD6 to U+1CCF9) make the editor stricter. Details and counts: `UI-NEEDS.md`, section 5.
7. **The approval dialog of an automation run is checked by the type checker only.** `run-decision.tsx` sends `discordBotNickname` for bot posts when the channel view has it and draws the same preview. That dialog needs a full automation run behind it and has no browser case in this harness. The channel view does not carry the nickname (a backend test asserts it), so the field is never sent today: with the nickname capability on and a nickname observed, the backend refuses the approval (R1 in `UI-NEEDS.md`, `campaigns.py` lines 788 to 791). With the capability off, which is the opening, nothing is recorded and the approval goes through.
8. **The held-post action recognises an English sentence.** The held event carries no code, so the Queue shows the explanation and "Verify connection" only for a held Discord bot post whose event line contains "server nickname is no longer the one this post was approved under". If the sentence changes the action disappears (the editor still offers Verify). The action is on the Queue rows; the calendar and the pipeline cards show the line without the action (R3 in `UI-NEEDS.md`).
9. **Screen readers were not run.** Keyboard operation, focus movement, live regions, `aria-describedby` wiring, the preview as a named group, and axe-core (WCAG 2 A and AA) were checked in a browser. NVDA, VoiceOver and TalkBack were not run.
10. **Fonts in the screenshots.** The screenshots come from a sandbox Chromium without the web fonts and with fallback fonts, so letterforms differ from production; layout, wording, colours and states are what they show. CJK text is drawn with whatever CJK font the sandbox has.
11. **CI.** The workflow that runs the browser cases starts on a push to `codex/discord-personal-account-20261019` or by hand (`workflow_dispatch`), not on a push to this branch, and has `timeout-minutes: 35`. A full local run of the four locale and width combinations took 15 minutes on a four-core sandbox; nobody has run it on the CI runner yet.
12. **Secret scan.** The offline scan finds nothing in any file added or changed on this branch. See the report for the result of the full-tree scan.

## 5. What only the owner can check in the tester server

The preview is an imitation of Discord's message layout, drawn from Discord's documented display rules. It is not a Discord client, and nothing in this sandbox can talk to Discord. These are the checks that need a real tester server, a webhook and the Rafii bot. Each one says what the UI predicts, so a difference is easy to spot.

| # | Check | The UI predicts | Result |
| --- | --- | --- | --- |
| 1 | Webhook: set a custom name, approve and send a post | Author line shows the custom name with the APP tag; the text keeps its line breaks; the picture is the one set on the webhook (the preview only has a placeholder) | not checked |
| 2 | Webhook: names with accents, CJK, an emoji and a family emoji (zero width joiners) | The name appears as typed (Discord may normalise Unicode and whitespace; Rafii's read-back accepts that) | not checked |
| 3 | Webhook: a name of exactly 80 characters, and one of 40 emoji | Accepted by Rafii and by Discord | not checked |
| 4 | Webhook: "Use the webhook's own name", then send a post | The post shows the name saved on the webhook in Discord; posts approved earlier keep the name they were approved with | not checked |
| 5 | Bot: change the nickname through Rafii with the right permissions | The member list and new posts show the new nickname for everyone in the server | not checked |
| 6 | Bot: look at a post the bot sent before the change | Discord decides whether an older post shows the old or the new nickname. The preview makes no claim about older posts | not checked |
| 7 | Bot: approve a post, then rename the bot in Server Settings, then let the post fall due | The post is held, nothing is sent, and the held message tells you to review it again | not checked |
| 8 | Bot: rename the bot in Server Settings, then open Edit sender name | The editor says the nickname was changed outside Rafii and that Rafii does not own it | not checked |
| 9 | Bot: take away Manage Nicknames from the account that connected the server | State "Your Discord account cannot manage nicknames in this server", with Check again | not checked |
| 10 | Bot: put the connecting account's top role below the bot's role | State "Your Discord role is not above the bot's role" | not checked |
| 11 | Bot: take away Change Nickname from the bot's role | State "The Rafii bot is not allowed to change its nickname here" | not checked |
| 12 | Bot: connect the same server from a second Rafii workspace | Neither workspace can change the nickname; the state names no workspace | not checked |
| 13 | Does Discord write an audit log entry when the bot changes its own nickname, and does it show the reason text? | The UI makes no claim about the audit log. The backend sends a reason header; whether Discord logs a member's change to its own nickname is not known here | not checked |
| 14 | Discord client in Traditional and Simplified Chinese | The APP tag and the time format are Discord's own (the preview shows "APP" and the workspace time zone) | not checked |
| 15 | Markdown, links and mentions in the text | The preview shows the text as plain text with its line breaks; Discord's formatting is Discord's | not checked |

## 6. Backend dependencies

See `UI-NEEDS.md`, section 1: R1 (the nickname an automation approval has to echo has no source in the UI), R2 (the webhook name the approval compares against), R3 (the held-post event has no code). None blocks the opening, where every switch is off and no sender-name control is shown.

## Appendix A. What the UI says in each state

English, then Traditional Chinese, then Simplified Chinese, quoted from `web/src/lib/channels/discord-copy.json` by the script that wrote this file.

### English

| State | Title | What it says | What you can do |
| --- | --- | --- | --- |
| `sender_names_disabled` | Custom sender names are not available yet | Rafii has not switched on custom sender names, so the name cannot be changed here. Posts keep using the default sender. Your Discord connection itself is fine. | Nothing to do on your side. You will be able to set a name here once Rafii switches the feature on. |
| `bot_nickname_disabled` | Bot nickname changes are switched off | For safety, Rafii has switched off changing the bot’s nickname for now. That nickname is shared by everyone who uses the bot in a Discord server, and Rafii cannot yet stop different people overwriting each other. The bot keeps the nickname it has in this server today. Webhook sender names are not affected. | Nothing to do here. If you need a sender name of your own now, connect a Discord incoming webhook: its name belongs to that connection alone. |
| `provider_unavailable` | Rafii is not ready to change sender names | Rafii cannot make Discord changes at the moment, so the name cannot be read or changed here. This is on Rafii’s side, not something in your Discord setup, and nothing was changed. | Nothing to fix on your side. Choose Check again in a little while. If this stays the same, contact Rafii support. |
| `not_authorizing_member` | Only the member who connected the bot can change its nickname | This bot installation was authorized by another member of your workspace. Because the nickname is shared by everyone in the Discord server, Rafii lets only that member change it. Webhook sender names are not affected: any member who can manage connections can change those. | Ask that member to open this page and change the nickname, or connect the bot again from your own account. |
| `session_reverification_required` | Confirm it’s you first | Confirm your identity before changing this name. Then reopen the sender settings. | Sign out and sign in again, then reopen this page. Nothing was changed. |
| `person_missing_manage_nicknames` | Your Discord account cannot manage nicknames in this server | To change the bot’s nickname, the Discord account you used to connect this server must be the server owner, an Administrator, or have the Manage Nicknames permission there. It has none of these right now. | Ask a server administrator to give that account Manage Nicknames (Server Settings, then Roles), or to change the bot’s nickname for you. Then choose Check again. |
| `person_role_below_bot` | Your Discord role is not above the bot’s role | Discord only lets someone change the bot’s nickname if they are the server owner or their highest role is above the bot’s highest role. The Discord account you used to connect this server is neither right now. | Ask a server administrator to move your role above the Rafii bot’s role (Server Settings, then Roles), or to change the nickname for you. Then choose Check again. |
| `bot_missing_change_nickname` | The Rafii bot is not allowed to change its nickname here | In this Discord server the bot does not have the Change Nickname permission (and is not an Administrator), so Discord would refuse the change. | A server administrator can allow it: Server Settings, Roles, the Rafii bot’s role, then turn on Change Nickname. Then choose Check again. |
| `nickname_authority_other_workspace` | Another Rafii workspace also uses this server’s bot | Another Rafii workspace is also connected to this Discord server, so the bot’s nickname here is shared between workspaces. To keep people from overwriting each other, Rafii does not let any workspace change that nickname while that is the case. Rafii does not say which workspace. | You cannot change it from here. Your posts will use whatever nickname the bot has in this server. For a sender name of your own, connect a Discord incoming webhook. If the other workspace disconnects this server, choose Check again. |
| `edit_pending` | An earlier change is still being confirmed | Discord did not confirm the last nickname change, so Rafii cannot tell whether it went through. To avoid overwriting anything, no new change can be made until it has been checked. | Come back when Rafii can check again and choose Check again. Checking only reads the current name; Rafii never sends the change a second time on its own. |
| `stale` | These settings were changed by someone else | The sender settings changed after you opened this page. It could be another member, a server administrator in Discord, or another Rafii workspace. Your change was not saved. | Choose Reload current name to see what it is now, then make your change again if you still want it. |
| `reconnect_required` | Reconnect this Discord connection first | Rafii can no longer confirm this connection. It was revoked, or its permissions or authorizing account changed, so the name cannot be changed. | Reconnect it from the Channels page, then choose Check again. |
| `write_unconfirmed` | Discord did not confirm the change | Discord accepted the nickname change but did not confirm the nickname you chose, or the check afterwards failed. The nickname may have changed, and Rafii did not try again. | Choose Check again to see the nickname Discord has now before you do anything else. |
| `write_refused` | Discord refused the nickname change | Discord answered the change with a refusal, for example because a permission was lost a moment ago. The nickname is unchanged, nothing is waiting, and Rafii did not try again. | If a permission is missing, fix it in Discord first. Then choose Check again to see the nickname and permissions as they are now, and try again. |
| `write_rate_limited` | Discord asked Rafii to slow down | Discord answered the nickname change by asking Rafii to wait, so the change was not made. The nickname is unchanged, nothing is waiting, and Rafii did not try again. This is not a permission problem. | Wait until the time shown, then choose Check again and try again. |
| `evidence_invalid` | Discord’s answer could not be used | Discord’s answer about this server, your roles or the bot’s permissions was incomplete, so Rafii could not tell whether the nickname can be changed. Nothing was changed. | Choose Check again once. If it keeps happening, reconnect the Discord installation from the Channels page. |
| `rate_limited` | Too many checks for now | Rafii limits how often a sender name can be read or changed, to protect your Discord server. Nothing was changed. | Wait until the time shown, then choose Check again. Choosing it sooner is refused again. |
| `rate_delayed` | Discord requests are busy right now | Rafii shares one request allowance with everything else it does on Discord, and it is used up for the moment, so nothing was sent. Nothing was changed. | Wait for the time shown, then choose Check again. Rafii does not retry for you. |
| `upstream_unavailable` | No answer right now | Discord or Rafii did not answer, so the name could not be read or saved. Nothing was changed. | Try again in a minute: choose Check again to read the current name. |
| `workspace_permission` | You cannot manage connections in this workspace | Changing a sender name needs the permission to manage connections in this workspace, and your role does not have it (or you are no longer a member). Nothing was changed. | Ask a workspace owner or administrator to change your role. |
| `failed` | Rafii could not check or save the name | The change could not be verified. Reload the current name before trying again. | Choose Reload current name. Rafii will read the name again and will not send your change a second time on its own. |

### Traditional Chinese

| State | Title | What it says | What you can do |
| --- | --- | --- | --- |
| `sender_names_disabled` | 尚未提供自訂發送者名稱 | Rafii 尚未開啟自訂發送者名稱，所以無法在此更改名稱。貼文會繼續使用預設發送者。你的 Discord 連接本身並無問題。 | 你這邊無須做任何事。待 Rafii 開啟此功能後，你便可在此設定名稱。 |
| `bot_nickname_disabled` | 機械人暱稱更改已關閉 | 為安全起見，Rafii 暫時關閉了更改機械人暱稱的功能。該暱稱由伺服器內所有使用此機械人的人共用，而 Rafii 暫時還無法避免不同人互相覆蓋。機械人會繼續使用它目前在此伺服器的暱稱。Webhook 發送者名稱不受影響。 | 此處無須操作。如現在就需要自己的發送者名稱，可連接 Discord 傳入 Webhook：名稱只屬於該連接。 |
| `provider_unavailable` | Rafii 暫時未能更改發送者名稱 | Rafii 目前未能向 Discord 作出更改，所以無法在此讀取或更改名稱。這是 Rafii 方面的情況，與你的 Discord 設定無關，亦沒有任何更改。 | 你這邊無需處理。請稍後選擇「重新檢查」；如情況沒有改變，請聯絡 Rafii 支援。 |
| `not_authorizing_member` | 只有連接此機械人的成員可更改暱稱 | 此機械人安裝由你工作區的另一位成員授權。由於暱稱由 Discord 伺服器內所有人共用，Rafii 只容許該成員更改。Webhook 的發送者名稱不受影響：任何可管理連接的成員都可更改。 | 請該成員開啟此頁面更改暱稱，或由你自己的帳戶重新連接此機械人。 |
| `session_reverification_required` | 請先確認是你本人 | 請先驗證登入身分，再重新開啟發送者設定。 | 請登出並重新登入，再重新開啟此頁面。沒有任何更改。 |
| `person_missing_manage_nicknames` | 你的 Discord 帳戶無法在此伺服器管理暱稱 | 要更改機械人暱稱，你連接此伺服器時所用的 Discord 帳戶必須是伺服器擁有者、具備「管理員」權限，或在該伺服器擁有「管理暱稱」權限。該帳戶目前三者皆無。 | 請伺服器管理員授予該帳戶「管理暱稱」權限（伺服器設定，再選身分組），或請他為你更改機械人暱稱。完成後選擇「重新檢查」。 |
| `person_role_below_bot` | 你的 Discord 身分組並不高於機械人的身分組 | Discord 只容許伺服器擁有者，或最高身分組高於機械人最高身分組的人更改機械人暱稱。你連接此伺服器時所用的 Discord 帳戶目前兩者皆不是。 | 請伺服器管理員把你的身分組移到 Rafii 機械人的身分組之上（伺服器設定，再選身分組），或請他為你更改暱稱。完成後選擇「重新檢查」。 |
| `bot_missing_change_nickname` | Rafii 機械人在此不被允許更改暱稱 | 在此 Discord 伺服器內，機械人沒有「更改暱稱」權限（亦不是管理員），Discord 會拒絕這項更改。 | 伺服器管理員可以開放：伺服器設定，身分組，Rafii 機械人的身分組，開啟「更改暱稱」。完成後選擇「重新檢查」。 |
| `nickname_authority_other_workspace` | 另一個 Rafii 工作區也在使用此伺服器的機械人 | 另一個 Rafii 工作區也連接了此 Discord 伺服器，所以機械人在此的暱稱由多個工作區共用。為免互相覆蓋，只要情況如此，Rafii 不容許任何工作區更改該暱稱。Rafii 不會透露是哪個工作區。 | 你無法在此更改。貼文會使用機械人在此伺服器的現有暱稱。如要自己的發送者名稱，可連接 Discord 傳入 Webhook。如另一個工作區已中斷此伺服器的連接，請選擇「重新檢查」。 |
| `edit_pending` | 先前的更改仍在確認中 | Discord 未有確認上一次的暱稱更改，Rafii 無法判斷是否已生效。為免覆蓋任何內容，在核對完成前不能再作更改。 | 待 Rafii 可再次檢查時回來，選擇「重新檢查」。檢查只會讀取目前名稱，Rafii 不會自行再次發送更改。 |
| `stale` | 設定已被其他人更改 | 你開啟此頁面後，發送者設定已有更改。可能是另一位成員、Discord 伺服器管理員，或另一個 Rafii 工作區。你的更改未有儲存。 | 選擇「重新載入目前名稱」查看現況，如仍想更改，請再操作一次。 |
| `reconnect_required` | 請先重新連接此 Discord 連接 | Rafii 已無法確認此連接：連接已被撤銷，或其權限或授權帳戶已改變，所以無法更改名稱。 | 請在「頻道」頁面重新連接，然後選擇「重新檢查」。 |
| `write_unconfirmed` | Discord 未有確認這項更改 | Discord 接受了暱稱更改，但沒有確認你所選的暱稱，或事後的檢查失敗。暱稱可能已經改變，Rafii 亦沒有再次嘗試。 | 請先選擇「重新檢查」，查看 Discord 現時的暱稱，再作其他操作。 |
| `write_refused` | Discord 拒絕了暱稱更改 | Discord 以拒絕回應這項更改，例如權限剛剛被取消。暱稱沒有改變，沒有任何更改在等待處理，Rafii 亦沒有再次嘗試。 | 如欠缺權限，請先在 Discord 修正。然後選擇「重新檢查」，查看現時的暱稱與權限，再試一次。 |
| `write_rate_limited` | Discord 要求 Rafii 放慢速度 | Discord 在處理暱稱更改時要求 Rafii 稍候，所以更改沒有進行。暱稱沒有改變，沒有任何更改在等待處理，Rafii 亦沒有再次嘗試。這不是權限問題。 | 請等到所示時間，然後選擇「重新檢查」，再試一次。 |
| `evidence_invalid` | Discord 的回應無法使用 | Discord 對此伺服器、你的角色或機械人權限的回應不完整，所以 Rafii 無法判斷是否可更改暱稱。沒有任何更改。 | 請選擇一次「重新檢查」。如持續出現，請在「頻道」頁面重新連接 Discord 安裝。 |
| `rate_limited` | 暫時檢查次數過多 | Rafii 會限制讀取或更改發送者名稱的頻率，以保護你的 Discord 伺服器。沒有任何更改。 | 請等到所示時間，然後選擇「重新檢查」。太早檢查只會再次被拒絕。 |
| `rate_delayed` | Discord 請求目前繁忙 | Rafii 與其他 Discord 操作共用同一個請求額度，額度暫時用完，所以沒有發出任何請求，亦沒有任何更改。 | 請等到所示時間，然後選擇「重新檢查」。Rafii 不會替你重試。 |
| `upstream_unavailable` | 暫時沒有回應 | Discord 或 Rafii 沒有回應，所以未能讀取或儲存名稱。沒有任何更改。 | 請一分鐘後再試：選擇「重新檢查」讀取目前名稱。 |
| `workspace_permission` | 你無法管理此工作區的連接 | 更改發送者名稱需要此工作區的「管理連接」權限，而你的角色沒有此權限（或你已不是成員）。沒有任何更改。 | 請工作區擁有者或管理員更改你的角色。 |
| `failed` | Rafii 未能核對或儲存名稱 | 未能核實更改結果。請重新載入目前名稱，再決定是否重試。 | 選擇「重新載入目前名稱」。Rafii 會重新讀取名稱，不會自行再次發送你的更改。 |

### Simplified Chinese

| State | Title | What it says | What you can do |
| --- | --- | --- | --- |
| `sender_names_disabled` | 尚未提供自定义发送者名称 | Rafii 尚未开启自定义发送者名称，所以无法在此更改名称。帖子会继续使用默认发送者。你的 Discord 连接本身并无问题。 | 你这边无须做任何事。待 Rafii 开启此功能后，你便可在此设置名称。 |
| `bot_nickname_disabled` | 机器人昵称更改已关闭 | 为安全起见，Rafii 暂时关闭了更改机器人昵称的功能。该昵称由服务器内所有使用此机器人的人共用，而 Rafii 暂时还无法避免不同人互相覆盖。机器人会继续使用它当前在此服务器的昵称。Webhook 发送者名称不受影响。 | 此处无须操作。如现在就需要自己的发送者名称，可连接 Discord 传入 Webhook：名称只属于该连接。 |
| `provider_unavailable` | Rafii 暂时无法更改发送者名称 | Rafii 目前无法向 Discord 作出更改，所以无法在此读取或更改名称。这是 Rafii 方面的情况，与你的 Discord 设置无关，也没有任何更改。 | 你这边无需处理。请稍后选择“重新检查”；如情况没有改变，请联系 Rafii 支持。 |
| `not_authorizing_member` | 只有连接此机器人的成员可更改昵称 | 此机器人安装由你工作区的另一位成员授权。由于昵称由 Discord 服务器内所有人共用，Rafii 只允许该成员更改。Webhook 的发送者名称不受影响：任何可管理连接的成员都可更改。 | 请该成员打开此页面更改昵称，或由你自己的账户重新连接此机器人。 |
| `session_reverification_required` | 请先确认是你本人 | 请先验证登录身份，再重新打开发送者设置。 | 请退出并重新登录，再重新打开此页面。没有任何更改。 |
| `person_missing_manage_nicknames` | 你的 Discord 账户无法在此服务器管理昵称 | 要更改机器人昵称，你连接此服务器时所用的 Discord 账户必须是服务器所有者、具备“管理员”权限，或在该服务器拥有“管理昵称”权限。该账户目前三者皆无。 | 请服务器管理员授予该账户“管理昵称”权限（服务器设置，再选身份组），或请他为你更改机器人昵称。完成后选择“重新检查”。 |
| `person_role_below_bot` | 你的 Discord 身份组并不高于机器人的身份组 | Discord 只允许服务器所有者，或最高身份组高于机器人最高身份组的人更改机器人昵称。你连接此服务器时所用的 Discord 账户目前两者皆不是。 | 请服务器管理员把你的身份组移到 Rafii 机器人的身份组之上（服务器设置，再选身份组），或请他为你更改昵称。完成后选择“重新检查”。 |
| `bot_missing_change_nickname` | Rafii 机器人在此不被允许更改昵称 | 在此 Discord 服务器内，机器人没有“更改昵称”权限（也不是管理员），Discord 会拒绝这项更改。 | 服务器管理员可以开放：服务器设置，身份组，Rafii 机器人的身份组，开启“更改昵称”。完成后选择“重新检查”。 |
| `nickname_authority_other_workspace` | 另一个 Rafii 工作区也在使用此服务器的机器人 | 另一个 Rafii 工作区也连接了此 Discord 服务器，所以机器人在此的昵称由多个工作区共用。为免互相覆盖，只要情况如此，Rafii 不允许任何工作区更改该昵称。Rafii 不会透露是哪个工作区。 | 你无法在此更改。帖子会使用机器人在此服务器的现有昵称。如要自己的发送者名称，可连接 Discord 传入 Webhook。如另一个工作区已断开此服务器的连接，请选择“重新检查”。 |
| `edit_pending` | 之前的更改仍在确认中 | Discord 没有确认上一次的昵称更改，Rafii 无法判断是否已生效。为免覆盖任何内容，在核对完成前不能再作更改。 | 待 Rafii 可再次检查时回来，选择“重新检查”。检查只会读取当前名称，Rafii 不会自行再次发送更改。 |
| `stale` | 设置已被其他人更改 | 你打开此页面后，发送者设置已有更改。可能是另一位成员、Discord 服务器管理员，或另一个 Rafii 工作区。你的更改没有保存。 | 选择“重新加载当前名称”查看现状，如仍想更改，请再操作一次。 |
| `reconnect_required` | 请先重新连接此 Discord 连接 | Rafii 已无法确认此连接：连接已被撤销，或其权限或授权账户已改变，所以无法更改名称。 | 请在“频道”页面重新连接，然后选择“重新检查”。 |
| `write_unconfirmed` | Discord 没有确认这项更改 | Discord 接受了昵称更改，但没有确认你所选的昵称，或事后的检查失败。昵称可能已经改变，Rafii 也没有再次尝试。 | 请先选择“重新检查”，查看 Discord 当前的昵称，再进行其他操作。 |
| `write_refused` | Discord 拒绝了昵称更改 | Discord 以拒绝回应这项更改，例如权限刚刚被取消。昵称没有改变，没有任何更改在等待处理，Rafii 也没有再次尝试。 | 如缺少权限，请先在 Discord 修正。然后选择“重新检查”，查看当前的昵称与权限，再试一次。 |
| `write_rate_limited` | Discord 要求 Rafii 放慢速度 | Discord 在处理昵称更改时要求 Rafii 稍候，所以更改没有进行。昵称没有改变，没有任何更改在等待处理，Rafii 也没有再次尝试。这不是权限问题。 | 请等到所示时间，然后选择“重新检查”，再试一次。 |
| `evidence_invalid` | Discord 的响应无法使用 | Discord 对此服务器、你的角色或机器人权限的响应不完整，所以 Rafii 无法判断是否可更改昵称。没有任何更改。 | 请选择一次“重新检查”。如持续出现，请在“频道”页面重新连接 Discord 安装。 |
| `rate_limited` | 暂时检查次数过多 | Rafii 会限制读取或更改发送者名称的频率，以保护你的 Discord 服务器。没有任何更改。 | 请等到所示时间，然后选择“重新检查”。太早检查只会再次被拒绝。 |
| `rate_delayed` | Discord 请求目前繁忙 | Rafii 与其他 Discord 操作共用同一个请求额度，额度暂时用完，所以没有发出任何请求，也没有任何更改。 | 请等到所示时间，然后选择“重新检查”。Rafii 不会替你重试。 |
| `upstream_unavailable` | 暂时没有响应 | Discord 或 Rafii 没有响应，所以未能读取或保存名称。没有任何更改。 | 请一分钟后再试：选择“重新检查”读取当前名称。 |
| `workspace_permission` | 你无法管理此工作区的连接 | 更改发送者名称需要此工作区的“管理连接”权限，而你的角色没有此权限（或你已不是成员）。没有任何更改。 | 请工作区所有者或管理员更改你的角色。 |
| `failed` | Rafii 未能核对或保存名称 | 未能核实更改结果。请重新加载当前名称，再决定是否重试。 | 选择“重新加载当前名称”。Rafii 会重新读取名称，不会自行再次发送你的更改。 |

### Wait line, held-post line and Verify

| Key | English |
| --- | --- |
| `senderRecheckIn` | Rafii can check again in about {wait}, at {time}. |
| `senderRecheckAt` | Rafii can check again at {time}. |
| `senderRecheckNow` | Rafii can check again now. |
| `senderRecheckSoon` | Rafii can check again in about two minutes. |
| `senderHoldNote` | The bot’s nickname in the server changed after this post was approved, so nothing was sent. Verify the connection so Rafii records the nickname as it is now, then review and approve the post again. |
| `senderVerifyLabel` | Verify connection |
| `senderVerifyHint` | Rafii records the bot’s nickname when it verifies the connection. Verify once after connecting, and again if a post was held because the nickname changed. Until then, posts you approve are not guarded against a later rename. |
| `senderVerifyDone` | Verified. Rafii has recorded the bot’s nickname as it is now. |
| `senderVerifyRepeat` | Rafii could not verify just now, for example because another change to this connection was in progress. Try again. |
| `senderVerifyFailed` | The connection could not be verified: {detail} |
| `senderBotSaveWarning` | Posts already approved under the old nickname will be held, not sent, until you review them again. |
| `previewBotNote` | Everyone who uses this bot in this server sees this nickname: every member, people who use other apps there, people who never use Rafii, and other Rafii workspaces connected to this server. It is not a name for one post. Rafii cannot freeze it per post, because the nickname is shared and a server administrator can change it at any time. |
| `previewBotQueuedNote` | Once Rafii has recorded the bot’s nickname (verifying the connection does that), a post you approve is recorded with it. If Discord shows a different nickname for the bot when the post is due, Rafii holds the post, sends nothing, and asks you to review it again. |
| `previewBotApprovedNote` | Rafii recorded the bot’s nickname in this server when the post was approved. If Discord shows a different nickname when the post is due, the post is held and nothing is sent. |
| `previewWebhookNote` | Every post from this connection is sent with this name. |
| `previewWebhookQueuedNote` | A post you approve keeps the name it was approved with, even if you change the name later. |
| `senderStateHeldNote` | A post that was already approved with a custom name is held, and nothing is sent, while the feature is off. It is never sent under another name, and it stays held after the feature is back on until you act on it in the queue. |
