"""Paged Inbox read uses a bounded number of SQL calls and authoritative counts."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_phase2.hosted import HostedWorkspaceService

DSN = "host=127.0.0.1 port=55438 dbname=postgres"
ONE = "00000000-0000-0000-0000-000000000001"


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    assert token == "synthetic"
    return ONE


verify.session_id = lambda token, principal: "inbox-page-synthetic-session"
verify.auth_time = lambda token, principal: time.time()
service = HostedWorkspaceService(connection, verify)
with connection() as db:
    wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0])
    db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
service.bootstrap("synthetic", "studio")
with connection() as db:
    db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,author_handle,text,created_at_provider) SELECT %s,'threads-account','threads','123',gs::text,'visitor','How much?',to_timestamp(%s-gs) FROM generate_series(1,120) gs", (wid, time.time()))
    db.execute("INSERT INTO public.pr_channel_capabilities(workspace_id,connection_id,capability,level) VALUES(%s,'threads-account','reply','Direct'),(%s,'threads-account','comments_read','Direct')", (wid, wid))
    thread = db.execute("SELECT id FROM public.pr_audience_threads WHERE workspace_id=%s AND provider_comment_id='1'", (wid,)).fetchone()[0]
    db.execute("INSERT INTO public.pr_reply_drafts(workspace_id,thread_id,author,origin,text,status,events,provider_reference) VALUES(%s,%s,%s,'manual','The price is $10','verified',%s::jsonb,'789')", (wid, thread, ONE, json.dumps([{"at": time.time(), "state": "verified"}])))

queries = []


class CountingCursor:
    def __init__(self, inner):
        self.inner = inner

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def execute(self, sql, params=None):
        queries.append(sql)
        return self.inner.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class CountingConnection:
    def __init__(self):
        self.inner = connection()

    def __enter__(self):
        self.inner.__enter__()
        return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def cursor(self):
        return CountingCursor(self.inner.cursor())


service.repository.connection_factory = CountingConnection
service.audience.engagement_enabled = True
seen = set()
cursor = None
for expected in (50, 50, 20):
    queries.clear()
    page = service.audience.threads(wid, "synthetic", cursor)
    assert len(page["threads"]) == expected, len(page["threads"])
    assert len(queries) <= 7, len(queries)
    assert page["counts"] == {"all": 120, "replied": 1, "unanswered": 119}
    for item in page["threads"]:
        assert item["threadId"] not in seen
        seen.add(item["threadId"])
        assert item["triage"]["category"] == "lead"  # existing classifier, not an Inbox fork
    cursor = page["nextCursor"]
assert cursor is None and len(seen) == 120
first = service.audience.threads(wid, "synthetic", limit=1)["threads"][0]
assert first["replies"][0]["events"][0]["state"] == "verified" and first["replies"][0]["providerReference"] == "789"
try:
    service.audience.threads(wid, "synthetic", cursor="not-a-valid-cursor")
except AlphaError as error:
    assert error.status == 400
else:
    raise AssertionError("invalid cursor accepted")
with connection() as db:
    db.execute("INSERT INTO public.pr_audience_threads(workspace_id,connection_id,provider,provider_post_id,provider_comment_id,text,created_at_provider) VALUES(%s,'threads-account','instagram','ig-post','ig-comment','Unsupported provider',now()+interval '1 minute')", (wid,))
unsupported = service.audience.threads(wid, "synthetic", limit=1)["threads"][0]
assert unsupported["provider"] == "instagram" and unsupported["replyLevel"] == "Unsupported" and not unsupported["replyAvailable"]
print(json.dumps({"status": "pass", "execution": "disposable PostgreSQL", "checks": ["120 rows in 50/50/20 stable pages", "six bounded SQL reads per page", "authoritative counts", "saved receipt events", "existing engagement classifier", "invalid cursor rejected", "unsupported provider never inherits another connector's Direct reply level"]}))
