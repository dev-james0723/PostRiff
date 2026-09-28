`dial-acceptance.mulaw` is a stock greeting generated locally with macOS `say`, then
converted with FFmpeg to mono G.711 μ-law at 8 kHz. It contains no user or workspace data:

> Hi, this is Rafii, your A I assistant. Press one to connect, or hang up to decline.

The audio is 5.886 seconds. Dial plays it before Rafii opens a Live session or reads
workspace history. A signed `dtmf` event with digit `1` is required; another digit,
hang-up, or a 20-second timeout ends the call without opening a model session.
Incoming media before acceptance is discarded. This asset is a prompt, not a call recording.

The inbound prompts use the same local macOS `say` (Samantha) → FFmpeg conversion:

- `dial-inbound.mulaw` (9.26475 seconds): “Welcome to Rafii, your A I assistant. Open Rafii and create a phone sign in code. Enter all twelve digits on your keypad. Press star to start over.”
- `dial-inbound-retry.mulaw` (4.77175 seconds): “That code could not connect. Check your code in Rafii and try again, or hang up.”

They contain no account data. The twelve-digit, five-minute, single-use web code is
required within 45 seconds (at most three attempts). Incoming speech is discarded
until admission succeeds. No model or paid speech-generation service generated these assets.
