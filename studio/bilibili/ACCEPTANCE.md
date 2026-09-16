# Bilibili integration acceptance

Reuse upload_task.py from Misaka-Mikoto-Tech/bililive-auto-upload at 739896c55846c5cad4d61b2d741e7a49577e5e34 and its pinned API dependency at 7148fceba944c4a422f8c15e3758eb0933a4419f. This is an unofficial session-based provider, not OAuth. User explicitly selected this provider.

Required: no credentials in output or content backups; owner-only local connection form; expected UID 3546856139262666 (JAMESAUCREATES) verified before storing credentials and before each submission; exact media hashes and metadata preview; no automatic submission, replay or blind retry; upstream title suffix, forced repost, update and comments disabled; rejected/unknown submissions remain distinct from verified public posts. Use isolated dependencies. Preserve upstream license and attribution.

Test local contracts and upstream payload with mocked network. Live identity requires the owner to enter credentials in the private local form. A live video test requires a selected video and exact publication approval. Do not claim those tests based on fixture results.
