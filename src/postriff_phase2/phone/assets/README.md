# Telephone prompts — OpenAI Marin

**Introduction revised:** The user approved one additional inbound generation. Its current opening is “Hi, this is Ravi. I'm your AI assistant.” The replacement was installed locally after offline transcription and format validation. See `intro-revision/generation.json` and `intro-revision/validation.json` in the evidence folder. The original three-request receipt remains historical. Total approved generation calls: four, without retries.

All three shipped `.mulaw` assets were generated with `gpt-4o-mini-tts`, voice `marin`, on 2026-09-28 from the generic scripts in `prompts.json`. They replace the earlier macOS voices. No account or workspace data was submitted. The original three approved requests completed without retries, followed by one separately approved inbound revision; actual provider billing was not returned.

Playback format: raw G.711 mu-law, 8 kHz, mono. The review WAVs are 24 kHz mono PCM, with normalized length headers. Offline cached Whisper transcription confirms the spoken-code and keypad/star instructions. Signal checks found no clipped samples. This is machine content validation, not a human audition or a real handset test.

## dial-acceptance

Hi, this is Rafii, your AI assistant. Press one to connect, or simply hang up to decline.

Duration: 5.9 seconds. PCMU SHA-256: `d04165a5566f0bbf5b13ff9a440117cc07612b6abf7bf4fff51df27c2a6d18ed`.

## dial-inbound

Hi, this is Ravi. I'm your AI assistant. Say your twelve-digit phone sign-in code, one digit at a time, then pause. Or enter all twelve digits on your keypad and press star. Press hash to start over.

Duration: 12.9 seconds. PCMU SHA-256: `d55a27719ad75fb026c47a8a9d5451b58126b45af79d874e1ce2c751c697f48c`.

## dial-inbound-retry

Sorry, that code did not connect. Say all twelve digits again, one at a time, then pause. Or enter them on your keypad and press star.

Duration: 9.3 seconds. PCMU SHA-256: `818acee53570533f747185f67d9500e856c1dd54323c0fb73789ae6ff3e82aee`.

The pre-authentication prompt uses generic Marin because identity is not yet verified. The authenticated conversation reads the caller’s Settings voice. Outbound acceptance requires `1`; inbound callers speak 12 digits and pause or enter 12 digits and submit with `*`. `#` resets keypad entry.

Evidence and review WAVs: `docs/design/rafii-live-agent/voice-opening-2026-09-28/`. Assets are installed locally; no deployment or live telephone test was performed.
