"""Preference learning on the hosted repository (design §5.1, §6): capture the events a command implies
inside that command's transaction, record what the worker published, keep the tables tidy, export them.

Nothing here writes workspace state, and nothing here decides anything. The tables come from migration
010; service code writes them, members read their own workspace's rows through the API. A capture that
fails (for example before the migration is applied) is rolled back to a savepoint and counted, so the
command that caused it still succeeds and the cron result shows that learning is not recording.
"""
from __future__ import annotations

import json
import time
import uuid

from postriff_alpha import learning
from postriff_alpha.domain import AlphaError
from . import learning_signals as signals

TTL_SECONDS = signals.EVENT_TTL_DAYS * 86400
EVENT_COLUMNS = "id::text,actor::text,kind,subject,scope,features,voice_revision,style_revision,extract(epoch from created_at),extract(epoch from expires_at),consumed_by::text"


def _row(values):
    keys = ("id", "actor", "kind", "subject", "scope", "features", "voiceRevision", "styleRevision", "at", "expiresAt", "consumedBy")
    record = dict(zip(keys, values))
    record["at"], record["expiresAt"] = float(record["at"]), float(record["expiresAt"])
    return record


def insert_events(cur, workspace_id, events):
    """Append events; each carries an epoch `at`. Returns how many were written."""
    written = 0
    for event in events:
        at = float(event.get("at") or 0)
        cur.execute(
            "INSERT INTO public.pr_learning_events(workspace_id,actor,kind,subject,scope,features,voice_revision,style_revision,created_at,expires_at) "
            "VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,to_timestamp(%s),to_timestamp(%s))",
            (workspace_id, event.get("actor"), event["kind"], json.dumps(event.get("subject") or {}), json.dumps(event.get("scope") or {}),
             json.dumps(event.get("features") or {}), event.get("voiceRevision"), int(event.get("styleRevision") or 0), at, at + TTL_SECONDS))
        written += 1
    return written


def guarded_insert(cur, workspace_id, events, failures=None):
    """Insert inside a savepoint so a failure never aborts the command's own transaction."""
    if not events:
        return 0
    mark = "learning_" + uuid.uuid4().hex[:8]
    cur.execute(f"SAVEPOINT {mark}")
    try:
        written = insert_events(cur, workspace_id, events)
    except Exception as error:  # noqa: BLE001 - the command must not fail because learning could not record
        cur.execute(f"ROLLBACK TO SAVEPOINT {mark}")
        if failures is not None:
            failures.append(type(error).__name__)
        return 0
    cur.execute(f"RELEASE SAVEPOINT {mark}")
    return written


def record_published(cur, workspace_id, job, now, failures=None):
    return guarded_insert(cur, workspace_id, [signals.published_event(job, None, now)], failures)


def list_events(cur, workspace_id, limit=500, unconsumed_only=False):
    cur.execute(f"SELECT {EVENT_COLUMNS} FROM public.pr_learning_events WHERE workspace_id=%s" + (" AND consumed_by IS NULL" if unconsumed_only else "") + " ORDER BY seq LIMIT %s", (workspace_id, limit))
    return [_row(values) for values in cur.fetchall()]


def sweep(cur, now=None):
    """Cron: drop events past their retention, expire proposals nobody decided."""
    cur.execute("DELETE FROM public.pr_learning_events WHERE expires_at < " + ("to_timestamp(%s)" if now is not None else "now()"), (now,) if now is not None else ())
    dropped = cur.rowcount
    cur.execute("UPDATE public.pr_memory_proposals SET status='expired' WHERE status='pending' AND expires_at < " + ("to_timestamp(%s)" if now is not None else "now()"), (now,) if now is not None else ())
    return {"eventsDropped": dropped, "proposalsExpired": cur.rowcount}


