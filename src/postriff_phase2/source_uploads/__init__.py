"""Bounded raw-file intake (RAFII Product Growth PRD R-FWR-04, G1-INTAKE).

A PDF or an audio recording goes from the browser straight to private storage through a signed URL (function bodies
never carry the file). The server verifies the stored bytes (size, sha256, sniffed type, audio duration), a durable
leased job extracts the PDF's text or transcribes the audio through an approved, quoted route, the person reviews and
corrects that text, and only then does it become a canonical source with approved statements. Source text is data,
never instructions. Everything is off unless RAFII_SOURCE_UPLOADS_ENABLED is set; audio needs RAFII_TRANSCRIPTION_ROUTE.

Modules: limits (policy), sniff (content and duration), pdf_text (bounded extractor), transcribe (provider boundary),
store (rows), service (operations), jobs (leased worker + retention), http (routes), agent_tools (typed tools).
"""
