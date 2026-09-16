# Caption-first intake contract

## Reviewed provider

The reviewed yt-dlp reference is `yt-dlp/yt-dlp@bbc809a1161d3bfca51fa36f59dda35556ee85a0`. It can list and acquire available caption tracks; it is not a translation engine, factual authority, rights grant, or publishing transport.

## Acquisition order

1. Inspect public metadata without media download.
2. List manual and automatic caption tracks.
3. Select the requested-language manual caption.
4. Otherwise select the requested-language automatic caption.
5. If no requested-language track exists, expose available alternatives for review.
6. If no caption exists, return `no_caption` and separately offer an ASR plan.

ASR planning records the exact source, proposed audio boundary, model/version requirement, confidence expectation, retention, terms, and rights decision. It performs no download until the exact operation is separately approved and supported.

## Blocked sources

Keep private, paid, age-gated, DRM-protected, geo-restricted, deleted, login-only, or otherwise access-controlled media blocked unless the creator already has lawful access and an exact reviewed route permits the intended operation. Never borrow credentials or cookies from an unrelated browser profile.

## Transcript quality

Preserve source language, caption source, track ID, ordered start/end times, exact source speech, confidence when available, speaker uncertainty, overlap removal, music-only regions, provider version, and artifact hash. A transcript remains `not translated`, `not fact-checked`, and `not approved for reuse` until those independent states change.
