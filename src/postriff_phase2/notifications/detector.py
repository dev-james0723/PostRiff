"""Domain events derived from authoritative state (architecture lock N2, deviation D2).

The publishing worker, the campaign worker and billing write state outside `repository.command`, so events cannot
come only from command hooks. `detect()` reads what the application actually holds (job states normalised by
`outcomes.normalize_result`, reviews, channels, automation occurrences, weekly plans, learning proposals,
subscriptions, trials, budgets, security audit rows, engagement threads) and returns the events that state implies,
each with a dedupe key made of the entity id and the state version. Emitting the same event twice is a no-op, so
the detector may run from a command effect (immediately) and from the cron scan (for worker-made changes) alike.

Publishing truth: `publish.verified` only for job state `verified` (never `published` or `provider_accepted`),
`publish.uncertain` for `uncertain`, `publish.failed` for `failed`; a `held` job is a blocked campaign that needs a
new approval. Nothing here reports "done" for work that state does not show as done.
"""
from __future__ import annotations

import time

RECONNECT_STATES = ("token_expired", "reauthorization_required", "scope_missing")
QUEUE_HREF = "/app/queue"


def _channel(state, channel_id):
    return next((c for c in ((state.get("phase2") or {}).get("channels") or []) if c.get("id") == channel_id), {}) or {}


def _last_message(job):
    events = job.get("events") or []
    return (events[-1].get("message") or "")[:200] if events else ""


