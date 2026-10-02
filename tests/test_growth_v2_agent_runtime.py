"""RAFII Product Growth tools on the production Agent Runtime v2 path (AC28; review finding: the slice tools were only
registered by `skill_registry.registered_tools()`, which only CI and the lock call).

A fresh interpreter constructs `AgentRuntimeService` exactly as the hosted app does and never calls a slice's
`register()` itself: every growth-v2 tool must then be in the runtime registry and in the specialist scopes its slice
names, with voice parity. In-process checks cover idempotency and that one broken slice never keeps the others out
(strict mode still fails CI)."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from postriff_phase2 import growth_v2_agent_tools  # noqa: E402
from postriff_phase2.agent_runtime_v2 import domain_tools, specialists, tool_adapter  # noqa: E402

EXPECTED = ("first_week_get", "first_week_start", "first_week_plan", "source_upload_status", "source_from_upload", "relationship_list",
            "relationship_upsert", "followup_transition", "results_summary", "result_declare", "tracking_link_create", "series_list",
            "series_prepare", "episode_prepare", "visual_pack_prepare", "visual_pack_edit", "visual_pack_export", "brief_read", "brief_action",
            "proof_read", "strategy_decide")

PROBE = r"""
import json, types
from postriff_phase2.agent_runtime_v2 import specialists, tool_adapter
from postriff_phase2.agent_runtime_v2.service import AgentRuntimeService
names = json.loads(NAMES)
before = [n for n in names if n in tool_adapter.REGISTRY]
AgentRuntimeService(types.SimpleNamespace(), cfg=types.SimpleNamespace())   # the hosted app's construction path
import importlib
from postriff_phase2 import growth_v2_agent_tools
scopes = {}
for slice_name in growth_v2_agent_tools.SLICES:
    module = importlib.import_module(slice_name)
    for tool, agents in module.TOOL_SCOPES.items():
        scopes[tool] = agents
print(json.dumps({"before": before, "registered": [n for n in names if n in tool_adapter.REGISTRY],
                  "voice": {n: tool_adapter.REGISTRY[n].spec.voice for n in names if n in tool_adapter.REGISTRY},
                  "scoped": {tool: [a for a in agents if tool in specialists.EXTRA_SCOPES.get(a, [])] for tool, agents in scopes.items()},
                  "wanted": scopes}))
"""


class RuntimePathTest(unittest.TestCase):
    def test_the_runtime_constructor_registers_every_slice_tool_and_scope(self):
        env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}{os.pathsep}{REPO / 'tests'}", "NAMES": json.dumps(EXPECTED)}
        script = "import os\nNAMES = os.environ['NAMES']\n" + PROBE
        out = subprocess.run([sys.executable, "-c", script], cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        found = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(found["before"], [], "nothing registers these tools before the runtime starts")
        self.assertEqual(found["registered"], list(EXPECTED))
        self.assertTrue(all(found["voice"].values()), found["voice"])   # voice and text have the same tools
        self.assertEqual(set(found["wanted"]), set(EXPECTED))
        for tool, agents in found["wanted"].items():
            self.assertEqual(found["scoped"][tool], agents, tool)


class RegistrationTest(unittest.TestCase):
    def test_ensure_registered_is_idempotent_and_rebinds_scopes(self):
        domain_tools.ensure_registered()
        count = len(tool_adapter.REGISTRY)
        specialists.EXTRA_SCOPES.get("creative", []).clear()   # a runtime that reset its extension points
        domain_tools.ensure_registered()
        self.assertEqual(len(tool_adapter.REGISTRY), count)
        self.assertIn("visual_pack_export", specialists.EXTRA_SCOPES["creative"])
        self.assertEqual(len(specialists.EXTRA_SCOPES["creative"]), len(set(specialists.EXTRA_SCOPES["creative"])))

    def test_one_broken_slice_never_keeps_the_others_out_but_fails_strict_mode(self):
        from postriff_phase2.series import agent_tools as series_tools
        domain_tools.ensure_registered()
        with mock.patch.object(series_tools, "register", side_effect=RuntimeError("broken slice")):
            with self.assertLogs("postriff.agent_runtime", "ERROR"):
                modules = growth_v2_agent_tools.register()
            self.assertNotIn(series_tools, modules)
            self.assertEqual(len(modules), len(growth_v2_agent_tools.SLICES) - 1)
            with self.assertRaises(RuntimeError):
                growth_v2_agent_tools.register(strict=True)
        self.assertIn("growth_v2_agent_tools", " ".join(domain_tools.EXTENSION_MODULES))


if __name__ == "__main__":
    unittest.main()
