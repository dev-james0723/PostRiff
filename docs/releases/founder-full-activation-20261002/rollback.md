# Rollback candidate

No deployment or production configuration change has occurred in this run.

Before any release, preserve the current serving deployment and configuration references without exporting values. Current independently observed baseline: `6059664c049bc6eb4da6d533e8926a135ff7e22f`, deployment `dpl_6MgiST6Dnyf7ySDjmkKL5RjetcXX`, stable alias `postriff-phase2-private.vercel.app`.

On a canary regression, stop new email/push/voice/call dispatch using the approved channel policy and flags. Append a new disabled cutover revision; keep earlier approvals and accepted provider IDs. Preserve unknown states, dispatch hashes, leases and receipts. Do not retry uncertain sends or calls.

Return the application alias to the preserved healthy deployment through the normal guarded Vercel flow. Verify its actual SHA, customer health and denied unauthenticated Founder access. Check cron and environment configuration independently: application rollback does not undo their changes automatically.

Keep additive schema 088 and existing Founder enrollment/roles. Do not drop tables, remove tenant/ledger rows, replay old migrations, reset credentials or clear historical unknown costs. Reconcile accepted external effects before resuming. A pending internal identity can be resumed with the same owner/environment and workspace ID.

Staging schema/role checks and an actual rollback rehearsal remain required before production release. The disposable database tests are local proof only.
