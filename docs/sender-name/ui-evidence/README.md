# UI evidence: customer Discord sender names

Screenshots taken by the browser acceptance run of `web/tests/discord-sender-name-browser.cjs` at head `da378659` (Chromium 141.0.7390.37, headless, Linux sandbox). Every picture is of the real app (Next.js dev server) with synthetic API answers: no Discord, no account, no real name or token anywhere in them. The names in the pictures are made up.

## How they were produced

```
cd web
CI=true RAFII_DISCORD_SYNTHETIC_FENCE=1 RAFII_TEST_CHROMIUM=/opt/pw-browsers/chromium \
  RAFII_EVIDENCE_DIR=../docs/sender-name/ui-evidence node tests/discord-sender-name-browser.cjs
```

The run covers four locale and width combinations (English at 1280 and 390 px, Traditional Chinese at 390 px, Simplified Chinese at 1280 px); the harness takes each picture named below from the combination that its file name states, as the run goes. Every file in this folder comes from one complete run that passed all of its cases (the receipt says `pass`, four combinations of 86 cases and five once-per-run cases). The dialog pictures show the dialog alone; the Queue picture is a strip of the page around the button.

## What each one shows

| File | Language | Width (px) | What it shows |
| --- | --- | --- | --- |
| `en-1280-bot-editor.png` | English | 1280 | Bot server-nickname editor: what the change affects (the shared nickname, every connection in that server), the rules, the counter, the preview with the notes that everyone using the bot sees the nickname and that an approved post is held if the nickname differs when it is due, the confirmation box, the warning about posts approved under the old nickname, and Verify connection. |
| `en-1280-schedule-dialog-preview.png` | English | 1280 | The Schedule dialog with the Discord preview of the chosen draft: author, APP tag, planned time and the draft's line breaks. |
| `en-1280-state-person-missing-manage-nicknames.png` | English | 1280 | The Discord account that installed the bot lacks the Manage Nicknames permission: the explanation, the next step and Check again (a read, never a second write). |
| `en-1280-webhook-editor-dark-app.png` | English | 1280 | The app itself in the dark colour scheme (`prefers-color-scheme: dark`): the preview follows it without being asked. |
| `en-1280-webhook-editor-dark-preview.png` | English | 1280 | The same editor with the preview switched to the dark theme (the preview has its own Dark and Light switch). |
| `en-1280-webhook-editor-light-preview.png` | English | 1280 | Webhook sender-name editor with the Discord preview in the light theme. The name in the field is the author of the preview message, next to the APP tag; the round picture is a placeholder and the notes say the avatar cannot be customised here. |
| `en-390-queue-held-nickname.png` | English | 390 | A strip of the Queue: a bot post held because the bot's nickname changed after approval, the explanation in the person's language, and the "Verify connection" button. |
| `en-390-state-bot-nickname-disabled.png` | English | 390 | A read-only explanation: changing the bot's nickname is switched off, why, and what to do. No error styling, no retry button, nothing to press that cannot work; Save is off and says why. |
| `zh-Hans-1280-webhook-editor-dark-preview.png` | Simplified Chinese | 1280 | The same editor with the preview switched to the dark theme (the preview has its own Dark and Light switch). |
| `zh-Hans-1280-webhook-editor-light-preview.png` | Simplified Chinese | 1280 | Webhook sender-name editor with the Discord preview in the light theme. The name in the field is the author of the preview message, next to the APP tag; the round picture is a placeholder and the notes say the avatar cannot be customised here. |
| `zh-Hant-390-bot-editor.png` | Traditional Chinese | 390 | Bot server-nickname editor: what the change affects (the shared nickname, every connection in that server), the rules, the counter, the preview with the notes that everyone using the bot sees the nickname and that an approved post is held if the nickname differs when it is due, the confirmation box, the warning about posts approved under the old nickname, and Verify connection. |
| `zh-Hant-390-queue-held-nickname.png` | Traditional Chinese | 390 | A strip of the Queue: a bot post held because the bot's nickname changed after approval, the explanation in the person's language, and the "Verify connection" button. |
| `zh-Hant-390-schedule-dialog-preview.png` | Traditional Chinese | 390 | The Schedule dialog with the Discord preview of the chosen draft: author, APP tag, planned time and the draft's line breaks. |
| `zh-Hant-390-state-edit-pending.png` | Traditional Chinese | 390 | An earlier nickname change is still being confirmed: the explanation, how long to wait, the clock time, and Check again which stays off until then. |

## Limits

* They show what the page looks like in this sandbox, not what Discord shows. The preview is an imitation of Discord's message layout; see `../UI-ACCEPTANCE.md`, section 4, and the owner's checks in section 5.
* The sandbox browser has no web fonts and uses fallback fonts, so letterforms differ from production; layout, wording, colours and states are what they show.
* There is no screenshot of "nothing": at the opening every sender-name switch is off and the connection cards show no sender-name control at all, which the run asserts (`card-nothing-when-off`) instead of picturing.
* The JSON receipt of the run (`.depot/discord-sender-name-browser/results.json`) is not committed; it lists case names only.
