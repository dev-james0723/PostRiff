"""Red/green regression for orphan gitlinks that break Depot checkout cleanup.

No CI invocation, network, submodule update, or project mutation.
"""
import configparser
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = {
    "vendor/xiaohongshu-mcp-v2.5.0-login-fix": "6583124dfda92312b6bc19a042a6acfae63fe498",
    "vendor/xiaohongshu-mcp-v2.5.0-rednote-candidate": "9f073e1bc31cdd5a6a304e8f09e7978b542f4d02",
}
UPSTREAM = "https://github.com/xpzouying/xiaohongshu-mcp.git"


class DepotGitlinkCheckout(unittest.TestCase):
    def test_vendor_gitlinks_have_explicit_nonfetching_mappings(self):
        tracked = subprocess.check_output(
            ["git", "ls-files", "--stage", "--", "vendor"], cwd=ROOT, text=True)
        links = {}
        for line in tracked.splitlines():
            prefix, path = line.split("\t", 1)
            mode, sha, stage = prefix.split()
            if mode == "160000":
                links[path] = sha
        self.assertEqual(links, VENDOR, "Do not delete, repin or fetch the vendor checkouts")

        modules = configparser.ConfigParser(interpolation=None)
        self.assertEqual(modules.read(ROOT / ".gitmodules"), [str(ROOT / ".gitmodules")])
        for path in VENDOR:
            with self.subTest(path=path):
                key = f'submodule "{path}"'
                self.assertTrue(modules.has_section(key))
                self.assertEqual(modules.get(key, "path"), path)
                self.assertEqual(modules.get(key, "url"), UPSTREAM)
                self.assertEqual(modules.get(key, "update"), "none")

    def test_submodule_cleanup_does_not_require_a_missing_url(self):
        result = subprocess.run(["git", "submodule", "foreach", "--recursive", "true"],
                                cwd=ROOT, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr[:500])

    def test_local_patch_checkout_retains_token_only_until_first_custom_step(self):
        workflow = (ROOT / ".depot/workflows/linkedin-qualification-once.yml").read_text()
        self.assertIn("persist-credentials: true", workflow)
        self.assertIn("Remove checkout authorization before running project code", workflow)
        self.assertIn("git config --local --unset-all http.https://github.com/.extraheader", workflow)
        self.assertIn("timeout-minutes: 20", workflow)


if __name__ == "__main__":
    unittest.main()
