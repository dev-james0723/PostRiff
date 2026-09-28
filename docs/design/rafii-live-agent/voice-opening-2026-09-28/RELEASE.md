# Voice opening and admission release

The user accepted the revised “Hi, this is Ravi.” recording and explicitly authorized commit, push and production deployment on 2026-09-28. Scope includes proactive browser/phone greeting, matching authenticated Settings voice, spoken or keypad-plus-star sign-in, and the three approved Marin recordings (one separately approved inbound revision). No migration or account-setting change is needed. Real paid phone/Live tests remain outside this release.

Prior scoped unit, browser and disposable PostgreSQL checks are documented in README.md. The installed inbound revision passed offline transcription, format/hash checks and six inbound tests. Original acceptance/retry asset hashes are unchanged. The release secret scanner initially found the literal mocked synthetic-test-key; its exact test path and hash were reviewed and added to the existing allowlist, without changing runtime credentials or scanning rules.

Commit, CI and deployment results will be recorded after execution. The earlier NOT DEPLOYED statements describe the local validation stage.
