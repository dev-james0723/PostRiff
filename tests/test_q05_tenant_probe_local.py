"""Local validation of the Q-05 cross-tenant isolation probe against the real RC1 code.

Stands up a throwaway PostgreSQL 16 cluster, runs the real hosted application with stub
auth and a mock Discord transport, and runs scripts/q05_tenant_probe.py against two tenants
A and B. Every attack case must be denied with no side effect; every control must succeed.

Skips cleanly when the PostgreSQL 16 server binaries or psycopg are unavailable, so it runs
under the repo's normal `python -m unittest discover -s tests` without special setup.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))

try:
    import psycopg  # noqa: F401
    HAVE_PSYCOPG = True
except Exception:
    HAVE_PSYCOPG = False

from q05_backend import pg_available  # noqa: E402

REASON = "needs PostgreSQL 16 server binaries (POSTRIFF_PG_BIN or /usr/lib/postgresql/16/bin) and psycopg"


def run_backend(*flags):
    cmd = [sys.executable, str(REPO / "tests/q05_backend.py"), "run", *flags]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    assert proc.stdout, "backend produced no JSON. stderr tail:\n" + proc.stderr[-2000:]
    return json.loads(proc.stdout.splitlines()[-1])


@unittest.skipUnless(HAVE_PSYCOPG and pg_available(), REASON)
class Q05LocalHarness(unittest.TestCase):
    def test_full_run_every_case_passes(self):
        result = run_backend("--allow-writes", "--allow-send-risk", "--victim-is-synthetic")
        self.assertEqual(result["status"], "ran", result)
        summary = result["summary"]
        # Every case that ran passed; nothing failed, inconclusive, or undiscovered.
        self.assertEqual(result["probeExit"], 0, result.get("probeStderr"))
        self.assertEqual(summary["failed"], 0,
                         [c for c in result["cases"] if c["verdict"] == "FAIL"])
        self.assertEqual(summary["inconclusive"], 0)
        self.assertEqual(summary["undiscovered"], 0)
        verdicts = {c["case"]: c["verdict"] for c in result["cases"]}
        self.assertNotIn("FAIL", verdicts.values())
        # NOT RUN only where the build does not serve the route at all (the sender-name cases before RC2)
        not_run = [c for c in result["cases"] if c["verdict"] == "NOT_RUN"]
        if result.get("senderNames"):
            self.assertEqual(not_run, [])
        else:
            self.assertEqual([c["case"] for c in not_run if not c["note"].startswith("not-applicable:")
                              or ".sender." not in c["case"]], [])

        # Coverage: both directions, reads and writes, a send-blast case, and controls.
        directions = {c["direction"] for c in result["cases"]}
        self.assertIn("A->B", directions)
        self.assertIn("B->A", directions)
        self.assertGreaterEqual(summary["reads"], 20)
        self.assertGreaterEqual(summary["writes"], 20)
        self.assertGreaterEqual(summary["blast_send"], 2)
        self.assertGreaterEqual(summary["controls_passed"], 8)

        # The independent proofs the HTTP probe cannot make on its own.
        self.assertEqual(result["messageSendsDuringRun"], 0,
                         "mock Discord transport saw a message send during the run")
        for key in ("A", "B"):
            self.assertTrue(result["dbSideEffect"][key]["ok"],
                            f"DB-level side effect on tenant {key}: {result['dbSideEffect'][key]}")

        if result.get("senderNames"):
            # Customer sender names (RC2): the probe marks its attack phase, and in EXACTLY that phase nothing
            # changed in either tenant and the mock Discord saw no request at all.
            attack = result["attackPhase"]
            self.assertIsNotNone(attack, "the probe did not mark its attack phase")
            self.assertEqual((attack["providerCalls"], attack["providerWrites"], attack["messageSends"],
                              attack["nicknameChanged"]), (0, 0, 0, False), attack)
            for key in ("A", "B"):
                self.assertEqual(attack["dbSideEffect"][key]["revisionDelta"], 0, attack["dbSideEffect"][key])
            self.assertGreaterEqual(summary["sender_cases"], 70)
            self.assertEqual(summary["sender_passed"], summary["sender_cases"])
            # send-level and same-server scenarios through the real app and worker against the mock Discord
            self.assertTrue(result["scenariosOk"],
                            {k: [c for c, ok in v["checks"].items() if not ok] or v["detail"]
                             for k, v in result["scenarios"].items() if not v["ok"]})
            self.assertEqual(set(result["scenarios"]),
                             {"name_pollution", "switch_off", "nickname_authority", "nickname_hold"})

    def test_default_readonly_plan_cannot_send(self):
        # With no --allow-writes the write cases are gated off and nothing can reach Discord.
        result = run_backend()
        self.assertEqual(result["status"], "ran")
        self.assertEqual(result["probeExit"], 0, result.get("probeStderr"))
        self.assertEqual(result["messageSendsDuringRun"], 0)
        writes = [c for c in result["cases"] if c["kind"] == "write"]
        self.assertTrue(writes)
        served = (lambda c: result.get("senderNames") or ".sender." not in c["case"])
        for c in writes:
            self.assertEqual(c["verdict"], "NOT_RUN", c)
            self.assertTrue(c["note"].startswith("gated:" if served(c) else "not-applicable:"), c)
        reads = [c for c in result["cases"] if c["kind"] == "read"]
        self.assertTrue(reads)
        for c in reads:
            self.assertEqual(c["verdict"], "PASS" if served(c) else "NOT_RUN", c)


if __name__ == "__main__":
    unittest.main()
