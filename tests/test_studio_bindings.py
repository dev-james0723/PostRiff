"""Local Studio binding set: the documents exist and describe the schema Studio enforces.

The hosted product binds the generic `postriff-*` skills, which describe cli_runtime.OUTPUT_SCHEMA.
Studio binds the personal set, which describes CANDIDATE_SCHEMA. Swapping one set for the other
tells the model to emit fields its strict schema rejects, so each set is checked against its own.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from james_au_social.studio_codex import BINDING_FILES, CANDIDATE_SCHEMA  # noqa: E402
from postriff_phase2.cli_runtime import OUTPUT_SCHEMA  # noqa: E402


def _fields(schema):
    return set(schema["properties"]) | set(schema["properties"]["variants"]["items"]["properties"])


class StudioBindingsTest(unittest.TestCase):
    def test_every_binding_document_exists(self):
        for name, relative in BINDING_FILES:
            self.assertTrue((ROOT / relative).is_file(), f"{name}: {relative} is missing")

    def test_binding_documents_name_only_fields_studio_accepts(self):
        accepted = _fields(CANDIDATE_SCHEMA)
        candidates = accepted | _fields(OUTPUT_SCHEMA)
        field = re.compile(r"`(" + "|".join(sorted(candidates, key=len, reverse=True)) + r")`|variants\[\]\.(\w+)")
        for name, relative in BINDING_FILES:
            text = (ROOT / relative).read_text(encoding="utf-8")
            named = {m.group(1) or m.group(2) for m in field.finditer(text)}
            self.assertEqual(named - accepted, set(),
                             f"{name} names fields CANDIDATE_SCHEMA rejects; the generic postriff-* skills describe the hosted schema")


if __name__ == "__main__":
    unittest.main()
