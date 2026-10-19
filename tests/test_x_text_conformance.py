"""Pinned official twitter-text v3 conformance. Synthetic; zero provider calls."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import unittest

import yaml  # Test-only, pinned in requirements-x-tests.txt.
from postriff_phase2._vendor.twitter_text import extract_urls, extract_urls_with_indices, parse_tweet

ROOT = Path(__file__).resolve().parent / "fixtures" / "x-twitter-text"
GROUPS = (
    ("validate", "WeightedTweetsWithDiscountedEmojiCounterTest", "parse"),
    ("validate", "UnicodeDirectionalMarkerCounterTest", "parse"),
    ("extract", "urls", "urls"),
    ("extract", "urls_with_indices", "indices"),
    ("extract", "urls_with_directional_markers", "indices"),
    ("extract", "tco_urls_with_params", "urls"),
)

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)

def run_pinned_fixtures():
    manifest = json.loads((ROOT / "manifest.json").read_bytes())
    assert manifest["upstream"] == "https://github.com/twitter/twitter-text"
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["commit"])
    vendor=Path(__file__).resolve().parents[1]/"src/postriff_phase2/_vendor/twitter_text"
    vm=json.loads((vendor/"VENDOR.json").read_bytes())
    assert (vm["package"],vm["version"],vm["wheelSha256"])==("twitter-text-parser","3.0.0",manifest["parser"]["wheelSha256"])
    for filename,evidence in vm["files"].items():
        assert hashlib.sha256((vendor/filename).read_bytes()).hexdigest()==evidence["sha256"],filename
    for name in ("validate.yml", "extract.yml", "v3.json", "LICENSE"):
        entry = manifest["files"][name]
        assert entry["sourceUrl"] == (manifest["upstream"].replace("github.com", "raw.githubusercontent.com")
            + "/" + manifest["commit"] + "/" + entry["sourcePath"])
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == entry["sha256"], name
    config = json.loads((ROOT / "v3.json").read_bytes())
    assert config == {"version":3,"maxWeightedTweetLength":280,"scale":100,"defaultWeight":200,
        "emojiParsingEnabled":True,"transformedURLLength":23,"ranges":[
        {"start":0,"end":4351,"weight":100},{"start":8192,"end":8205,"weight":100},
        {"start":8208,"end":8223,"weight":100},{"start":8242,"end":8247,"weight":100}]}
    assert b"Apache License" in (ROOT / "LICENSE").read_bytes()
    documents = {name: yaml.safe_load((ROOT / (name + ".yml")).read_bytes()) for name in ("validate", "extract")}
    counts, failures = {}, []
    for name, group, mode in GROUPS:
        rows = documents[name]["tests"][group]
        assert isinstance(rows, list) and rows, group
        counts[group] = {"cases": len(rows), "passed": 0}
        for i, row in enumerate(rows):
            try:
                actual = (parse_tweet(row["text"]).asdict() if mode == "parse" else
                    extract_urls(row["text"]) if mode == "urls" else extract_urls_with_indices(row["text"]))
                if canonical(actual) != canonical(row["expected"]):
                    failures.append({"group": group, "case": i, "description": row.get("description"),
                        "expected": row["expected"], "actual": actual})
                else:
                    counts[group]["passed"] += 1
            except Exception as error:
                failures.append({"group":group,"case":i,"exception":type(error).__name__ + ": " + str(error)})
    return {"synthetic":True,"providerCalls":0,"commit":manifest["commit"],"groups":counts,
        "cases":sum(v["cases"] for v in counts.values()),"passed":sum(v["passed"] for v in counts.values()),
        "failures":failures}

class TwitterTextConformance(unittest.TestCase):
    def test_pinned_official_v3_and_url_fixtures(self):
        report = run_pinned_fixtures()
        self.assertEqual(report["failures"], [], json.dumps(report,ensure_ascii=True,indent=2))

if __name__ == "__main__":
    report = run_pinned_fixtures()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    raise SystemExit(bool(report["failures"]))
