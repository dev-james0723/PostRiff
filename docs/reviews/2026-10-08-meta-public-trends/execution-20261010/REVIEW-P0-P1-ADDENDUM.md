# Meta public discovery — P0/P1 review addendum

Date: 2026-10-10. Reviewer: independent `meta_control` agent. Status: **STATIC_ONLY — cloud validation pending**.

Reviewed worktree: `/Users/ouxianxing/.codex/worktrees/rafii-meta-public-execution/James-Au-Studio`. Observed HEAD: `ccbc2d878e60f2c8f9d7df7e9b52bfb19fcfcfe3`; the file hashes below identify the reviewed working contents independently of that commit.

All five reported P1 findings and the subsequent grant-renewal follow-up are closed in the bounded code sections reviewed. No remaining concrete P0/P1 was found in these sections. This is not a production, provider-access, or test-pass certification.

| Finding | Static closure evidence |
| --- | --- |
| 1. Retention lock inversion | `retention.sweep` takes shared trust as its first transaction operation, before the runtime guard and node/job locks. This removes the reviewed cycle with restore/revocation taking exclusive trust first. |
| 2. Repeated native post rejected as a sequence collision | `store.same_meta_sample_revision` permits the three exact public Meta operations to reuse an unchanged content revision with retrieval-based sequences. `put_observation` checks it under the canonical source lock, returns the prior ID, and preserves the original provenance and retention. Other collisions remain rejected. |
| 3. Empty/queued requests bypass current policy validity | `trend_meta_discovery_request_valid` checks the restore guard, enabled scope, request expiry, active creator membership/profile, policy/contract validity and metric rights, and exact reviewed authorization. Request loading, receipt reads, and purge share it. Empty samples therefore cannot bypass the lifecycle checks through an empty observation array. |
| 4. Cached UI receipt crosses workspace or expiry boundaries | `PublicSources` keys its stateful subtree by workspace; disposed rows ignore asynchronous completions. `RequestReceipt` checks current authorization, source/request expiry, and successful current reads before exposing selections, measurements, or completeness. The wire schema requires `expires_at`. |
| 5. New request prolongs an older canonical sample | Completed receipt expiry is the minimum of the request deadline and canonical observation/node retention, original policy/contract/grant/credential expiry, proof freshness, and applicable observation/policy rights. An already-expired bound makes the receipt unavailable. Canonical membership does not extend original source retention. |
| 6. Renewed grant cannot reacquire unchanged native content | Meta revision identity now includes the immutable policy version; normalized stored-content digest is recorded separately. A new reviewed policy creates a new authorized acquisition node while preserving the old revoked node unchanged. Same-policy overlapping queries still reuse the canonical row. Native source identity, source lock, and app/account quota bucket remain unchanged. |

The review also followed request selection validation, reviewed Facebook Page selection, workspace predicates, runtime request/grant binding, isolated cursors, provider quota reservation, explicit HTTP routes, and result attachment in the worker's ingestion transaction. For renewal, `pipeline._sources` suppresses older native-source sequences and `metrics.latest_revisions` groups by scope/provider/native identity; a fresh acquisition is not a second current native post in metric input. `content_revision_digest` is a digest of normalized stored content, not provider-native edit/version evidence. No additional P0/P1 was identified there. Earlier status/control implementation is outside this addendum's independent review scope.

Regression source was inspected, not executed in this pass: the focused dispatch tests cover lock ordering, distinct-time normalizations, and policy-scoped renewal identities; PostgreSQL tests exercise actual adapter normalization and canonical reuse, changed revisions, empty/queued lifecycle withdrawal, an earlier canonical node deadline shared by two receipts, and same-content reacquisition after grant revocation without rewriting old evidence or resetting its quota bucket; browser tests cover offline expiry, failed reads, authorization loss, and a late submission after workspace switching. No local database, provider, model, or heavy validation ran. Observed `git diff --check` completed with exit code 0. The parent must attach cloud execution results separately.

Test-only follow-up: independently reviewed the later purge assertion change in `tests/phase2/postgres_trend_meta.py`. The purge is global, so the test now counts its bounded eligible candidate set rather than assuming exactly three total requests. It separately requires its own revoked IDs to be eligible and deleted, verifies cascading result removal, and confirms an unrelated active workspace request survives unchanged. Reconstructing the former block reproduced the previously reviewed file hash, confirming this was the only file delta. No new product concern or weakened revocation assertion was identified. The file hash below supersedes its earlier value; this follow-up remains static-only, with the parent-owned cloud retry pending and no new test-pass claim.