def from_state(workspace_id, state, now=None):
    now = now or time.time()
    out = []
    phase2 = state.get("phase2") or {}
    for job in phase2.get("jobs") or []:
        manifest = job.get("manifest") or {}
        channel = _channel(state, manifest.get("channelId"))
        common = {"entity_type": "job", "entity_id": job.get("id"), "payload": {"platform": channel.get("platform") or manifest.get("platform"),
                  "account": channel.get("account"), "href": f"{QUEUE_HREF}?job={job.get('id')}", "reason": _last_message(job)}}
        attempts = len(job.get("attempts") or [])
        st = job.get("state")
        if st == "failed":
            out.append({"event_type": "publish.failed", "dedupe_key": f"publish.failed:{job['id']}:{attempts}", **common})
        elif st == "uncertain":
            out.append({"event_type": "publish.uncertain", "dedupe_key": f"publish.uncertain:{job['id']}:{attempts}", **common})
        elif st == "held":
            out.append({"event_type": "campaign.blocked", "dedupe_key": f"job.held:{job['id']}:{len(job.get('events') or [])}",
                        **{**common, "payload": {**common["payload"], "title": "A scheduled post needs a new approval"}}})
        elif st == "verified":
            out.append({"event_type": "publish.verified", "dedupe_key": f"publish.verified:{job['id']}", **common})
        elif st in ("approved", "scheduled"):
            out.append({"event_type": "publish.scheduled", "dedupe_key": f"publish.scheduled:{job['id']}", **common})
    for review in phase2.get("reviews") or []:
        if review.get("status") == "needs_review":
            manifest = review.get("manifest") or {}
            channel = _channel(state, manifest.get("channelId"))
            out.append({"event_type": "campaign.approval_required", "dedupe_key": f"approval_required:{review['id']}", "entity_type": "review",
                        "entity_id": review["id"], "payload": {"platform": channel.get("platform"), "account": channel.get("account"), "href": QUEUE_HREF}})
    for channel in phase2.get("channels") or []:
        connection = channel.get("connectionState")
        expired = channel.get("configured") and not channel.get("revoked") and isinstance(channel.get("expiresAt"), (int, float)) and 0 < channel["expiresAt"] < now
        if connection in RECONNECT_STATES or expired:
            marker = connection or f"expired:{int(channel['expiresAt'])}"
            out.append({"event_type": "channel.reconnect_required", "dedupe_key": f"reconnect:{channel.get('id')}:{marker}", "entity_type": "channel",
                        "entity_id": channel.get("id"), "payload": {"platform": channel.get("platform"), "account": channel.get("account"), "href": "/app/channels"}})
    planning = ((state.get("raffi") or {}).get("campaignPlanning") or {})
    tasks = {t.get("id"): t for t in planning.get("recurringTasks") or []}
    for occurrence in planning.get("occurrences") or []:
        oid, lifecycle = occurrence.get("id"), occurrence.get("lifecycle")
        task = tasks.get(occurrence.get("taskId")) or {}
        base = {"entity_type": "automation_run", "entity_id": oid, "payload": {"recipeName": (task.get("name") or task.get("title") or "")[:80], "href": "/app/automations"}}
        items = occurrence.get("items") or []
        if lifecycle == "drafted" and any(i.get("state") == "ready_for_review" for i in items):
            out.append({"event_type": "campaign.drafts_ready", "dedupe_key": f"drafts_ready:{oid}", **{**base, "payload": {**base["payload"], "count": sum(1 for i in items if i.get("state") == "ready_for_review"), "href": QUEUE_HREF}}})
        if lifecycle in ("failed", "source_unavailable"):
            out.append({"event_type": "automation.failed", "dedupe_key": f"automation.failed:{oid}", **{**base, "payload": {**base["payload"], "reason": (occurrence.get("reason") or "")[:200]}}})
        if lifecycle == "skipped":
            out.append({"event_type": "automation.completed", "dedupe_key": f"automation.skipped:{oid}", **{**base, "payload": {**base["payload"], "reason": (occurrence.get("reason") or "Nothing worth posting was found.")[:200]}}})
        if items and all(i.get("state") in ("published", "rejected", "skipped") for i in items) and any(i.get("state") == "published" for i in items):
            out.append({"event_type": "automation.completed", "dedupe_key": f"automation.completed:{oid}", **base})
        waiting = [i for i in items if i.get("state") == "ready_for_review"]
        review_sent = (occurrence.get("notices") or {}).get("reviewSentAt")
        if waiting and isinstance(review_sent, (int, float)):   # the worker asks once, at the review time (legacy review_ready)
            out.append({"event_type": "campaign.approval_required", "dedupe_key": f"automation_review:{oid}:{int(review_sent)}",
                        **{**base, "payload": {**base["payload"], "count": len(waiting), "platform": ", ".join(sorted({str(i.get("platform")) for i in waiting if i.get("platform")})),
                                               "href": QUEUE_HREF}}})
        for item in items:
            if item.get("state") == "ready_for_review" and item.get("reason") and isinstance(item.get("changedAt"), (int, float)):
                # An approval was voided (the draft changed, or the approver lost the right): a fresh request of its own.
                out.append({"event_type": "campaign.approval_required", "dedupe_key": f"approval_again:{oid}:{item.get('key')}:{int(item['changedAt'])}",
                            **{**base, "payload": {**base["payload"], "platform": item.get("platform"), "reason": (item.get("reason") or "")[:200], "href": QUEUE_HREF}}})
            if item.get("state") == "failed":
                out.append({"event_type": "publish.failed", "dedupe_key": f"item_failed:{oid}:{item.get('key')}:{int(item.get('changedAt') or 0)}",
                            **{**base, "payload": {**base["payload"], "platform": item.get("platform"), "reason": (item.get("reason") or "")[:200]}}})
            if item.get("state") == "approval_expired":
                out.append({"event_type": "campaign.blocked", "dedupe_key": f"approval_expired:{oid}:{item.get('key')}", **{**base, "payload": {**base["payload"], "title": "An approval expired", "reason": (item.get("reason") or "")[:200]}}})
            if item.get("state") == "platform_disconnected":
                out.append({"event_type": "channel.reconnect_required", "dedupe_key": f"reconnect_item:{oid}:{item.get('key')}", **{**base, "payload": {**base["payload"], "reason": (item.get("reason") or "")[:200], "href": "/app/channels"}}})
    weekly = ((state.get("coworker") or {}).get("weekly") or {})
    for week in weekly.get("weeks") or []:
        if week.get("state") == "ready_for_review":
            out.append({"event_type": "campaign.week_ready", "dedupe_key": f"week_ready:{week['id']}", "entity_type": "week_plan", "entity_id": week["id"],
                        "payload": {"weekOf": week.get("weekOf"), "count": sum(1 for s in week.get("slots") or [] if s.get("status") in ("ready", "needs_revision")),
                                    "href": f"/app/weekly?week={week['id']}"}})
        elif week.get("state") in ("needs_input", "needs_source", "needs_asset", "channel_unavailable", "approval_expired"):
            out.append({"event_type": "campaign.blocked", "dedupe_key": f"week_blocked:{week['id']}:{week['state']}", "entity_type": "week_plan", "entity_id": week["id"],
                        "payload": {"weekOf": week.get("weekOf"), "title": "Next week needs you", "reason": week.get("blockedReason") or week["state"],
                                    "href": f"/app/weekly?week={week['id']}"}})
    for record in (state.get("coworker") or {}).get("sourceCampaigns") or []:
        if record.get("status") in ("needs_input", "needs_source"):
            reason = ("The source didn't contain facts Rafii could use. Add a source with the facts, or tell Rafii what to say."
                      if record["status"] == "needs_source" else "Rafii needs one answer before it can draft this campaign.")
            out.append({"event_type": "research.needs_input", "dedupe_key": f"source_campaign_input:{record.get('id')}:{record['status']}", "entity_type": "source_campaign",
                        "entity_id": record.get("id"), "payload": {"reason": reason, "href": "/app/weekly"}})
    jobs = phase2.get("jobs") or []
    used = {m.get("id") for j in jobs for m in ((j.get("manifest") or {}).get("media") or []) if isinstance(m, dict)}
    for asset in phase2.get("assets") or []:
        lineage = asset.get("lineage") or {}
        if asset.get("origin") == "rafii_agent" and not asset.get("deleted") and asset.get("id") not in used:
            out.append({"event_type": "asset.review_required", "dedupe_key": f"asset_review:{asset.get('id')}", "entity_type": "asset", "entity_id": asset.get("id"),
                        "payload": {"platform": lineage.get("platform") or "a post", "href": "/app/library"}})
    return out


