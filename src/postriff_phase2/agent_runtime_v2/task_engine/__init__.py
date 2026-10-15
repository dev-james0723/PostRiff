"""Rafii's durable task engine (contract CF-3, "EX"; migration 108). Off unless RAFII_AGENT_TASKS_ENABLED and the workspace is in
RAFII_AGENT_TASKS_WORKSPACES; with it off nothing here reads or writes anything and every route answers as today.

    flags        server-enforced flags and the fail-closed allowlist
    model        pure rules: states, legacy mapping, derive(), defaults, effect keys, digests
    store        the 108 rows: tasks, steps, attempts, approvals, receipts, compensations (frozen lock order)
    authz_seam   decide_for_step on every claim (CF-2's when present; today's role rule until then)
    executor     inline and cron executors, the claim/receipt/lease path, recovery and expiry
    approvals    request_approval and the one resolve_approval for every surface
    checkpoints  service-only paused-run state (replaces artifact.pendingRun)
    actions      cancel, retry, undo, continue
    views        TaskV1 shapes and the visibility rules
    http, cron   routes and cron phases
    bridge       the seam with legacy task_state (mirror, projection, adoption)
"""
