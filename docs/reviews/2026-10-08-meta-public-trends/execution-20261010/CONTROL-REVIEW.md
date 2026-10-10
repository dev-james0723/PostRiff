# Independent control review — 2026-10-10

Reviewer: `meta_storage`, independently reviewing `meta_control.py` and its focused tests. Static review only; no production changes, provider traffic, token diagnostics, or PostgreSQL execution by this reviewer.

| Reviewed file | SHA-256 |
| --- | --- |
| `src/postriff_phase2/growth/trends/providers/meta_control.py` | `5a8cd22fc399767fd41140240ba129daf2c62b300080b89362a9daaa06cc8dba` |
| `tests/test_trend_meta_control.py` | `f0b9819b286fedaebb4f1284b358445e3d16e7334e744f23ab571f519909ca82` |

The earlier processing-rights findings are resolved in this snapshot: both independent App Review and consent artifacts bind policy identity, workspace scope, operation, rights digest, and a strict retention ceiling before custody writes. Registration copies the policy before reading evidence and derives an immutable, exact reviewed-policy capsule; client selection cannot supply that capsule. Quota rules match independent review records. Dedicated encrypted credentials, short-lived diagnostic binding, fresh immutable renewals, targeted secret erasure, and no automatic source activation are represented in the implementation and 22 synthetic test methods.

**Qualified signoff — one concurrency finding remains.** Renewal currently acquires the exclusive trust fence and previous grant row before taking `pr_workspaces FOR SHARE`. This reverses the workspace-before-trust order reported for hosted workspace deletion and can deadlock with deletion. Acquire/validate the workspace row before the renewal trust fence and cover that ordering in regression tests. Reported to the parent and control owner; this reviewer made no code changes.

Both reviewed files parse successfully. The tests use a synthetic storage recorder; their presence does not prove PostgreSQL constraints or concurrency. Parent cloud CI run `0lb567l0hs` was still running when this receipt was written. This is not a test-pass or release approval.

Live OAuth/token diagnostics, safe diagnostic transport, actual per-operation Meta App Review approval, genuine third-party public reads, and production acceptance remain **unverified**. The module explicitly reports `blocked_safe_diagnostic_transport_unverified` and `awaiting_live_public_read`; synthetic records do not establish either live capability or provider permission.

## Superseding signoff after renewal repair

The concurrency finding above is **resolved** in the following independently reread snapshot. Registration now first locks and checks the workspace inside its transaction, then acquires the renewal trust fence and previous grant. The new regression asserts this order and proves a deleting/unavailable workspace cannot reach renewal locks or encryption. No unresolved blocking finding remains in this scoped static review.

| Reviewed file | Superseding SHA-256 |
| --- | --- |
| `src/postriff_phase2/growth/trends/providers/meta_control.py` | `b54ea65809c4a0da35ff7a179c294dc7904fd03999f1aba7f5cbbd5a457e6f2d` |
| `tests/test_trend_meta_control.py` | `43e5670ebc77012323f42c615516f823672727716607fea2fab5c244219ca8f9` |

Reviewer independently verified both hashes, successful AST parsing, and 23 synthetic test methods. The control owner reported observed RED for the new order regression followed by all 23 focused tests passing; this reviewer did not repeat that execution. Full cloud CI remains a separate parent-owned gate, and the live OAuth/diagnostics/App Review/public-read limitations above remain unchanged.