def from_database(cur, workspace_id, now=None):
    """Events implied by relational state: learning proposals, billing, trials, budgets, security, engagement."""
    now = now or time.time()
    out = []
    cur.execute("SELECT id::text, extract(epoch from created_at) FROM public.pr_memory_proposals WHERE workspace_id=%s AND status='pending' AND created_at > now() - interval '30 days'", (workspace_id,))
    for proposal_id, _created in cur.fetchall():
        out.append({"event_type": "learning.preference_proposed", "dedupe_key": f"preference_proposed:{proposal_id}", "entity_type": "memory_proposal", "entity_id": proposal_id,
                    "payload": {"href": "/app/workspace/memory"}})
    cur.execute("""SELECT status, extract(epoch from last_event_at), extract(epoch from current_period_end), extract(epoch from updated_at),
                          coalesce(provider_subscription_id, plan_terms_id) FROM public.pr_subscriptions WHERE workspace_id=%s""", (workspace_id,))
    sub = cur.fetchone()
    if sub:
        status, last_event, period_end, updated, subscription = sub
        stamp = int(last_event or updated or 0)
        if status == "past_due":
            out.append({"event_type": "billing.payment_failed", "dedupe_key": f"payment_failed:{workspace_id}:{stamp}", "entity_type": "subscription", "entity_id": workspace_id,
                        "payload": {"href": "/app/account/billing"}})
        elif status == "active" and updated and now - float(updated) < 2 * 86400:
            # Keyed on the subscription itself: a renewal rewrites updated_at and the period end, but is not a new activation.
            out.append({"event_type": "billing.subscription_active", "dedupe_key": f"subscription_active:{workspace_id}:{subscription}", "entity_type": "subscription",
                        "entity_id": workspace_id, "payload": {"href": "/app/account/billing"}})
    cur.execute("""SELECT extract(epoch from t.expires_at) FROM public.pr_trials t JOIN public.pr_memberships m ON m.user_id=t.user_id AND m.workspace_id=%s AND m.role='owner'
                   LEFT JOIN public.pr_subscriptions s ON s.workspace_id=%s WHERE (s.status IS NULL OR s.status='trial')
                   AND t.expires_at > now() AND t.expires_at < now() + interval '3 days'""", (workspace_id, workspace_id))
    for (expires,) in cur.fetchall():
        out.append({"event_type": "billing.trial_ending", "dedupe_key": f"trial_ending:{workspace_id}:{int(expires)}", "entity_type": "trial", "entity_id": workspace_id,
                    "payload": {"endsAt": int(expires), "href": "/app/account/billing"}})
    cur.execute("SELECT scope, extract(epoch from window_start), warn_usd_micro, spent_usd_micro + reserved_usd_micro FROM public.pr_budgets WHERE scope = %s AND status='approved'",
                (f"workspace:{workspace_id}",))
    for scope, window, warn, used in cur.fetchall():
        if warn and used >= warn:
            out.append({"event_type": "budget.threshold_reached", "dedupe_key": f"budget:{scope}:{int(window or 0)}", "entity_type": "budget", "entity_id": scope,
                        "payload": {"href": "/app/account/billing"}})
    cur.execute("""SELECT t.id::text, t.text, t.author_handle, t.provider FROM public.pr_audience_threads t
                   WHERE t.workspace_id=%s AND t.tombstoned_at IS NULL AND t.ingested_at > now() - interval '3 days'
                   AND NOT EXISTS (SELECT 1 FROM public.pr_reply_drafts d WHERE d.thread_id=t.id AND d.status IN ('approved','submitting','submitted','verified'))
                   ORDER BY t.ingested_at DESC LIMIT 50""", (workspace_id,))
    from ..coworker.engagement import classify
    for thread_id, text, author, provider in cur.fetchall():
        category = classify(text)
        if category in ("question", "complaint", "lead"):
            out.append({"event_type": "engagement.needs_attention", "dedupe_key": f"engagement:{thread_id}", "entity_type": "audience_thread", "entity_id": thread_id,
                        "payload": {"platform": provider, "reason": category, "href": "/app/inbox"}})
    return out


def security_events(cur, since_seconds=86400):
    """Person-level security events from the audit log (no workspace): new devices and account changes."""
    cur.execute("""SELECT a.id::text, a.actor::text, a.kind FROM public.pr_audit_events a JOIN public.pr_profiles p ON p.user_id = a.actor AND p.deleted_at IS NULL
                   WHERE a.kind IN ('session.alerted','mfa.enabled','mfa.disabled','session.revoked_others')
                   AND a.at > now() - make_interval(secs => %s) AND a.actor IS NOT NULL ORDER BY a.at DESC LIMIT 500""", (since_seconds,))
    out = []
    for audit_id, actor, kind in cur.fetchall():
        event_type = "security.new_device" if kind == "session.alerted" else "security.account_change"
        out.append({"event_type": event_type, "dedupe_key": f"{event_type}:{audit_id}", "user_id": actor, "entity_type": "audit_event", "entity_id": audit_id,
                    "payload": {"title": {"session.alerted": "A new device signed in", "mfa.enabled": "Two-step sign-in was turned on", "mfa.disabled": "Two-step sign-in was turned off",
                                          "session.revoked_others": "Other sessions were signed out"}[kind], "href": "/app/account/security"}})
    return out
