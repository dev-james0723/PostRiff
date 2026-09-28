# Rafii voice opening and telephone admission — local implementation

Status: **LOCAL CODE VERIFIED; REVISED INBOUND SELF-INTRODUCTION INSTALLED; NOT DEPLOYED**.
Base: origin/consumer-saas 84165f1, isolated managed worktree `rafii-voice-greeting/James-Au-Studio`.
Three original approved generic Marin TTS requests and one separately approved inbound revision completed using the existing project OpenAI key. No real telephone call, production migration, deployment, or message was made.

## Behavior

- Fresh browser Talk sessions send one opening after both the authenticated start response and `session.started`. Early user speech cancels a pending opening; duplicate events and reconnection do not repeat it. Uses the caller's own display-name first token, falling back to their account first/given/full/name metadata, never workspace owner or email. Missing names use a generic greeting. English/Cantonese/Mandarin honor saved language and account locale for the initial greeting.
- Incoming, explicit outgoing, scheduled and proactive telephone sessions read all six Settings voices (`marin`, `cedar`, `sage`, `verse`, `coral`, `alloy`). Phone opening follows successful admission only. Scheduled/proactive openings explain the reason; ordinary calls ask one short question then listen. Media-generation handoffs do not greet again.
- Inbound callers can say all 12 digits one at a time and pause, or enter 12 digits and press `*`. `#` clears keypad input. Twelve digits alone no longer auto-submit; an overlong number is not truncated into a valid one. Selecting the keypad cancels a competing recognizer. Outbound acceptance continues to use `1`, not an inbound sign-in code.
- Spoken admission uses a separate `gpt-4o-mini-transcribe` request with an in-memory WAV, no account/workspace/history/tools. Maximum 15 seconds per request, three requests per admission, no automatic HTTP retries, existing 45-second admission deadline and three authentication attempts. A code is accepted only through the existing one-use, five-minute DB verifier; no missing digits are inferred. No code/audio is persisted in app transcript or logs. OpenAI processes the audio, as authorized by the user; this does not assert provider-side zero retention.
- Existing operator admission limits include a conservative additional $0.01 STT reserve per admitted connection, including authenticated ones. This is an application estimate, not a provider-enforced hard billing cap. Keypad-only calls may reserve this estimate without using STT.

## Validation

- After installing all three new audio assets, 37 telephone playback/admission/media tests passed (`audio-install-tests.log`). Installed PCMU hashes and review WAV durations match `generation.json`; generator syntax and `git diff --check` passed.
- 150 scoped Python tests passed: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /private/tmp/rafii-phone-env/bin/python -m unittest test_voice_opening test_phone_code_speech test_rafii_inbound test_rafii_dial test_rafii_phone test_rafii_phone_media test_agent_runtime`.
- Guard cleanup recheck passed (15 tests), including the installed Live SDK over loopback.
- 11 frontend unit tests passed: `node --test web/tests/voice-opening.test.cjs web/tests/voice-transcript.test.cjs`.
- Chromium and WebKit: six real-browser scenarios of the actual `voice-session.ts`, with synthetic API/audio transports. API/event ordering, greeting exactly once, caller-first, reconnect and end all passed: `node web/tests/voice-opening-browser.cjs`.
- Disposable PostgreSQL: existing style suite passed; phone lifecycle suite passed with every voice saved through the real Settings API then loaded by the real phone controller. Inbound signed HTTP/WebSocket admission, real DB/code consumption and actual draft editing passed independently for keypad and synthetic spoken recognition. Run `scripts/postriff_pg_suite.py postgres_inbound_phone`; add `RAFII_TEST_CODE_METHOD=spoken` for the speech path. All external providers/models are synthetic.
- `npm run typecheck`, `npm run lint` (0 warnings/errors), and `git diff --check` passed.
- Initial spoken ASGI test found speech arriving during queued prompt playback was discarded. Fixed by arming the bounded code buffer only after signed admission and before playback; the repaired spoken test passes. `phone-settings-postgres.log` retains the initial spoken failure followed by the successful phone Settings suite; `spoken-postgres.log` is the final repaired speech result.

These checks prove routing and admission logic, not real speech recognition accuracy, live GPT-Live greeting/audio quality, handset/network behavior, or production availability. Those remain **validation_unavailable: no live speech/phone validation executed**.

## Fixed recordings — generated and installed locally

The user approved OpenAI processing of short spoken-code audio and exactly three generic Marin TTS generations, without retries, estimated below $0.05. The existing project key was found in the repository's phone-test checkout and passed only in process environment. It was not printed, copied into source, or checkpointed. The earlier missing-key conclusion was incomplete; no new key setup is needed. No deployment or real phone test was authorized.

The original three requests completed once. Historical `generation.json` records their original fingerprints, PCMU hashes and durations (the inbound clip is now superseded by `intro-revision/generation.json`): acceptance 5.9 seconds, inbound 13.05 seconds, retry 9.3 seconds. Actual provider billing was not returned. Exact text is in `src/postriff_phase2/phone/assets/prompts.json`; `scripts/render_phone_prompts.py` remains preview-only by default and blocks uncertain duplicate submissions.

All three old `.mulaw` assets were replaced together; the inbound clip was subsequently updated as described below. Current review WAVs are in `recordings/`. Streaming WAV length headers were normalized locally from received frames, with no regeneration. The generator now performs this normalization too. `audio-validation.json` verifies lengths, mono 24 kHz review format, 8 kHz PCMU byte lengths and no clipped samples. `local-transcription.json` is an offline cached Whisper-tiny transcription of all three recordings; it confirms twelve digits, spoken alternative, keypad plus star, hash reset and outbound one-to-connect. No remote transcription calls were used for this check. Machine transcription does not constitute human audition.

Before authentication the fixed prompt uses generic Marin because caller identity is not yet known; personalized conversation uses Settings after authentication. New source and audio are local and uncommitted. Production remains unchanged. Real spoken-code accuracy, GPT-Live/handset audio and end-to-end PSTN behavior still need a separately authorized live test; human voice-quality review is available through the WAV previews.

## API sources checked

- [GPT-Live: greet before the caller speaks](https://developers.openai.com/api/docs/guides/live-conversations): append instructions after `session.started`, with input audio kept active.
- [OpenAI text to speech](https://developers.openai.com/api/docs/guides/text-to-speech): static natural speech generation with `gpt-4o-mini-tts`, Marin and WAV.
- [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text): isolated transcription endpoint.

## User-requested introduction correction

User clarified that Ravi is the agent's name and requested “Hi, this is Ravi.” instead of “Welcome to Ravi”. The inbound source script now reads:

> Hi, this is Ravi. I'm your AI assistant. Say your twelve-digit phone sign-in code, one digit at a time, then pause. Or enter all twelve digits on your keypad and press star. Press hash to start over.

Only the inbound prompt changes. The user subsequently approved regeneration (“you can regenerate”). One additional `gpt-4o-mini-tts` / Marin request completed using the existing key, without retries. The other two clips were not regenerated. `intro-revision/generation.json` retains the new request fingerprint, duration and PCMU hash; the original receipt was preserved. `intro-revision/validation.json` records offline cached Whisper transcription confirming the exact new introduction and all digit/star/hash instructions. It also verifies 12.9 seconds, mono 24 kHz review WAV, 103200 bytes of 8 kHz PCMU, and zero clipped samples. The installed inbound clip and current review WAV now contain the revised introduction. No deployment or real phone test was performed; human voice-quality review remains available through the preview. Actual provider billing was not returned.
