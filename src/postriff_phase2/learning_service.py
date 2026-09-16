"""Preference learning on the hosted repository (design §5.1, §6): capture the events a command implies
inside that command's transaction, record what the worker published, keep the tables tidy, export them.

Nothing here writes workspace state, and nothing here decides anything. The tables come from migration
010; service code writes them, members read their own workspace's rows through the API. A capture that
fails (for example before the migration is applied) is rolled back to a savepoint and counted, so the
command that caused it still succeeds and the cron result shows that learning is not recording.
"""
from __future__ import annotations

import json
import uuid

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


class HostedLearning:
    """Bound to a service: the repository effect, the worker hook and the cron sweep."""
    def __init__(self, connection_factory, clock):
        self.connection_factory = connection_factory
        self.clock = clock
        self.failures = []

    def capture(self, cur, workspace_id, before, after, principal):
        """Repository effect (hosted.PostgresWorkspaceRepository.command): the events one command implies."""
        events = signals.derive_events(before, after, principal, self.clock())
        guarded_insert(cur, workspace_id, events, self.failures)
        return events

    def published(self, cur, workspace_id, job):
        return record_published(cur, workspace_id, job, self.clock(), self.failures)

    def events(self, workspace_id, token, repository, limit=500):
        with repository.transaction(token, workspace_id) as (cur, _, _):
            return {"events": list_events(cur, workspace_id, limit)}

    def sweep(self):
        with self.connection_factory() as db:
            with db.cursor() as cur:
                result = sweep(cur, self.clock())
        result["captureFailures"] = len(self.failures)
        return result
