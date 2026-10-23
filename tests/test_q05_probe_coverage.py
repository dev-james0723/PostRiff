"""Router coverage for the Q-05 probe (no database needed).

Enumerates every workspace-scoped route family of the hosted API in RC1 and fails if any
family is neither LIVE-attacked by the probe matrix (COVERED_FAMILIES) nor named, with a
written reason, in the exclusion list (EXCLUDED_FAMILIES). This is the tripwire the brief
asks for: a new `/api/workspaces/<id>/<thing>` route cannot be added without someone either
giving the probe a case for it or consciously excluding it with a reason.
"""
import re
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import q05_tenant_probe as probe  # noqa: E402


def extract_hosted_families():
    """Workspace-scoped first-segment families referenced by the hosted router and sub-routers."""
    src = (REPO / "src/postriff_phase2/hosted_app.py").read_text()
    fams = set()
    for m in re.finditer(r'parts\[3\]\s*==\s*["\']([a-z0-9-]+)["\']', src):
        fams.add(m.group(1))
    for m in re.finditer(r'parts\[3\]\s*in\s*\(([^)]*)\)', src):
        fams.update(re.findall(r'["\']([a-z0-9-]+)["\']', m.group(1)))
    for m in re.finditer(r'parts\[3:5\]\s*==\s*\[["\']([a-z0-9-]+)["\']', src):
        fams.add(m.group(1))
    for m in re.finditer(r"parts\[3:\]\s*==\s*\[['\"]([a-z0-9-]+)['\"]", src):
        fams.add(m.group(1))
    if "coworker_http.RESOURCES" in src:
        # the coworker sub-router matches parts[3] against its RESOURCES tuple
        from postriff_phase2.coworker import http as coworker_http
        fams.update(coworker_http.RESOURCES)
    # these tokens are matched by the regex but belong to /api/oauth and /api/tools, not workspaces
    return fams


def covered_families_from_matrix():
    """The first path segment each attack case targets under /api/workspaces/<id>/ ('get' for
    the bare workspace route)."""
    cfg = probe.Config({"Q05_WORKSPACE_A": "A", "Q05_WORKSPACE_B": "B",
                        "Q05_TOKEN_A": "t", "Q05_TOKEN_B": "t", "Q05_BASE_URL": "http://x"})
    disc = {}
    for key in ("A", "B"):
        d = probe.Discovery(key, key)
        d.ok = True
        d.revision = 0
        d.connections = [f"{key}-conn"]
        d.all_channel_ids = [f"{key}-conn"]
        d.identities = [f"{key}-identity"]
        d.destinations = {f"{key}-conn": [f"{key}-dest"]}
        d.jobs = [(f"{key}-job", "0" * 64)]
        d.members = [f"{key}-member"]
        disc[key] = d
    cfg.victim_oauth_state = {"A": "state-a", "B": "state-b"}
    flags = types.SimpleNamespace(allow_writes=True, allow_send_risk=True, victim_is_synthetic=True)
    cases = probe.build_matrix(disc, cfg, flags)
    covered = set()
    for c in cases:
        if c.direction not in ("A->B", "B->A") or not c.template:
            continue
        m = re.match(r"/api/workspaces/<[AB]\.workspace>(?:/([a-z0-9-]+))?", c.template)
        covered.add(m.group(1) if m and m.group(1) else "get")
    return covered


class Q05Coverage(unittest.TestCase):
    def test_every_workspace_family_is_covered_or_excluded(self):
        families = extract_hosted_families()
        self.assertIn("channels", families, "extractor sanity: expected to see the channels family")
        covered = covered_families_from_matrix()
        unclassified = []
        for fam in sorted(families):
            if fam in probe.COVERED_FAMILIES or fam in probe.EXCLUDED_FAMILIES:
                continue
            unclassified.append(fam)
        self.assertFalse(
            unclassified,
            "hosted workspace route families neither covered by the probe matrix nor excluded "
            "with a reason: " + ", ".join(unclassified) +
            "  (add a case to scripts/q05_tenant_probe.py build_matrix, or add it to "
            "EXCLUDED_FAMILIES with a written reason)")
        # COVERED_FAMILIES must not lie: each claimed family is actually in the built matrix.
        for fam in probe.COVERED_FAMILIES:
            self.assertIn(fam, covered,
                          f"COVERED_FAMILIES claims '{fam}' but build_matrix emits no case for it")

    def test_exclusions_have_written_reasons(self):
        for fam, reason in probe.EXCLUDED_FAMILIES.items():
            self.assertIsInstance(reason, str)
            self.assertGreaterEqual(len(reason.strip()), 12,
                                    f"exclusion '{fam}' needs a real written reason")


if __name__ == "__main__":
    unittest.main()
