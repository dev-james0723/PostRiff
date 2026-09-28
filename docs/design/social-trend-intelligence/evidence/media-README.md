# Local media evidence

These are byte-for-byte copies of the acknowledged receipts and small acceptance logs. `media-evidence-index.json` records their SHA256 hashes and original artifact paths. No large generated fixtures, credentials, or product changes are included.

- `media-core-receipt.json`:74passed,0skips;38actual local runtime tests plus36portable checks, including25actual PostgreSQL tests. Core imported-source hashes were identical before/after execution.
- `media-http-receipt.json`:51portable checks passed,0skips, including29actual PostgreSQL tests. This includes15new HTTP tests (4real SQL) and the earlier36core checks; counts overlap. The receipt preserves all recorded source hashes, the exact `TrendService.media` block hash, and comparison proving the six frozen core implementation/test files unchanged from the core receipt.
- `media-http-regressions.log`:23existing HTTP/service regression tests passed. This supporting run had no independent before/after source-hash capture; that limitation remains explicit in the receipt.

The core receipt SHA256 is `7ec31dc5572afe9b034ddc41718ccb9cda64ac59d85a81eaf35c8b17b39e1f5d`; the HTTP receipt SHA256 is `bb054f3e6cb77c671afdea56fa9f778d9fedfef6497cb6aa1bf459dd50ffaad3`. Both are preserved unchanged. Hashes describe their test-time snapshots; later parent edits to shared modules require their own validation.

The portable entry point `tests/phase2/postgres_trend_media.py` includes the new HTTP module and rejects skipped PostgreSQL tests and003/pr_runtime. Media admission/run uses current authorization, an explicit180s monotonic deadline, and execution outside the service transaction. Manifest GET returns current-authorized metadata and artifact references with a4.5MB response cap; individual current-authorized PNG GET requires a matching SHA256 and size strictly below3MiB. GET never dispatches work; all responses are private/no-store. Existing asset-deletion effects were tested through the real repository transaction.

These receipts prove local SQL execution and locally generated media processing. Grants, session verification and private storage transport are explicit test fixtures. No live provider/model/storage calls, production deployment, or ASR/OCR/semantic qualification is claimed. The media runners stopped and released55438; subsequent parent runs own their own reservation.
