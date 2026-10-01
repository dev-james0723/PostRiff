"""Launch ceilings for raw-file intake (PRD R-FWR-04) and how lower limits win.

The ceilings below are the most this release will accept. An operator may lower any of them through the environment;
a value above the ceiling is clamped down, never up. At run time the private bucket's own size limit, the approved
transcription route's limits and the source pipeline's text limit (`source_intake.MAX_TEXT`) lower them further.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

AUDIO_MAX_BYTES = 30_000_000
AUDIO_MAX_SECONDS = 600
PDF_MAX_BYTES = 20_000_000
PDF_MAX_PAGES = 100
TEXT_MAX_CHARS = 60_000
TRANSCRIPT_FILE_MAX_CHARS = 150_000     # a pasted SRT/VTT/TXT before its timings are removed
PDF_SECONDS = 12                        # one extraction attempt, enforced by killing the parser process (fits a 20 s cron tick)
TOKEN_SECONDS = 2 * 3600                # Supabase signed upload URLs live two hours
REVIEW_DAYS = 30                        # text never used is deleted with its file after this
RETAIN_DAYS = 30                        # the file is kept this long after a source is created from it
FLAG = "RAFII_SOURCE_UPLOADS_ENABLED"
ROUTE = "RAFII_TRANSCRIPTION_ROUTE"


def truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def environment():
    """The hosted environment through the same preview isolation as every other flag (a broken preview pin
    switches nothing on)."""
    from ..deployment import isolated_environment
    try:
        return isolated_environment(os.environ)
    except ValueError:
        return {}


def _lowered(values, name, ceiling):
    try:
        value = int(str(values.get(name) or ceiling))
    except (TypeError, ValueError):
        value = ceiling
    return max(1, min(ceiling, value))


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    audio_max_bytes: int = AUDIO_MAX_BYTES
    audio_max_seconds: int = AUDIO_MAX_SECONDS
    pdf_max_bytes: int = PDF_MAX_BYTES
    pdf_max_pages: int = PDF_MAX_PAGES
    text_max_chars: int = TEXT_MAX_CHARS
    pdf_seconds: int = PDF_SECONDS
    pending_per_member: int = 3
    pending_per_workspace: int = 6
    active_per_workspace: int = 6
    daily_bytes: int = 300_000_000

    @classmethod
    def from_environment(cls, values=None):
        values = environment() if values is None else values
        from ..coworker.source_intake import MAX_TEXT
        return cls(enabled=truthy(values.get(FLAG)),
                   audio_max_bytes=_lowered(values, "RAFII_SOURCE_UPLOADS_AUDIO_MAX_BYTES", AUDIO_MAX_BYTES),
                   audio_max_seconds=_lowered(values, "RAFII_SOURCE_UPLOADS_AUDIO_MAX_SECONDS", AUDIO_MAX_SECONDS),
                   pdf_max_bytes=_lowered(values, "RAFII_SOURCE_UPLOADS_PDF_MAX_BYTES", PDF_MAX_BYTES),
                   pdf_max_pages=_lowered(values, "RAFII_SOURCE_UPLOADS_PDF_MAX_PAGES", PDF_MAX_PAGES),
                   text_max_chars=min(_lowered(values, "RAFII_SOURCE_UPLOADS_TEXT_MAX_CHARS", TEXT_MAX_CHARS), MAX_TEXT),
                   daily_bytes=_lowered(values, "RAFII_SOURCE_UPLOADS_DAILY_BYTES", 300_000_000))

    def effective(self, bucket_limit=None, route=None):
        """The limits a person is shown and the server enforces: the lowest of this policy, the bucket and the route."""
        audio_bytes, audio_seconds, pdf_bytes = self.audio_max_bytes, self.audio_max_seconds, self.pdf_max_bytes
        if isinstance(bucket_limit, int) and bucket_limit > 0:
            audio_bytes, pdf_bytes = min(audio_bytes, bucket_limit), min(pdf_bytes, bucket_limit)
        if route is not None:
            audio_bytes = min(audio_bytes, int(route.max_bytes))
            audio_seconds = min(audio_seconds, int(route.max_seconds))
        return {"audio": {"maxBytes": audio_bytes, "maxSeconds": audio_seconds},
                "pdf": {"maxBytes": pdf_bytes, "maxPages": self.pdf_max_pages, "maxCharacters": self.text_max_chars},
                "transcript": {"maxCharacters": self.text_max_chars, "maxFileCharacters": TRANSCRIPT_FILE_MAX_CHARS},
                "text": {"maxCharacters": self.text_max_chars}}
