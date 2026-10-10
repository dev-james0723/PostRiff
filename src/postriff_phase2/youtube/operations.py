"""Thin selection hints; locked workspace/journal state remains authoritative.

Migration 104 maintains these projections in the same source transaction. They
never grant approval or remove history. Private legacy deployments may use the
previous selector until the migration exists; the public fleet requires it.
"""


SCHEMA_SQL = """SELECT to_regclass('public.pr_youtube_operations'),
    to_regclass('public.pr_youtube_planner_candidates'),
    EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('public.pr_youtube_uploads')
      AND attname='youtube_api_expires_at' AND NOT attisdropped)"""


def schema_ready(cur):
    cur.execute(SCHEMA_SQL)
    row = cur.fetchone()
    return bool(row and len(row) == 3 and all(row))


WORKER_SQL = """SELECT w.id::text,w.revision FROM public.pr_youtube_operations o
    JOIN public.pr_workspaces w ON w.id=o.workspace_id
    LEFT JOIN public.pr_worker_tenants dispatch ON dispatch.workspace_id=w.id
    WHERE o.upload_due_at<=least(%s,%s)
    ORDER BY dispatch.last_claimed_at NULLS FIRST,w.id LIMIT 100
    FOR UPDATE OF w SKIP LOCKED"""


def planner_sql(*, fleet=False):
    lease = " AND NOT (w.id=ANY(%s::uuid[])) AND o.planner_lease_until<=%s" if fleet else ''
    return """SELECT w.id::text FROM public.pr_youtube_operations o
        JOIN public.pr_workspaces w ON w.id=o.workspace_id
        WHERE EXISTS(SELECT 1 FROM public.pr_youtube_planner_candidates p
          WHERE p.workspace_id=w.id AND p.candidate_at<=%s AND p.ends_at>%s)""" + lease + """
        ORDER BY o.last_planner_dispatch,w.id LIMIT 100""" + (' FOR UPDATE OF w SKIP LOCKED' if fleet else '')


EXPIRY_SQL = """SELECT workspace_id::text FROM (
    (SELECT workspace_id FROM public.pr_youtube_operations WHERE provider_expires_at<=%s
      ORDER BY workspace_id LIMIT 100)
    UNION
    (SELECT workspace_id FROM public.pr_youtube_uploads WHERE youtube_api_expires_at<=%s
      GROUP BY workspace_id ORDER BY workspace_id LIMIT 100)
    ) expired ORDER BY workspace_id LIMIT 100"""
