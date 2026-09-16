# Runtime contract and integration boundary

PostRiff owns execution server-side: the tool registry and effect classes in `src/postriff_phase2/tools.py`, and the review/approve chain in `store.py`. `publish` is deliberately absent from the registry. If the host does not expose the capability a step needs, report `runtime_dependency_missing`; never substitute a local runtime.

- `issue_approval(id, [(job_id, payload)], user_session_ref=..., approved_at=..., expires_at=...)` binds the entire execution payload. It is called only after an authenticated human approved that payload.
- `JobStore(path).create(job_id, payload, now=...)` saves a new immutable version in SQLite; duplicate target/version identity is rejected.
- `approve(job_id, receipt, now=...)` validates receipt integrity, type, exact payload, validity period and current source bindings. It cannot turn a recipe receipt into content approval.
- `begin(job_id, route_record, now=...)` atomically checks approval, source bindings, route versions, account lock, parent verification, duplicate history and kill switches. `True` reserves the one execution boundary. `False` means no submission is permitted.
- `set_kill_switch(scope, enabled)` supports global, platform, account and recipe scopes. Derive account scope with `account_scope(payload)`.

The strict canonical serializer accepts ASCII field names and JSON string/bool/null/list/object values plus safe integers. Fractions, unsafe integers and unsupported types fail closed. Costs use integer minor units. Broader JCS numeric support remains a separate requirement.

The storage is a local trusted-operator boundary, not an authentication server. It does not sandbox a malicious driver or implement a credential broker. File permissions and independent production host controls are required before connecting a real transport. Tests use synthetic job/account references and simulated evidence.

News, launch and YouTube announcement jobs require nonempty `source_claim_bindings`, each binding exact claim ID, version and hash. Initialize `SourceLog` and `JobStore` against the **same SQLite file**: approval and begin read current claim lifecycle, evidence and registry within the job transaction. A separate/missing ledger, retraction, superseded claim or registry drift fails closed. This prevents a retraction committed before begin from crossing the submit boundary. It cannot undo an already-submitting request or a remote scheduled post; those require reconciliation and an explicitly approved correction/cancellation workflow. The source classifier and content type remain trusted editorial inputs, not automatic semantic verification.
