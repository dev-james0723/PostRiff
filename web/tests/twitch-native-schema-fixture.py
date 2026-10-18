"""Generate offline browser-form contracts from the actual native server registry.

Usage: PYTHONPATH=src python web/tests/twitch-native-schema-fixture.py /tmp/twitch-fields.json
Then: node web/tests/twitch-native-schema-contract.mjs /tmp/twitch-fields.json
No OAuth credentials or transport is used.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

from postriff_phase2.twitch_native import OPERATIONS, _validate_payload


def sample(field):
    if field.get("enum"):
        return field["enum"][0]
    kind = field["type"]
    if kind == "boolean":
        return False
    if kind in ("integer", "number"):
        return field.get("minimum", 0)
    if kind == "object":
        return {key: sample(item) for key, item in field["properties"].items()}
    if kind == "array":
        values = [sample(field["items"]) for _ in range(max(1, field.get("minItems", 0)))]
        for index, item in enumerate(values):
            if isinstance(item, dict) and "title" in item:
                item["title"] = "Choice " + str(index + 1)
        return values
    if field.get("format") == "date-time":
        return "2030-01-01T12:00:00Z"
    if field.get("format") == "iana-timezone":
        return "America/Indiana/Indianapolis"
    pattern = field.get("pattern", "")
    text = "x" * max(1, field.get("minLength", 0))
    if pattern:
        for candidate in ("#123456", "en", "1", text):
            if re.fullmatch(pattern, candidate):
                return candidate
        raise ValueError(f"Add a valid fixture for this native pattern: {pattern}")
    return text


rows = []
for action, operation in OPERATIONS.items():
    fields = operation.fields
    payload = {key: sample(field) for key, field in fields.items()}
    try:
        rows.append({"action": action, "fields": fields, "payload": _validate_payload(payload, fields)})
    except Exception as exc:
        raise AssertionError(f"Native field fixture failed for {action}") from exc

source = Path(__file__).resolve().parents[2] / "src/postriff_phase2/twitch_native.py"
fixture = {"sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(), "operations": rows}
Path(sys.argv[1]).write_text(json.dumps(fixture), encoding="utf-8")
print(f"Generated {len(rows)} native form contracts; no provider calls.")
