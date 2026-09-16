#!/usr/bin/env python3
"""Bounded local privacy/artifact receipt; uses synthetic content only."""
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from postriff_alpha.templates import catalog
from test_postriff_profiles_auth import AgentAwareAcceptance

evidence = ROOT / "docs/postriff-phase-1/evidence"
baseline = json.loads((evidence / "baseline.json").read_text())
changed = []
for group in ("legacy_source_sha256", "private_skill_sha256"):
    for name, digest in baseline[group].items():
        path = Path(name) if name.startswith("/") else ROOT / name
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            changed.append(name)
if changed:
    raise SystemExit("Baseline files differ; review locally before claiming unchanged: " + ", ".join(changed))

release = ROOT / "docs/postriff-phase-1/released-templates"
release.mkdir(exist_ok=True)
for t in catalog():
    folder = release / t["id"]
    folder.mkdir(exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {t['id']}\ndescription: {t['description']}\n---\n\n# {t['name']}\n\nAlpha template v{t['version']}. No model or tools are granted by this file.\n\n" + "\n".join("- " + x for x in t["instructions"]) + "\n\nExample: " + t["example"] + "\n\nDependencies: " + (", ".join(t["dependencies"]) or "None") + "\n\nPrivate overrides are applied by the workspace host, never by modifying this template.\n")
    (folder / "configuration.schema.json").write_text(json.dumps(t["configurationSchema"], indent=2) + "\n")
(release / "release.json").write_text(json.dumps({"status": "founder-alpha-fixture-release", "version": "1.0.0", "entitlements": "same released templates for all plan and trial fixtures", "templates": [{"id": t["id"], "version": t["version"], "dependencies": t["dependencies"]} for t in catalog()]}, indent=2) + "\n")

forbidden = re.compile(r"james[-_]au|@jamesau|ouxianxing|James Au Studio|127\.0\.0\.1:4310|/Users/", re.I)
scanned = []
for folder in (ROOT / "studio/web/dist-alpha", release):
    for path in folder.rglob("*"):
        if path.is_file():
            if forbidden.search(path.read_text(errors="replace")):
                raise SystemExit("Private provenance leaked into customer artifact: " + str(path.relative_to(ROOT)))
            scanned.append(str(path.relative_to(ROOT)))
prompt = ROOT / "src/postriff_alpha/profile_builder_prompt.md"
if forbidden.search(prompt.read_text()):
    raise SystemExit("Private provenance in portable builder prompt")

packages = []
fixtures = evidence / "fixtures"
fixtures.mkdir(exist_ok=True)
case = AgentAwareAcceptance()
case.setUp()
try:
    for mode in ("personal", "niche", "business", "hybrid"):
        j = case.guided(mode)
        j.act("source", kind="sample")
        src = j.state["sources"][0]
        j.act("approve_source", sourceId=src["id"], factIds=[f["id"] for f in src["facts"]])
        j.act("source_done")
        j.act("runtime", selected="deterministic-preview")
        j.two()
        j.act("you_identity", value="A fictional community-learning agency")
        j.act("you_art_refresh")
        j.act("save")
        for kind, payload in (("drafts", case.store.export(j.id, j.token)), ("profile", case.store.export_profile(j.id, j.token))):
            z = zipfile.ZipFile(io.BytesIO(payload))
            assert z.testzip() is None
            manifest = json.loads(z.read("manifest.json"))
            for name, digest in manifest["files"].items():
                assert hashlib.sha256(z.read(name)).hexdigest() == digest, name
            for name in z.namelist():
                content = z.read(name).decode()
                assert not forbidden.search(content), name
                assert 'credential_hash' not in content and 'principalKey' not in content and '.auth-key' not in content, name
            output = fixtures / f"fictional-{mode}-{kind}.zip"
            output.write_bytes(payload)
            packages.append({"path": str(output.relative_to(ROOT)), "sha256": hashlib.sha256(payload).hexdigest(), "files": z.namelist(), "state": "synthetic-fixture-only"})
finally:
    case.tearDown()
report = {"status": "passed", "privateSkillsUnchanged": len(baseline["private_skill_sha256"]), "legacySourcesUnchanged": len(baseline["legacy_source_sha256"]), "customerArtifactsScanned": scanned, "builderPromptNeutral": True, "packages": packages, "scope": "These checks prove fixture isolation and packaging, not customer validation, production authentication or real-model qualification."}
(evidence / "privacy-artifact-validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({k: report[k] for k in ("status", "privateSkillsUnchanged", "legacySourcesUnchanged", "builderPromptNeutral")}))
print(f"Verified {len(packages)} synthetic ZIPs, CRCs, manifest hashes and neutral customer artifacts.")
