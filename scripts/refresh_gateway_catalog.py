"""Refresh the bundled AI Gateway model catalogue snapshot (src/postriff_phase2/gateway_catalog.json).

    PYTHONPATH=src python3 scripts/refresh_gateway_catalog.py

Reads the public catalogue (no credential), keeps language models' reasoning_options, supported_parameters and
max_tokens, and writes the snapshot the writer uses when the running app has not refreshed it in memory.
"""
import datetime
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_phase2 import gateway_catalog  # noqa: E402


def main():
    with urlopen(Request(gateway_catalog.CATALOG_URL, headers={"Accept": "application/json"}), timeout=30) as response:
        models = gateway_catalog.parse(json.loads(response.read()))
    if not models:
        sys.exit("The catalogue answer had no language models; the snapshot was left unchanged.")
    out = {"source": gateway_catalog.CATALOG_URL, "fetched": datetime.date.today().isoformat(),
           "note": "Language models only: reasoning_options, supported_parameters, max_tokens. Refreshed by scripts/refresh_gateway_catalog.py; production also refreshes it in memory at most once a day.",
           "models": dict(sorted(models.items()))}
    path = Path(gateway_catalog.__file__).with_name("gateway_catalog.json")
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(models)} language models written to {path}")


if __name__ == "__main__":
    main()
