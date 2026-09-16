# Security and RLS results

## Verified locally

- [Python suite](evidence/all-python.txt): cross-workspace reads, mutations, exports, approvals, account deletion and object IDs rejected; stale versions rejected; expired/revoked sessions rejected; recovery and trial replay tested.
- [RLS execution](evidence/rls-results.txt): two users, 13 public tables including nine object families; direct foreign-ID reads, forged inserts, browser updates/deletes, private Storage writes and browser bootstrap denied. Revoked membership loses workspace and object access. Anonymous reads denied.
- [PostgreSQL repository](evidence/postgres-repository.json): real database persistence, existing alpha command reuse without SQLite, membership isolation, viewer write denial, compare-and-swap and rollback.
- [Source/artifact audit](evidence/local-audit.json): bounded hashes, generalized-template preservation, customer bundle/source credential patterns and documentation links. This is a bounded scan, not a security certification.

RLS tests use a disposable PostgreSQL auth/storage harness. The actual Supabase service, bucket configuration, signed URLs, object deletion, provider secret encryption and deployment need separate validation. SQL writes are unavailable to browser roles even within their own workspace; the trusted API must apply the same membership and content checks before service writes.

## Boundaries and data lifecycle

Loopback HTTP enforces the exact host and origin, a custom mutation guard, bounded JSON bodies, no CORS, no-store responses and script CSP. Phase 2 permits style attributes for selected-image focal positioning only; scripts remain restricted to self. HTTP logs omit request contents and credentials. The local launcher has no enabled external transport.

Media bytes must start with JPEG/PNG signatures and pass a full decoder. The local runtime uses ffprobe/ffmpeg; the hosted function uses pinned Pillow because Vercel does not guarantee those binaries. Both paths reject playlists, SVG uploads and remote references, strip metadata from immutable JPEG renditions, and enforce size/dimension checks. Publication preflight separately enforces aspect, alt text and rights. Artwork SVGs come only from the trusted fixed procedural adapter.

Private exports include the account's own draft/profile/source/artwork/receipt data, including clearly unapproved work, and remain available after trial expiry. They contain no account credential, principal key or provider token. Deletion removes the local workspace and stored image bytes, revokes devices and retains a minimal trial/identity tombstone. An uncertain external outcome cannot be erased as if cancellation had recalled it.

The localhost fixture identity is not production authentication. Hosted credentials, callback handling, storage delivery and a remotely deployed worker have not been security-qualified.