def export_files(cur, workspace_id):
    """The learning tables as files for the workspace export: ids and numbers, never draft text."""
    files = {"learning/events.jsonl": "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in list_events(cur, workspace_id, limit=20000))}
    for name, table in (("learning/proposals.json", "pr_memory_proposals"), ("learning/versions.json", "pr_memory_versions")):
        cur.execute(f"SELECT row_to_json(t) FROM (SELECT * FROM public.{table} WHERE workspace_id=%s ORDER BY 1) t", (workspace_id,))
        files[name] = json.dumps([values[0] for values in cur.fetchall()], ensure_ascii=False, indent=2, default=str)
    return files


PROPOSAL_COLUMNS = "id::text,scope_key,op,source,body,status,decided_by::text,extract(epoch from decided_at),extract(epoch from created_at),extract(epoch from expires_at)"
VERSION_COLUMNS = "id::text,scope_key,body,status,proposal_id::text,confirmed_by::text,extract(epoch from valid_from),extract(epoch from valid_to)"
DECISIONS = {"remember": "remembered", "edit": "edited", "dismiss": "dismissed", "post_only": "post_only"}
SUPPRESS_SECONDS = 90 * 86400


def _proposal(values):
    keys = ("id", "scopeKey", "op", "source", "body", "status", "decidedBy", "decidedAt", "at", "expiresAt")
    record = dict(zip(keys, values))
    for key in ("decidedAt", "at", "expiresAt"):
        record[key] = float(record[key]) if record[key] is not None else None
    return record


def _version(values):
    keys = ("id", "scopeKey", "body", "status", "proposalId", "confirmedBy", "validFrom", "validTo")
    record = dict(zip(keys, values))
    for key in ("validFrom", "validTo"):
        record[key] = float(record[key]) if record[key] is not None else None
    return record


def pending_proposals(cur, workspace_id):
    cur.execute(f"SELECT {PROPOSAL_COLUMNS} FROM public.pr_memory_proposals WHERE workspace_id=%s AND status='pending' ORDER BY created_at, id", (workspace_id,))
    return [_proposal(values) for values in cur.fetchall()]


def recent_proposals(cur, workspace_id, limit=20):
    cur.execute(f"SELECT {PROPOSAL_COLUMNS} FROM public.pr_memory_proposals WHERE workspace_id=%s AND status<>'pending' ORDER BY decided_at DESC NULLS LAST, created_at DESC LIMIT %s", (workspace_id, limit))
    return [_proposal(values) for values in cur.fetchall()]


def load_proposal(cur, workspace_id, proposal_id):
    cur.execute(f"SELECT {PROPOSAL_COLUMNS} FROM public.pr_memory_proposals WHERE workspace_id=%s AND id::text=%s", (workspace_id, str(proposal_id)))
    values = cur.fetchone()
    if values is None:
        raise AlphaError("Proposal unavailable.", 404)
    return _proposal(values)


def versions(cur, workspace_id):
    cur.execute(f"SELECT {VERSION_COLUMNS} FROM public.pr_memory_versions WHERE workspace_id=%s ORDER BY valid_from, id", (workspace_id,))
    return [_version(values) for values in cur.fetchall()]


def suppressed(cur, workspace_id, scope_key, now):
    """A dismissed proposal keeps its scope quiet for 90 days (design §5.3)."""
    cur.execute("SELECT 1 FROM public.pr_memory_proposals WHERE workspace_id=%s AND scope_key=%s AND status='dismissed' AND decided_at > to_timestamp(%s) LIMIT 1", (workspace_id, scope_key, now - SUPPRESS_SECONDS))
    return cur.fetchone() is not None


def dismissed_keys(cur, workspace_id, now):
    cur.execute("SELECT DISTINCT scope_key FROM public.pr_memory_proposals WHERE workspace_id=%s AND status='dismissed' AND decided_at > to_timestamp(%s)", (workspace_id, now - SUPPRESS_SECONDS))
    return {values[0] for values in cur.fetchall()}


def recent_decisions(cur, workspace_id, limit=10):
    cur.execute("SELECT status FROM public.pr_memory_proposals WHERE workspace_id=%s AND decided_at IS NOT NULL ORDER BY decided_at DESC LIMIT %s", (workspace_id, limit))
    return [values[0] for values in cur.fetchall()]


def automatic_proposals_since(cur, workspace_id, since):
    cur.execute("SELECT count(*) FROM public.pr_memory_proposals WHERE workspace_id=%s AND source IN ('deterministic','model','performance') AND created_at > to_timestamp(%s)", (workspace_id, since))
    return cur.fetchone()[0]


def owners(cur, workspace_id):
    cur.execute("SELECT user_id::text FROM public.pr_memberships WHERE workspace_id=%s AND role='owner' AND status='active'", (workspace_id,))
    return {values[0] for values in cur.fetchall()}


def workspaces_due(cur, now, min_events=5, max_age_seconds=86400, limit=20):
    """Workspaces with enough unconsumed events, or one that has waited a day (design §5.2)."""
    cur.execute("SELECT workspace_id::text, count(*), extract(epoch from min(created_at)) FROM public.pr_learning_events WHERE consumed_by IS NULL GROUP BY workspace_id HAVING count(*) >= %s OR min(created_at) < to_timestamp(%s) ORDER BY min(created_at) LIMIT %s", (min_events, now - max_age_seconds, limit))
    return [values[0] for values in cur.fetchall()]


def events_window(cur, workspace_id, now, days):
    cur.execute(f"SELECT {EVENT_COLUMNS} FROM public.pr_learning_events WHERE workspace_id=%s AND created_at > to_timestamp(%s) ORDER BY seq", (workspace_id, now - days * 86400))
    return [_row(values) for values in cur.fetchall()]


def latest_metrics_by_job(cur, workspace_id):
    """The newest available value of each native metric per PostRiff-published job (insights.py definitions)."""
    cur.execute("SELECT DISTINCT ON (job_id, metric) job_id, metric, value FROM public.pr_metric_observations WHERE workspace_id=%s AND job_id IS NOT NULL AND availability='available' ORDER BY job_id, metric, observed_at DESC", (workspace_id,))
    metrics = {}
    for job_id, metric, value in cur.fetchall():
        metrics.setdefault(job_id, {})[metric] = float(value)
    return metrics


def mark_consumed(cur, workspace_id, batch_id, before):
    cur.execute("UPDATE public.pr_learning_events SET consumed_by=%s WHERE workspace_id=%s AND consumed_by IS NULL AND created_at <= to_timestamp(%s)", (batch_id, workspace_id, before))
    return cur.rowcount


def create_proposal(cur, workspace_id, state, proposal, now, evidence=None):
    """Server code adds a pending proposal (a chat instruction now, extraction later). Returns the row, or
    None when there is nothing new to ask: the same preference is active, waiting, recently dismissed, or
    three are already waiting. Raises ValueError for a statement the lint refuses."""
    p = learning.normalize_proposal(proposal)
    if p["type"] not in learning.TYPES or p["polarity"] not in learning.POLARITIES or p["ruleKey"] not in learning.RULE_KEYS:
        raise ValueError("Unsupported preference proposal.")
    p["statement"] = learning.lint(p.get("statement"), p["ruleKey"])
    key = learning.scope_key(p["type"], p["ruleKey"], p["polarity"], p["scope"])
    current = next((item for item in learning.active_items(state) if item["scopeKey"] == key), None)
    if current and current["statement"] == p["statement"]:
        return None
    if suppressed(cur, workspace_id, key, now):
        return None
    pending = pending_proposals(cur, workspace_id)
    if len(pending) >= learning.MAX_PENDING or any(row["scopeKey"] == key for row in pending):
        return None
    op = p["op"] if p["op"] == "retire" else ("update" if (current or p["replaces"]) else "add")
    replaces = p["replaces"] or (current["id"] if current else None)
    if op == "retire" and (not replaces or replaces not in {item["id"] for item in learning.active_items(state)}):
        return None
    body = {k: p[k] for k in ("type", "ruleKey", "polarity", "scope", "statement", "applyWhen", "params", "source")}
    body.update({"scopeKey": key, "op": op, "why": " ".join(str(p.get("why") or "").split())[:240], "evidence": evidence or p.get("evidence") or [], "variantId": p.get("variantId"), "replaces": replaces, "support": p.get("support"),
                 "performance": p.get("performance") if isinstance(p.get("performance"), dict) else None})
    cur.execute("INSERT INTO public.pr_memory_proposals(workspace_id,scope_key,op,source,body,status,created_at,expires_at) VALUES(%s,%s,%s,%s,%s::jsonb,'pending',to_timestamp(%s),to_timestamp(%s)) RETURNING id::text",
                (workspace_id, key, op, p["source"], json.dumps(body, ensure_ascii=False), now, now + learning.PROPOSAL_TTL.total_seconds()))
    return load_proposal(cur, workspace_id, cur.fetchone()[0])


def proposal_view(row):
    """What a card shows: the proposal, its status and when it expires."""
    return {"id": row["id"], "status": row["status"], "op": row["op"], "source": row["source"], "at": row["at"], "expiresAt": row["expiresAt"], "decidedAt": row["decidedAt"], **{k: row["body"].get(k) for k in ("type", "ruleKey", "polarity", "scope", "statement", "applyWhen", "why", "evidence", "variantId", "replaces", "performance")}, "scopeLabel": learning.scope_label(row["body"].get("scope") or {})}


class HostedLearning:
    """Bound to a service: the repository effect, the worker hook, the cron sweep, proposals and decisions."""
    def __init__(self, connection_factory, clock, extractor=None):
        self.connection_factory = connection_factory
        self.clock = clock
        self.failures = []
        # A model extractor (design §5.2 C2) adds observations from the drafts' text; None keeps extraction deterministic.
        self.extractor = extractor

    def capture(self, cur, workspace_id, before, after, principal):
        """Repository effect (hosted.PostgresWorkspaceRepository.command): the events one command implies.
        A reset (learning.resetAt changed) also clears this workspace's learning tables."""
        if (after.get("learning") or {}).get("resetAt") != (before.get("learning") or {}).get("resetAt"):
            for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events"):
                cur.execute(f"DELETE FROM public.{table} WHERE workspace_id=%s", (workspace_id,))
        events = signals.derive_events(before, after, principal, self.clock())
        guarded_insert(cur, workspace_id, events, self.failures)
        return events

    def proposals(self, repository, workspace_id, token):
        with repository.transaction(token, workspace_id) as (cur, row, _):
            state = json.loads(row[1]) if isinstance(row[1], str) else row[1]
            return {"pending": [proposal_view(r) for r in pending_proposals(cur, workspace_id)], "recent": [proposal_view(r) for r in recent_proposals(cur, workspace_id)],
                    "versions": versions(cur, workspace_id), "learning": learning.summary(state)}

    def propose_from_chat(self, cur, workspace_id, state, proposal, principal, now):
        """Inside a turn's transaction: the proposal a chat instruction implies, plus the chat.instruction event."""
        created = create_proposal(cur, workspace_id, state, proposal, now)
        event = {"kind": "chat.instruction", "actor": principal, "at": now, "subject": {"proposalId": created["id"] if created else None, "ruleKey": proposal.get("ruleKey"), "accepted": created is not None},
                 "scope": {**(proposal.get("scope") or {}), "formatId": None}, "features": {}, "voiceRevision": (state.get("speaker") or {}).get("activeRevision"), "styleRevision": learning.revision(state)}
        guarded_insert(cur, workspace_id, [event], self.failures)
        return created

    def decide(self, repository, workspace_id, token, revision, proposal_id, decision, statement=None):
        """Owner decision on one proposal: remember / edit (a new version, a new style revision), dismiss (quiet
        for 90 days), post_only (only when the proposal came from a draft). One transaction with the state."""
        if decision not in DECISIONS:
            raise AlphaError("Choose remember, edit, dismiss or post_only.")
        with repository.transaction(token, workspace_id) as (cur, _, _):
            proposal = load_proposal(cur, workspace_id, proposal_id)
        if proposal["status"] != "pending":
            raise AlphaError("This proposal was already decided.", 409)
        body = dict(proposal["body"])
        if decision == "edit":
            body["statement"] = statement if isinstance(statement, str) else ""
            body["evidenceState"] = "user_confirmed"
        now = self.clock()
        result = {}

        def apply(state, principal):
            learning.ensure(state, now)
            if decision in ("remember", "edit") and body.get("op") == "retire":
                # The person agreed to stop a preference they had been editing against.
                if not learning.retire(state, body.get("replaces"), now, "retired"):
                    raise AlphaError("That learned preference is no longer active.", 409)
            elif decision in ("remember", "edit"):
                try:
                    result["item"] = learning.remember(state, {**body, "id": proposal["id"], "source": body.get("source", "chat")}, actor=principal, now=now)
                except ValueError as error:
                    raise AlphaError(str(error)) from error
                if decision == "edit":
                    result["item"]["evidenceState"] = "user_confirmed"
                    result["item"]["evidenceSummary"] = "you edited the wording"
            elif decision == "post_only":
                variant = next((v for v in state.get("variants") or [] if v.get("id") == body.get("variantId")), None)
                if variant is None:
                    raise AlphaError("This suggestion is not tied to a draft. Remember it for future drafts, or dismiss it.")
                variant["localPreferences"] = dict(body.get("params") or {})
            return state

        def after(cur, state, principal):
            cur.execute("UPDATE public.pr_memory_proposals SET status=%s,decided_by=%s,decided_at=to_timestamp(%s),body=%s::jsonb WHERE id::text=%s AND workspace_id=%s AND status='pending' RETURNING id",
                        (DECISIONS[decision], principal, now, json.dumps(body, ensure_ascii=False), proposal["id"], workspace_id))
            if cur.fetchone() is None:
                raise AlphaError("This proposal was already decided.", 409)
            if decision in ("remember", "edit"):
                cur.execute("UPDATE public.pr_memory_versions SET status='retired',valid_to=to_timestamp(%s) WHERE workspace_id=%s AND scope_key=%s AND valid_to IS NULL", (now, workspace_id, proposal["scopeKey"]))
                if body.get("replaces"):
                    cur.execute("UPDATE public.pr_memory_versions SET status='retired',valid_to=to_timestamp(%s) WHERE workspace_id=%s AND proposal_id::text=%s AND valid_to IS NULL", (now, workspace_id, str(body["replaces"])))
                if body.get("op") != "retire":
                    cur.execute("INSERT INTO public.pr_memory_versions(workspace_id,scope_key,body,status,proposal_id,confirmed_by,valid_from) VALUES(%s,%s,%s::jsonb,'active',%s,%s,to_timestamp(%s)) RETURNING id::text",
                                (workspace_id, proposal["scopeKey"], json.dumps(result["item"], ensure_ascii=False), proposal["id"], principal, now))
                    result["versionId"] = cur.fetchone()[0]
            event = {"kind": "proposal.decided", "actor": principal, "at": now, "subject": {"proposalId": proposal["id"], "decision": DECISIONS[decision], "scopeKey": proposal["scopeKey"], "ruleKey": body.get("ruleKey"), "source": body.get("source")},
                     "scope": {**(body.get("scope") or {}), "formatId": None}, "features": {}, "voiceRevision": (state.get("speaker") or {}).get("activeRevision"), "styleRevision": learning.revision(state)}
            guarded_insert(cur, workspace_id, [event], self.failures)

        saved = repository.command(workspace_id, token, revision, apply, requirement="owner", after=after)
        return {"revision": saved["revision"], "proposalId": proposal["id"], "status": DECISIONS[decision], "item": result.get("item"), "versionId": result.get("versionId"), "learning": learning.summary(saved["state"])}

    def update_version(self, repository, workspace_id, token, revision, item_id, status):
        """Owner: pause, resume or retire one learned item; the version row follows the state."""
        now = self.clock()

        def apply(state, principal):
            try:
                if not learning.set_status(state, item_id, status, now):
                    raise AlphaError("This learned preference is not in that state.", 409)
            except ValueError as error:
                raise AlphaError(str(error)) from error
            return state

        def after(cur, state, principal):
            if status == "retired":
                cur.execute("UPDATE public.pr_memory_versions SET status='retired',valid_to=to_timestamp(%s) WHERE workspace_id=%s AND proposal_id::text=%s AND valid_to IS NULL", (now, workspace_id, item_id))
            else:
                cur.execute("UPDATE public.pr_memory_versions SET status=%s WHERE workspace_id=%s AND proposal_id::text=%s AND valid_to IS NULL", (status, workspace_id, item_id))

        saved = repository.command(workspace_id, token, revision, apply, requirement="owner", after=after)
        return {"revision": saved["revision"], "itemId": item_id, "status": status, "learning": learning.summary(saved["state"])}

    def published(self, cur, workspace_id, job):
        return record_published(cur, workspace_id, job, self.clock(), self.failures)

    def events(self, workspace_id, token, repository, limit=500):
        with repository.transaction(token, workspace_id) as (cur, _, _):
            return {"events": list_events(cur, workspace_id, limit)}

    def sweep(self, max_seconds=15):
        """Cron entry: retention and expiry, then extraction for the workspaces that are due."""
        with self.connection_factory() as db:
            with db.cursor() as cur:
                result = sweep(cur, self.clock())
        result["captureFailures"] = len(self.failures)
        result["extraction"] = self.extract(max_seconds=max_seconds)
        return result

    def model_allowed(self, state):
        if self.extractor is None:
            return False
        if getattr(self.extractor, "local", False):
            return True
        from . import memory
        settings = state.get("learning") if isinstance(state.get("learning"), dict) else {}
        return bool(settings.get("cloudExtraction")) and memory.egress(state).get("cloud") is True

    def extract(self, max_seconds=15, max_workspaces=20):
        """Design §5.2–§5.3: for each workspace that is due, read the last 90 days of events, consolidate
        deterministic observations (and a model extractor's, when one is configured and allowed) into
        proposals, and mark the events seen. Never touches workspace state, so open tabs see no 409."""
        from . import learning_extract as extract
        started, now = time.monotonic(), self.clock()
        stats = {"workspaces": 0, "proposed": 0, "skipped": 0, "modelRuns": 0}
        with self.connection_factory() as db:
            with db.cursor() as cur:
                due = workspaces_due(cur, now, limit=max_workspaces)
        for workspace_id in due:
            if time.monotonic() - started > max_seconds:
                break
            stats["workspaces"] += 1
            batch = uuid.uuid4().hex
            with self.connection_factory() as db:
                with db.cursor() as cur:
                    cur.execute("SELECT state FROM public.pr_workspaces WHERE id=%s", (workspace_id,))
                    row = cur.fetchone()
                    if row is None:
                        continue
                    state = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    settings = state.get("learning") if isinstance(state.get("learning"), dict) else {}
                    if settings.get("enabled") is False:
                        mark_consumed(cur, workspace_id, batch, now)
                        stats["skipped"] += 1
                        continue
                    allowed_actors = None if settings.get("teamEdits") else owners(cur, workspace_id)
                    events = [e for e in events_window(cur, workspace_id, now, extract.WINDOW_DAYS) if allowed_actors is None or e["actor"] is None or e["actor"] in allowed_actors]
                    support, counter = extract.observations(events)
                    if self.model_allowed(state):
                        # Decision C: the person's own CLI needs no consent beyond learning being on; a cloud model needs
                        # memory-egress consent plus the cloudExtraction switch (and per-source consent, checked per pair).
                        try:
                            support.extend(self.extractor.observe(state, events, now))
                            stats["modelRuns"] += 1
                        except Exception:  # noqa: BLE001 - the deterministic half still proposes
                            stats["modelFailures"] = stats.get("modelFailures", 0) + 1
                    candidates = extract.consolidate(support, counter, state, now, dismissed_keys(cur, workspace_id, now), recent_decisions(cur, workspace_id))
                    # Phase D: the kill switch adds retire proposals; performance is attached as a note, never as a reason.
                    replaced = {c.get("replaces") for c in candidates}
                    candidates += [r for r in extract.regressions(state, events, now) if r["replaces"] not in replaced]
                    approved = [e for e in events if e["kind"] == "draft.approved"]
                    if approved:
                        metrics = latest_metrics_by_job(cur, workspace_id)
                        for candidate in candidates:
                            note = extract.performance_note(candidate, approved, metrics) if metrics else None
                            if note:
                                candidate["performance"] = note
                    budget = max(0, 1 - automatic_proposals_since(cur, workspace_id, now - 86400))
                    for candidate in candidates:
                        if budget <= 0:
                            break
                        try:
                            created = create_proposal(cur, workspace_id, state, candidate, now)
                        except ValueError:
                            created = None
                        if created is not None:
                            stats["proposed"] += 1
                            budget -= 1
                    mark_consumed(cur, workspace_id, batch, now)
        return stats