Web/cloud-selector follow-up: reviewed the control-character predicate replacement, matching localized accessible names on the three input/select declarations, and explicit NUL/LF/DEL/whitespace/Unicode contract cases. The new character predicate preserves the previous rejection set; no selection or authorization boundary is widened. Reviewed `--web-only`, its package script, and the JCB e2e mapping: the route still requires CI, Linux, and the cloud bootstrap; it runs wire contracts, typecheck, lint, build, and browser checks. `--full` retains the existing Python, secret scan, five PostgreSQL scripts, and web cohort. No deployment or local-heavy fallback was added. No new P0/P1 concern was identified. Python/SQL product hashes remain unchanged; this is a scoped static review, not confirmation of the parent's reported cloud outcomes or the pending web rerun.

## Reviewed SHA-256 snapshot

```text
bfaed161f0d8a71e252bddafdccd1fe395f9323c255121d54a575a1d30f0f3ce  src/postriff_phase2/growth/trends/store.py
de5c4666aec77e72fa04deb5b5983373d6e186242013464af99c152ce87bd127  src/postriff_phase2/growth/trends/retention.py
a6f885b1ccadc0133ecfb0745ad7f1fb01545216bef0d882603b769a088aa43e  src/postriff_phase2/growth/trends/meta_discovery.py
e2d5fde79103f742d40312a261ed18a8c2db2dbd88e4d3c1b611066288449005  migrations/postriff/110_meta_public_trends.sql
6e33f6f11a0663abe9fd46c488ca97bc3859e4b0d87102a5a89427feb88336a2  src/postriff_phase2/growth/trends/providers/meta_runtime.py
495e95da2c9c19b00f10ac66f61a293234467b35414e17a3dd15a1472f8ab074  src/postriff_phase2/growth/trends/providers/meta_public.py
78d82d297eaf963a7aff9a96ec8824d31c06bfcdb8c09de74ef523010292b8ca  src/postriff_phase2/growth/trends/worker.py
9ff3e53c430b4d89473a878052c3298b37252349d505b55a858f9207e18ae8a2  src/postriff_phase2/growth/trends/http.py
2c5d1e72c4df14336f0e9e5a6abd1bcaf0803780beea3df6c65bbc8bb677f116  web/src/features/trends/api.ts
93019af7ef34a975f80bd90ad7c872b457b4a808544533072a1ef4664b8768a1  web/src/features/trends/public-sources.tsx
835480951936acbd005534a45ed7a65a1e79fb888d037d5b819ef20fd70d5258  tests/test_trend_meta_dispatch.py
d16189919294d3e70cb27fbdf4c428d82729fdea5de01e68e84e2a6a26424159  tests/test_trend_meta_discovery.py
55c9bafc3c82b1158dc0c3d75556b4767604965892ccf30825f860830435302c  tests/phase2/postgres_trend_meta.py
3c609f3d46f3a15458b25ba454a4b681a8f817cc38a77a36a8843b1eaa407553  web/tests/trend-meta-discovery.test.cjs
ce8a1d756dc05ddd94b977e637f573708cc2431f1ce587417b739d086e1f685d  web/tests/trend-browser.cjs
0e2dc9a4d8d9899092017af3c1ee0682890be246cda53f0534cdddd3e5c422f9  src/postriff_phase2/growth/trends/pipeline.py
a469db3b25fa70a29d354ad6117180f95780148192951a716bb799da009af948  src/postriff_phase2/growth/trends/metrics.py
aba6d676af64c9cba1be62d47cd6c7d5fbbe927ec9cdf5b3e2c610772abfe541  src/postriff_phase2/growth/trends/membership.py
5e441816fc57bd4c932ecdf0ceb38aae9ebaf27c99ff4ab85a53e647f915e61a  scripts/cloud-meta-validation.sh
1690d95a767e6d306bedd09abc69146b951f10d43ad3e1aac9b340145a97e517  web/package.json
85f5f461b0e9e3bd604c87f9bc57a7e98302a08d5dfaa210a1a2fcb0846fbf2b  .james-cloud-build.json
```

Any change to these files requires review of the changed portions before carrying this disposition forward. Usage/cost for this static review: unknown.
