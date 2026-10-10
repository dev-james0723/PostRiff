"""Thin selection hints; locked workspace/journal state remains authoritative.

Migration 106 maintains these projections; 107 adds the durable fleet claim cursor. They
never grant approval or remove history. Private legacy deployments may use the
previous selector until the migration exists; the public fleet requires it.
"""

import math

# Operational cursor only; reject malformed or out-of-epoch-range legacy data.
PLANNER_CURSOR_MAX = 253402300799.0


def next_planner_claim_at(state, now):
    data = state.get('youtubeAgent') or {}
    previous = 0
    for name in ('lastPlannerClaimAt', 'lastDispatchAt'):
        value = data.get(name)
        if type(value) not in (int, float):
            continue
        try:
            if math.isfinite(value) and 0 <= value < PLANNER_CURSOR_MAX:
                previous = 0 if value < .000001 else value
                break
        except OverflowError:
            continue
    # Strict per-tenant progress also rotates a clock that has not advanced.
    return max(now, math.nextafter(previous, math.inf), .000001)


def planner_claim_order_sql(state_column='state'):
    def cursor(name):
        field = state_column + "#>'{youtubeAgent," + name + "}'"
        text = state_column + "#>>'{youtubeAgent," + name + "}'"
        # Numeric bounds precede float conversion; tiny epoch values are zero.
        # Nested CASE prevents SQL predicate reordering from overflowing a cast.
        return ("CASE WHEN jsonb_typeof(" + field + ")='number' THEN "
                "CASE WHEN (" + text + ")::numeric>=0 AND (" + text + ")::numeric<253402300799 THEN "
                "CASE WHEN (" + text + ")::numeric<0.000001 THEN 0 ELSE (" + text + ")::float8 END END END")
    return 'coalesce(' + cursor('lastPlannerClaimAt') + ',' + cursor('lastDispatchAt') + ',0)'


def planner_rotation_ready(cur):
    cur.execute("""SELECT EXISTS(SELECT 1 FROM pg_attribute
        WHERE attrelid=to_regclass('public.pr_youtube_operations')
          AND attname='last_planner_claim' AND NOT attisdropped)""")
    row = cur.fetchone()
    return bool(row and row[0])


SCHEMA_SQL = """SELECT to_regclass('public.pr_youtube_operations'),
    to_regclass('public.pr_youtube_planner_candidates'),
    EXISTS(SELECT 1 FROM pg_attribute WHERE attrelid=to_regclass('public.pr_youtube_uploads')
      AND attname='youtube_api_expires_at' AND NOT attisdropped)"""


def schema_ready(cur):
    cur.execute(SCHEMA_SQL)
    row = cur.fetchone()
    return bool(row and len(row) == 3 and all(row))


WORKER_SQL = """SELECT w.id::text,w.revision FROM public.pr_workspaces w
    JOIN public.pr_youtube_operations o ON w.id=o.workspace_id
    LEFT JOIN public.pr_worker_tenants dispatch ON dispatch.workspace_id=w.id
    WHERE o.upload_due_at<=least(%s,%s)
    ORDER BY dispatch.last_claimed_at NULLS FIRST,w.id LIMIT 100
    FOR UPDATE OF w SKIP LOCKED"""


def planner_sql(*, fleet=False, claim_rotation=False):
    lease = " AND NOT (w.id=ANY(%s::uuid[])) AND o.planner_lease_until<=%s" if fleet else ''
    order = ('o.last_planner_claim' if claim_rotation else planner_claim_order_sql('w.state')) if fleet else 'o.last_planner_dispatch'
    return """SELECT w.id::text FROM public.pr_workspaces w
        JOIN public.pr_youtube_operations o ON w.id=o.workspace_id
        WHERE EXISTS(SELECT 1 FROM public.pr_youtube_planner_candidates p
          WHERE p.workspace_id=w.id AND p.candidate_at<=%s AND p.ends_at>%s)""" + lease + """
        ORDER BY """ + order + ",w.id LIMIT 100" + (' FOR UPDATE OF w SKIP LOCKED' if fleet else '')


EXPIRY_SQL = """SELECT workspace_id::text FROM (
    (SELECT workspace_id FROM public.pr_youtube_operations WHERE provider_expires_at<=%s
      ORDER BY workspace_id LIMIT 100)
    UNION
    (SELECT workspace_id FROM public.pr_youtube_uploads WHERE youtube_api_expires_at<=%s
      GROUP BY workspace_id ORDER BY workspace_id LIMIT 100)
    ) expired ORDER BY workspace_id LIMIT 100"""
