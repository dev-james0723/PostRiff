`dial-acceptance.mulaw` is a stock greeting generated locally with macOS `say`, then
converted with FFmpeg to mono G.711 μ-law at 8 kHz. It contains no user or workspace data:

> Hi, this is Rafii, your A I assistant. Press one to connect, or hang up to decline.

The audio is 5.886 seconds. Dial plays it before Rafii opens a Live session or reads
workspace history. A signed `dtmf` event with digit `1` is required; another digit,
hang-up, or a 20-second timeout ends the call without opening a model session.
Incoming media before acceptance is discarded. This asset is a prompt, not a call recording.
