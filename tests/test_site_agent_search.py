"""workspace.search: the `@` picker's server results (chat-context SPEC §4.3, §5.9). Read-only, this workspace only."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from postriff_phase2 import content_types  # noqa: E402
from postriff_phase2.permissions import Membership  # noqa: E402
from postriff_phase2.site_agent import tools  # noqa: E402  (tools first: reads builds on it)
from postriff_phase2.site_agent import reads  # noqa: E402

NOW = 1_790_000_000.0
A1, A2, A3 = ("0f3c0e3a9d5b4c1e8f7a6b5c4d3e2f1" + c for c in "012")


def workspace(tag="one"):
    system = content_types.ensure_content_state({})
    version = content_types.definition({}, "postriff:update")["version"]
    system["templates"] = [
        {"id": f"t-{tag}", "name": "Concert announcement", "contentTypeId": "postriff:update", "contentTypeVersion": version, "ownerUserId": "u1", "visibility": "private", "archived": False},
        {"id": f"t-shared-{tag}", "name": "Weekly update", "contentTypeId": "postriff:update", "contentTypeVersion": version, "ownerUserId": "u2", "visibility": "workspace", "archived": False},
        {"id": f"t-private-{tag}", "name": "Someone's private", "contentTypeId": "postriff:update", "contentTypeVersion": version, "ownerUserId": "u2", "visibility": "private", "archived": False},
        {"id": f"t-archived-{tag}", "name": "Concert old", "contentTypeId": "postriff:update", "contentTypeVersion": version, "ownerUserId": "u1", "visibility": "workspace", "archived": True},
    ]
    return {
        "contentSystem": system,
        "variants": [
            {"id": f"v-spring-{tag}", "text": "春季演奏會\n五月三日", "platform": "Instagram", "language": "zh-Hant-HK", "channelId": f"ch-ig-{tag}"},
            {"id": f"v-launch-{tag}", "text": "Product launch recap", "platform": "LinkedIn", "language": "en"},
            {"id": f"v-rejected-{tag}", "text": "春 rejected", "platform": "X", "language": "en", "rejected": True},
        ],
        "sources": [
            {"id": f"s-notes-{tag}", "kind": "text", "title": "Programme notes", "active": True, "sourcePolicy": "public_quote", "facts": [{"id": "f1", "approved": True}, {"id": "f2", "approved": False}]},
            {"id": f"s-voice-{tag}", "kind": "voice_sample", "title": "Programme voice", "active": True, "sourcePolicy": "public_quote", "facts": []},
            {"id": f"s-gone-{tag}", "kind": "text", "title": "Programme old", "active": False, "sourcePolicy": "public_quote", "facts": []},
            {"id": f"s-banned-{tag}", "kind": "text", "title": "Programme banned", "active": True, "sourcePolicy": "prohibited", "facts": []},
        ],
        "phase2": {
            "channels": [{"id": f"ch-ig-{tag}", "platform": "Instagram", "account": "piano_hk"}, {"id": f"ch-li-{tag}", "platform": "LinkedIn", "account": "HKFIMM"},
                         {"id": f"ch-old-{tag}", "platform": "Instagram", "account": "old_piano", "revoked": True}],
            "channelFolders": [{"id": f"fo-{tag}", "name": "Festival", "accountIds": [f"ch-ig-{tag}", f"ch-li-{tag}", f"ch-old-{tag}"]}],
            "assets": [
                {"id": A1, "mime": "image/jpeg", "processing": "decoded", "width": 1080, "height": 1350, "deleted": False, "createdAt": 10},
                {"id": A2, "mime": "video/mp4", "processing": "ready", "duration": 42.4, "deleted": False},
                {"id": A3, "mime": "image/jpeg", "processing": "decoded", "deleted": True},
            ],
            "jobs": [{"id": "job-1", "manifest": {"variantId": f"v-launch-{tag}"}, "updatedAt": NOW}],
        },
    }


def ctx(state, role="viewer", principal="u1", workspace_id="w-one"):
    return tools.Context(state=state, membership=Membership(role), principal=principal, workspace_id=workspace_id, now=NOW)


def search(state=None, role="viewer", **args):
    record, result = tools.run("workspace.search", args, ctx(state or workspace(), role))
    return record, result


def ids(result, category):
    return [item["id"] for item in result["data"]["categories"].get(category, [])]


class RegistryTests(unittest.TestCase):
    def test_registered_as_a_read(self):
        self.assertEqual(tools.CATALOG["workspace.search"]["effect"], "read")
        self.assertEqual(set(tools.EXECUTORS), set(tools.CATALOG))
        self.assertEqual(tools.LABELS["workspace.search"], "Searched items to add to a message")

    def test_input_bounds(self):
        for args in ({"query": "x" * 121}, {"categories": "posts"}, {"categories": ["posts", "secrets"]}, {"limit": 13}, {"limit": 0}, {"limit": True}, {"other": 1}):
            with self.subTest(args=args):
                record, result = search(**args)
                self.assertEqual(record["status"], "blocked")
                self.assertFalse(result["ok"])


class QueryTests(unittest.TestCase):
    def test_shared_vectors(self):
        vectors = json.loads((ROOT / "tests" / "fixtures" / "picker-queries.json").read_text(encoding="utf-8"))["vectors"]
        for vector in vectors:
            with self.subTest(query=vector["query"]):
                self.assertEqual(reads.picker_query(vector["query"]), (vector["text"], vector["category"], vector["platform"]))


class SearchTests(unittest.TestCase):
    def test_viewer_can_search_everything(self):
        record, result = search(query="")
        self.assertEqual(record["status"], "verified")
        data = result["data"]["categories"]
        self.assertEqual(set(data), {"posts", "templates", "accounts", "folders", "sources", "library"})
        self.assertEqual(ids(result, "posts"), ["v-launch-one", "v-spring-one"])   # recency: the scheduled post first
        self.assertEqual(ids(result, "templates"), ["t-shared-one", "t-one"])   # newest (last added) first
        self.assertEqual(ids(result, "accounts"), ["ch-li-one", "ch-ig-one"])
        self.assertEqual(data["folders"][0]["sublabel"], "2 accounts")
        self.assertEqual(data["sources"], [{"kind": "source", "id": "s-notes-one", "label": "Programme notes", "sublabel": "1 approved fact"}])
        self.assertEqual(ids(result, "library"), [A1, A2])
        self.assertEqual(data["library"][1], {"kind": "video", "id": A2, "label": "Video", "href": f"/api/workspaces/w-one/media/{A2}", "duration": 42.4})

    def test_cjk_single_character_and_labels(self):
        _, result = search(query="@春")
        posts = result["data"]["categories"]["posts"]
        self.assertEqual([(p["id"], p["label"]) for p in posts], [("v-spring-one", "春季演奏會")])
        self.assertEqual(posts[0]["sublabel"], "Instagram · piano_hk · zh-Hant-HK")
        self.assertNotIn("v-rejected-one", json.dumps(result))

    def test_aliases_switch_groups(self):
        _, result = search(query="改")
        self.assertEqual(result["data"]["categories"], {})
        _, result = search(query="帖子")
        self.assertEqual(list(result["data"]["categories"]), ["posts"])
        _, result = search(query="ig")
        self.assertEqual(result["data"]["categories"], {"accounts": [{"kind": "account", "id": "ch-ig-one", "label": "Instagram · piano_hk", "platform": "Instagram", "state": "Connected"}]})
        _, result = search(query="＠ＩＧ")
        self.assertEqual(ids(result, "accounts"), ["ch-ig-one"])
        _, result = search(query="相片")
        self.assertEqual(ids(result, "library"), [A1, A2])
        _, result = search(query="帖子", categories=["accounts"])
        self.assertEqual(result["data"]["categories"], {})

    def test_ranking_prefix_before_substring(self):
        state = workspace()
        state["variants"] = [{"id": "a", "text": "A spring gala", "platform": "X", "language": "en"}, {"id": "b", "text": "Spring concert", "platform": "X", "language": "en"},
                             {"id": "c", "text": "Offspring", "platform": "X", "language": "en"}]
        _, result = search(state, query="spring", categories=["posts"])
        self.assertEqual(ids(result, "posts"), ["b", "a", "c"])

    def test_limit_and_categories(self):
        state = workspace()
        state["variants"] = [{"id": f"v{n}", "text": f"Post {n}", "platform": "X", "language": "en"} for n in range(20)]
        _, result = search(state, query="", categories=["posts"], limit=12)
        self.assertEqual(len(ids(result, "posts")), 12)
        self.assertEqual(list(result["data"]["categories"]), ["posts"])

    def test_filters(self):
        _, result = search(query="programme")
        self.assertEqual(ids(result, "sources"), ["s-notes-one"])
        _, result = search(query="concert")
        self.assertEqual(ids(result, "templates"), ["t-one"])
        _, result = search(query="old_piano")
        self.assertEqual(ids(result, "accounts"), [])

    def test_never_another_workspace(self):
        mine, theirs = workspace("one"), workspace("two")
        _, result = search(mine, query="")
        self.assertNotIn("-two", json.dumps(result))
        self.assertIsNotNone(theirs)

    def test_template_visibility_follows_the_actor(self):
        record, result = tools.run("workspace.search", {"query": "", "categories": ["templates"]}, ctx(workspace(), principal="u2"))
        self.assertEqual(ids(result, "templates"), ["t-private-one", "t-shared-one"])

    def test_empty_state(self):
        record, result = tools.run("workspace.search", {"query": "春"}, ctx({}))
        self.assertEqual((record["status"], result["data"]["categories"]), ("verified", {}))


if __name__ == "__main__":
    unittest.main()
