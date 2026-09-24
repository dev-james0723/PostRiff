"""Channel folders (Rafii v9): saved account groups keyed by connection id, stored in workspace state."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from postriff_alpha.domain import AlphaError  # noqa: E402
from postriff_phase2 import channel_folders as cf  # noqa: E402
from postriff_phase2.store import Phase2Store  # noqa: E402
from test_postriff_phase2 import P2Journey  # noqa: E402


def state_with(*ids):
    return {"phase2": {"channels": [{"id": i, "platform": "Instagram", "account": f"@{i}"} for i in ids]}}


class FolderRulesTest(unittest.TestCase):
    def test_save_validates_name_members_and_symbol(self):
        s = state_with("a", "b")
        self.assertTrue(cf.apply_action(s, "folder_save", {"name": "  Festival   week ", "accountIds": ["a", "b", "a"], "symbol": "music", "pinned": True}, "u1", 10))
        [folder] = cf.folders(s)
        self.assertEqual(folder["name"], "Festival week")
        self.assertEqual(folder["accountIds"], ["a", "b"])  # deduplicated, order kept
        self.assertEqual((folder["symbol"], folder["pinned"], folder["createdBy"], folder["updatedAt"]), ("music", True, "u1", 10))
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "", "accountIds": ["a"]}, "u1", 11)
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "x" * 41, "accountIds": ["a"]}, "u1", 11)
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "festival WEEK", "accountIds": ["a"]}, "u1", 11)  # case-insensitive duplicate
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "Empty", "accountIds": []}, "u1", 11)
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "Stranger", "accountIds": ["not-connected"]}, "u1", 11)
        cf.apply_action(s, "folder_save", {"name": "Plain", "accountIds": ["a"], "symbol": "rocket"}, "u1", 12)
        self.assertEqual(cf.folders(s)[1]["symbol"], "folder")  # unknown symbols fall back, never fail

    def test_edit_keeps_identity_and_missing_members_are_explicit(self):
        s = state_with("a", "b")
        cf.apply_action(s, "folder_save", {"name": "Personal", "accountIds": ["a", "b"]}, "u1", 1)
        folder_id = cf.folders(s)[0]["id"]
        s["phase2"]["channels"].pop()  # account b disconnected
        view = cf.view(s)
        self.assertEqual([m["connected"] for m in view[0]["members"]], [True, False])
        # Renaming keeps the stale member (an explicit record, not a silent drop) and the id.
        cf.apply_action(s, "folder_save", {"id": folder_id, "name": "Personal 2", "accountIds": ["a", "b"]}, "u2", 2)
        self.assertEqual(cf.folders(s)[0]["accountIds"], ["a", "b"])
        self.assertEqual(cf.folders(s)[0]["id"], folder_id)
        self.assertEqual(cf.folders(s)[0]["updatedBy"], "u2")
        # A brand-new folder cannot adopt the missing account.
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "Other", "accountIds": ["b"]}, "u1", 3)

    def test_delete_leaves_accounts_alone_and_limits_hold(self):
        s = state_with("a")
        cf.apply_action(s, "folder_save", {"name": "One", "accountIds": ["a"]}, "u1", 1)
        folder_id = cf.folders(s)[0]["id"]
        cf.apply_action(s, "folder_delete", {"id": folder_id}, "u1", 2)
        self.assertEqual(cf.folders(s), [])
        self.assertEqual(len(s["phase2"]["channels"]), 1)
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_delete", {"id": folder_id}, "u1", 3)
        for n in range(cf.FOLDER_MAX):
            cf.apply_action(s, "folder_save", {"name": f"F{n}", "accountIds": ["a"]}, "u1", 4)
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_save", {"name": "One too many", "accountIds": ["a"]}, "u1", 5)

    def test_move_stays_inside_pinned_section(self):
        s = state_with("a")
        for name, pinned in (("P1", True), ("U1", False), ("P2", True), ("U2", False)):
            cf.apply_action(s, "folder_save", {"name": name, "accountIds": ["a"], "pinned": pinned}, "u1", 1)
        ids = {f["name"]: f["id"] for f in cf.folders(s)}
        cf.apply_action(s, "folder_move", {"id": ids["P2"], "delta": -1}, "u1", 2)
        self.assertEqual([f["name"] for f in cf.folders(s)], ["P2", "P1", "U1", "U2"])
        cf.apply_action(s, "folder_move", {"id": ids["P1"], "delta": 1}, "u1", 3)  # edge of the pinned section: no change
        self.assertEqual([f["name"] for f in cf.folders(s)], ["P2", "P1", "U1", "U2"])
        with self.assertRaises(AlphaError):
            cf.apply_action(s, "folder_move", {"id": ids["U1"], "delta": 2}, "u1", 4)
        self.assertFalse(cf.apply_action(s, "channel_add", {}, "u1", 5))


class FolderStoreTest(unittest.TestCase):
    """Through the real mutation channel: tenancy, permissions and revision checks come for free."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Phase2Store(Path(self.tmp.name) / "p2.db", clock=lambda: 1_800_000_000.0)
        self.j = P2Journey(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_folders_persist_in_snapshot_with_revision_and_isolation(self):
        self.j.act("p2_channel_add", platform="Instagram", language="English")
        self.j.act("p2_channel_add", platform="Instagram", language="English")
        a, b = [c["id"] for c in self.j.state["phase2"]["channels"]]
        self.assertNotEqual(a, b)
        state = self.j.act("p2_folder_save", name="Festival", accountIds=[a, b], symbol="music", pinned=True)
        [folder] = state["phase2"]["channelFolders"]
        self.assertEqual(folder["accountIds"], [a, b])
        self.assertEqual(self.store.get(self.j.id, self.j.token)["state"]["phase2"]["channelFolders"][0]["name"], "Festival")
        stale = self.j.snapshot["revision"] - 1
        with self.assertRaises(AlphaError) as ctx:
            self.store.mutate(self.j.id, self.j.token, stale, "p2_folder_save", {"id": folder["id"], "name": "Renamed", "accountIds": [a]})
        self.assertEqual(ctx.exception.status, 409)
        other = P2Journey(self.store)
        self.assertEqual(other.state.get("phase2", {}).get("channelFolders", []), [])
        with self.assertRaises(AlphaError):
            other.store.mutate(other.id, other.token, other.snapshot["revision"], "p2_folder_save", {"name": "Steal", "accountIds": [a]})


if __name__ == "__main__":
    unittest.main()
