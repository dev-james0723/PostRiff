# Driver interface

PostRiff owns the job lifecycle server-side in `src/postriff_phase2/store.py`: one job per approved destination, sharing a `scheduleId`, each with its own state. No skill and no agent tool may submit; the host does, after the user approves.

`execute(store, job_id, route_record, driver, now=...)` calls `begin`, then `driver.submit(job_id, immutable_payload)` once. It stores only a safe outcome class. Raw exception messages are discarded. `reconcile(...)` calls a separate `driver.inspect(job_id, payload)` and compares evidence with the immutable job.

Drivers return observed evidence including `source=independent_read`, `content_hash`, exact account/destination/native format, observed state/time and provider ID or permalink. This is a trusted adapter assertion: a production driver must derive the observed hash from actual observed fields and must not simply echo the requested hash. Tests use synthetic observations.

Current limitations requiring later implementation: authenticated approval broker, per-platform evidence normalization, ephemeral evidence acceptance, separate media upload lifecycle, cancellation of remote schedules, redaction of returned structured evidence, deliberate-repost workflow and bounded pre-submit retry. Keep corresponding V14 acceptance clauses open.
