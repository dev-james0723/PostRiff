"""Bounded content-free writer receipts in the existing append-only tenant audit.

Failed/suspended batches retain only the writer's already validated ids, enums,
counts and times. Recovery uses original event time and current observation time,
never restores a deleted tenant or a revoked actor, and makes no provider calls.
The journal is best effort too: if the database itself is unavailable, its
absence is an explicit coverage limitation, never proof of zero missing events.
"""
from collections import defaultdict
from datetime import datetime
import json
import logging
import uuid

LOG = logging.getLogger(__name__)
WRITERS = ('product_events', 'ai_call_events')
MAX_BYTES = 256_000


def record(cur, writer, rows, *, state, recorded=0, error=None):
    if writer not in WRITERS or state not in ('recorded', 'failed', 'suspended'):
        return False
    groups = defaultdict(list)
    for row in rows:
        if writer == 'ai_call_events':
            from .ai_call_events import COLUMNS
            row = {key: row.get(key) for key in COLUMNS}
        groups[row[0] if writer == 'product_events' else row.get('workspace_id')].append(row)
    mark = 'telemetry_journal_' + uuid.uuid4().hex[:8]
    try:
        cur.execute(f'SAVEPOINT {mark}')
        for workspace, items in groups.items():
            meta = {'version': 1, 'writer': writer, 'state': state, 'attempted': len(items),
                    # Recorded is batch-wide; counted once, including batches spanning tenants.
                    'recorded': recorded if workspace == next(iter(groups)) else 0,
                    'errorClass': type(error).__name__ if error else None,
                    'recoverable': state != 'recorded', 'rows': items if state != 'recorded' else []}
            payload = json.dumps(meta, separators=(',', ':'), default=lambda x: x.isoformat() if isinstance(x, datetime) else str(x))
            if len(payload.encode()) > MAX_BYTES:
                meta.update(recoverable=False, rows=[], errorClass='JournalBatchTooLarge')
                payload = json.dumps(meta, separators=(',', ':'))
            cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,NULL,%s,'',%s::jsonb)",
                        (workspace, 'telemetry.' + writer, payload))
        cur.execute(f'RELEASE SAVEPOINT {mark}')
        return True
    except Exception as error:
        try:
            cur.execute(f'ROLLBACK TO SAVEPOINT {mark}')
            cur.execute(f'RELEASE SAVEPOINT {mark}')
        except Exception:
            pass
        LOG.warning(json.dumps({'event': 'telemetry.journal_unavailable', 'writer': writer, 'errorClass': type(error).__name__}))
        return False


def recover(cur, *, limit=100):
    """Owning service-role transaction only; bounded manual recovery, not cron replay.

    Caller commits. An advisory lock plus immutable recovery receipt serialize
    readers without adding update/delete rights to the existing audit journal.
    """
    limit = min(100, max(1, int(limit)))
    cur.execute("SELECT now()-interval '400 days'")
    retention_start = cur.fetchone()[0]
    cur.execute("""SELECT a.id::text,a.workspace_id::text,a.at,a.meta FROM public.pr_audit_events a
                   WHERE a.kind IN ('telemetry.product_events','telemetry.ai_call_events')
                     AND a.meta->>'recoverable'='true'
                     AND NOT EXISTS(SELECT 1 FROM public.pr_audit_events r
                                    WHERE r.kind='telemetry.recovered' AND r.subject=a.id::text)
                   ORDER BY a.at,a.id LIMIT %s""", (limit,))
    batches = cur.fetchall()
    result = {'batches': 0, 'inserted': 0, 'discarded': 0}
    for journal_id, workspace, occurred, meta in batches:
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('telemetry:' + journal_id,))
        cur.execute("SELECT 1 FROM public.pr_audit_events WHERE kind='telemetry.recovered' AND subject=%s", (journal_id,))
        if cur.fetchone():
            continue
        if workspace:
            cur.execute('SELECT 1 FROM public.pr_workspaces WHERE id=%s', (workspace,))
            if not cur.fetchone():
                # FK cascades normally already removed this batch.
                continue
        inserted, discarded = 0, 0
        for row in meta.get('rows', []):
            event_time = occurred if meta['writer']=='product_events' else row.get('started_at')
            if isinstance(event_time, str):
                event_time = datetime.fromisoformat(event_time)
            if event_time is None or event_time < retention_start:
                discarded += 1
                continue
            user = row[1] if meta['writer'] == 'product_events' else row.get('user_id')
            if user:
                cur.execute("SELECT 1 FROM public.pr_profiles p WHERE p.user_id=%s AND p.deleted_at IS NULL "
                            "AND (%s::uuid IS NULL OR EXISTS(SELECT 1 FROM public.pr_memberships m WHERE m.user_id=p.user_id AND m.workspace_id=%s AND m.status='active'))",
                            (user, workspace, workspace))
                if cur.fetchone() is None:
                    discarded += 1
                    continue
            if meta['writer'] == 'product_events':
                cur.execute('INSERT INTO public.pr_product_events(workspace_id,user_id,event,properties,dedupe_key,occurred_at,expires_at) '
                            "VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s+interval '400 days') ON CONFLICT DO NOTHING", (*row, occurred, occurred))
                inserted += cur.rowcount
            else:
                from .ai_call_events import _insert
                inserted += _insert(cur, [row])
        cur.execute("INSERT INTO public.pr_audit_events(workspace_id,actor,kind,subject,meta) VALUES(%s,NULL,'telemetry.recovered',%s,%s::jsonb)",
                    (workspace, journal_id, json.dumps({'version': 1, 'inserted': inserted, 'discarded': discarded})))
        result['batches'] += 1
        result['inserted'] += inserted
        result['discarded'] += discarded
    return result
