# Telephone prompts — OpenAI Marin

Current local assets for caller identity. Three new requests were explicitly authorized with a US$0.25 total ceiling, one request per clip and no automatic retries. All three completed. Outbound acceptance is preserved. Actual provider billing was not returned.

Playback: raw G.711 PCMU, 8 kHz mono. Review WAVs: PCM, 24 kHz mono. Source text, bytes and hashes are enforced by `phone/prompt_assets.py`; mismatch prevents playback.

## dial-inbound

Please enter or say your 12-digit agent pairing code. If you enter it on your keypad, press star when you’re done.

Duration: 7.25 seconds. PCMU SHA-256: `8fb13565a41db35a6e19b21825e08afd4ae075dd78d4a982f3a7debe694bc928`.

## dial-inbound-retry

Sorry, that Agent Pairing Code did not connect. Say all 12 digits, then pause. Or enter all 12 digits on your keypad and press star.

Duration: 8.65 seconds. PCMU SHA-256: `ce5becb308870ced06eee6500ebd2625fdb7e25876e93ff8f15480a017b9e0ea`.

## dial-repeat

Welcome back. I’ve sent a secure verification request to your trusted device. Confirm it with Face ID, Touch ID, or your passkey to continue. To use a new Agent Pairing Code instead, press hash.

Duration: 13.25 seconds. PCMU SHA-256: `8f6a325ce4e641f4bc632902990153793784784474161a410b1fd2a9d6e339c8`.

## dial-acceptance

Hi, this is Rafii, your AI assistant. Press one to connect, or simply hang up to decline.

Duration: 5.9 seconds. PCMU SHA-256: `d04165a5566f0bbf5b13ff9a440117cc07612b6abf7bf4fff51df27c2a6d18ed`.

Pre-authentication uses generic Marin. Only the authenticated conversation reads the caller’s Settings voice. Outbound acceptance requires `1`; inbound keypad requires exactly 12 digits followed by `*`, while spoken 12 digits submit on pause without star. `#` clears keypad entry.

Evidence: `docs/design/rafii-live-agent/caller-identity-2026-09-28/`. Original assets, README and text/hashes are preserved there. Cached offline Whisper supports the expected content but has spelling errors on “pairing” and “passkey”; human audition remains a release gate. No deployment or real call in this task.
