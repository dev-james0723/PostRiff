"""Context Navigation contracts on a disposable PostgreSQL workspace (no external providers)."""
import json
import os
import sys
import uuid
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime import FixtureAgentRuntime
from postriff_phase2.hosted import PostgresWorkspaceRepository
from postriff_phase2.ideas import IdeasService

DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
ONE = "00000000-0000-0000-0000-000000000001"
TWO = "00000000-0000-0000-0000-000000000002"

def connection(): return psycopg.connect(DSN)

repo = PostgresWorkspaceRepository(connection, lambda token: token)
ideas = IdeasService(repo, None, runtimes=[FixtureAgentRuntime()], researcher=False)
with connection() as db:
    first = db.execute("SELECT workspace_id::text FROM public.pr_memberships WHERE user_id=%s", (ONE,)).fetchone()[0]
    second = db.execute("SELECT workspace_id::text FROM public.pr_memberships WHERE user_id=%s", (TWO,)).fetchone()[0]
    conversation = db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Navigation research') RETURNING id::text", (first, ONE)).fetchone()[0]
    foreign = db.execute("INSERT INTO public.pr_conversations(workspace_id,created_by,title) VALUES(%s,%s,'Foreign secret') RETURNING id::text", (second, TWO)).fetchone()[0]
    asset_id = uuid.uuid4().hex  # Production video uploads use the compact UUID spelling.
    db.execute("""UPDATE public.pr_workspaces SET state=state || jsonb_build_object('phase2',
               coalesce(state->'phase2','{}'::jsonb) || jsonb_build_object('assets',
               coalesce(state->'phase2'->'assets','[]'::jsonb) || %s::jsonb)) WHERE id=%s""",
               (json.dumps([{"id": asset_id, "mime": "video/mp4", "processing": "ready", "duration": 180}]), first))
    with db.cursor() as cur:
        cur.executemany("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body) VALUES(%s,%s,%s,'user',%s::jsonb)",
                        [(conversation, first, n, json.dumps({"text": f"Turn {n} about navigation" if n != 973 else "Unique research context at turn 973，導航片段"})) for n in range(1, 1102)])
    db.execute("INSERT INTO public.pr_messages(conversation_id,workspace_id,seq,role,body) VALUES(%s,%s,1,'user','{\"text\":\"Foreign secret turn\"}')", (foreign, second))

page = ideas.navigation(first, ONE, conversation, 0, 200)
assert len(page["items"]) == 200 and page["nextCursor"] == 200 and page["totalMessages"] == 1101
assert all("body" not in item and len(item["excerpt"]) <= 180 for item in page["items"])
next_page = ideas.navigation(first, ONE, conversation, page["nextCursor"], 200)
assert next_page["items"][0]["seq"] == 201
with connection() as db:
    target = db.execute("SELECT id::text FROM public.pr_messages WHERE conversation_id=%s AND seq=973", (conversation,)).fetchone()[0]
window = ideas.message_window(first, ONE, conversation, target)
assert any(m["messageId"] == target for m in window["messages"]) and window["hasOlder"] and window["hasNewer"]
assert len(window["messages"]) <= 100
older = ideas.message_window(first, ONE, conversation, before=window["messages"][0]["seq"])
assert older["messages"][-1]["seq"] < window["messages"][0]["seq"]

search = ideas.navigation_search(first, ONE, "Unique research")
assert any(r.get("messageId") == target for r in search["results"])
assert any(r.get("messageId") == target for r in ideas.navigation_search(first, ONE, "導航")["results"])
assert all("Foreign" not in str(r) for r in search["results"])
assert any(r["kind"] == "conversation" for r in ideas.navigation_search(first, ONE, "Navigation research")["results"])
listed = ideas.navigation_conversations(first, ONE, limit=1)
assert listed["conversations"][0]["conversationId"] == conversation
assert listed["conversations"][0]["messageCount"] == 1101
assert all(r["conversationId"] != foreign for r in listed["conversations"])

saved = ideas.save_moment(first, ONE, conversation, {"assetId": asset_id, "title": "My video", "seconds": 83.4})
assert saved["timestamp"] == "01:23" and saved["source"] == "rafii_asset"
nav_moment = next(item for item in ideas.navigation(first, ONE, conversation, 1000, 200)["items"] if item.get("momentId") == saved["momentId"])
assert nav_moment["assetId"] == asset_id
window_moment = next(moment for moment in ideas.message_window(first, ONE, conversation)["moments"] if moment["momentId"] == saved["momentId"])
assert window_moment["assetId"] == asset_id
anchored_moment = next(moment for moment in ideas.message_window(first, ONE, conversation, saved["momentId"])["moments"] if moment["momentId"] == saved["momentId"])
assert anchored_moment["assetId"] == asset_id
for bad in ({"assetId": str(uuid.uuid4()), "title": "Wrong asset", "seconds": 1},
            {"assetId": asset_id, "title": "Too late", "seconds": 300},
            {"assetId": asset_id, "title": "Out of range", "seconds": 86400}):
    try: ideas.save_moment(first, ONE, conversation, bad)
    except AlphaError: pass
    else: raise AssertionError("Invalid moment accepted")
for operation in (lambda: ideas.navigation(first, TWO, conversation),
                  lambda: ideas.message_window(second, TWO, conversation, target),
                  lambda: ideas.save_moment(first, TWO, conversation, {"assetId": asset_id, "title": "X", "seconds": 1})):
    try: operation()
    except AlphaError as error: assert error.status in (403, 404)
    else: raise AssertionError("Foreign workspace access accepted")

with connection() as db:
    db.execute("INSERT INTO public.pr_memberships(workspace_id,user_id,role,status) VALUES(%s,%s,'viewer','active')", (first, TWO))
assert ideas.navigation(first, TWO, conversation)["totalMessages"] == 1101
try: ideas.save_moment(first, TWO, conversation, {"assetId": asset_id, "title": "Viewer", "seconds": 1})
except AlphaError as error: assert error.status == 403
else: raise AssertionError("Viewer saved a moment")

with connection() as db:
    with db.cursor() as cur:
        cur.executemany("INSERT INTO public.pr_conversations(workspace_id,created_by,title,updated_at) VALUES(%s,%s,%s,now() - (%s || ' minutes')::interval)",
                        [(first, ONE, f"Older conversation {n}", n + 1) for n in range(85)])
first_page = ideas.navigation_conversations(first, ONE, limit=40)
second_page = ideas.navigation_conversations(first, ONE, cursor=first_page["nextCursor"], limit=40)
third_page = ideas.navigation_conversations(first, ONE, cursor=second_page["nextCursor"], limit=40)
all_ids = [c["conversationId"] for page in (first_page, second_page, third_page) for c in page["conversations"]]
assert len(all_ids) == 86 and len(set(all_ids)) == 86 and third_page["nextCursor"] is None

print(json.dumps({"status": "passed", "checks": ["1101-turn pagination", "many-conversation keyset", "multilingual bounded search", "exact deep link", "workspace isolation", "viewer permission", "moment save/read/validation"]}))
