"""Keep every pinned research finding in the native implementation roadmap."""
import csv
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/creative-intelligence"
STATES = {"Verified equivalent", "Implemented but unverified", "Partial", "Missing", "Externally blocked", "Legally restricted"}


class InventoryCoverage(unittest.TestCase):
    def test_all_source_and_documented_behaviors_keep_their_evidence_and_acceptance_case(self):
        reference = json.loads((DOCS / "reference/capabilities.json").read_text())
        with (DOCS / "parity.csv").open(newline="") as matrix:
            native_rows = list(csv.DictReader(matrix))
        by_id = {r["id"]: r for r in native_rows}
        self.assertEqual(len(by_id), len(native_rows))
        self.assertCountEqual(by_id, (r["id"] for r in reference["rows"]))
        self.assertEqual(sum(r["evidence_level"] == "source verified" for r in reference["rows"]), 67)
        for item in reference["rows"]:
            with self.subTest(capability=item["id"]):
                row = by_id[item["id"]]
                self.assertTrue(all(isinstance(v, str) and v.strip() for v in row.values()))
                self.assertEqual(row["reference_revision"], reference["reference_revision"])
                self.assertEqual(row["reference_version"], reference["reference_version"])
                self.assertEqual(row["reference_evidence"].split(" | "), item["evidence"])
                self.assertEqual(row["acceptance_criteria"], item["criterion"])
                self.assertIn(row["implementation_status"], STATES)
                for native_path in row["rafii_sources"].split(" | "):
                    self.assertTrue((ROOT / native_path).is_file(), native_path)
