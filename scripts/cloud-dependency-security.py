#!/usr/bin/env python3
"""Cloud-only security checks after JCB's immutable npm ci; never changes a lock."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


EXPECTED = {"sharp": "0.35.5", "source-map-js": "1.2.2", "tinypool": "2.1.2"}
LOCK_SHA256 = "c347e642ee841cdcc2ca1a8450c4acc09cd391ea6962735c7b1f31fe6c551504"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, cwd, allowed=(0,), timeout=120):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    require(result.returncode in allowed, f"{command[0]} {command[1]} exited {result.returncode}")
    # Raw npm output can include user configuration; only print parsed, bounded results.
    require(len(result.stdout) <= 4_000_000, "Unexpectedly large command output")
    return result.stdout


def main():
    require(sys.platform == "linux" and os.environ.get("CI", "").lower() in {"1", "true"},
            "Cloud Linux CI is required; do not run Node/npm checks on the Mac")
    package = Path(__file__).resolve().parents[1] / "web"
    manifest_path, lock_path = package / "package.json", package / "package-lock.json"
    before = {p.name: digest(p) for p in (manifest_path, lock_path)}
    require(before["package-lock.json"] == LOCK_SHA256, "Reviewed lockfile changed; re-review before validation")
    manifest, lock = (json.loads(p.read_text()) for p in (manifest_path, lock_path))
    require(manifest["dependencies"]["sharp"] == "^0.35.5", "Sharp dependency does not match upstream release")
    for name, value in {"sharp": "^0.35.5", "tinypool": "2.1.2", "source-map-js": "1.2.2"}.items():
        require(manifest["overrides"].get(name) == value, f"Missing reviewed override: {name}")
    for section in ("dependencies", "devDependencies"):
        require(manifest.get(section, {}) == lock["packages"][""].get(section, {}),
                f"Manifest and lock root disagree: {section}")
    for name, version in EXPECTED.items():
        entries = [v for k, v in lock["packages"].items() if k.endswith("/" + name)]
        require(bool(entries) and all(v.get("version") == version for v in entries),
                f"Unexpected locked version: {name}")
    require(lock["packages"]["node_modules/tinypool"].get("dev") is True,
            "Tinypool unexpectedly entered the production dependency graph")

    tree = json.loads(run(["npm", "ls", *EXPECTED, "--all", "--json"], package))
    graph = {name: [] for name in EXPECTED}

    def visit(node):
        for name, entry in node.get("dependencies", {}).items():
            if name in graph:
                graph[name].append(entry.get("version"))
            visit(entry)

    visit(tree)
    require(all(versions and set(versions) == {EXPECTED[name]} for name, versions in graph.items()),
            "Installed dependency graph differs from reviewed target versions")
    audit = json.loads(run(["npm", "audit", "--json", "--registry=https://registry.npmjs.org"],
                          package, allowed=(0, 1)))
    require("error" not in audit and isinstance(audit.get("metadata", {}).get("vulnerabilities"), dict),
            "npm advisory service did not return a usable result")
    counts = audit["metadata"]["vulnerabilities"]
    require(all(counts.get(level) == 0 for level in ("info", "low", "moderate", "high", "critical", "total")),
            "npm audit reported a finding; review it before release, do not auto-fix")

    with tempfile.TemporaryDirectory(prefix="rafii-deps-smoke-", dir=package) as scratch:
        directory = Path(scratch)
        worker = directory / "worker.mjs"
        worker.write_text("export function formatterProbe(task) { return task.value * 2; }\n")
        native = json.loads(run(["node", "-e", r'''
const assert = require('node:assert/strict');
const sharp = require('sharp');
(async () => {
  assert.equal(sharp.versions.sharp, '0.35.5');
  assert.equal(typeof sharp.versions.rsvg, 'string');
  const parts = sharp.versions.rsvg.split('.').map(Number);
  assert(parts[0] > 2 || (parts[0] === 2 && (parts[1] > 63 || (parts[1] === 63 && parts[2] >= 2))));
  sharp.concurrency(1);
  const png = await sharp({create: {width: 2, height: 2, channels: 3, background: '#4488cc'}}).png().toBuffer();
  const jpeg = await sharp(png).jpeg().toBuffer();
  assert.equal((await sharp(jpeg).metadata()).format, 'jpeg');
  const svg = Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="#4488cc"/></svg>');
  assert.equal((await sharp(await sharp(svg).png().toBuffer()).metadata()).width, 2);
  const {default: Tinypool} = await import('tinypool');
  const pool = new Tinypool({filename: process.argv[1], minThreads: 1, maxThreads: 1, runtime: 'child_process'});
  try { assert.equal(await pool.run({value: 21}, {name: 'formatterProbe'}), 42); }
  finally { await pool.destroy(); }
  console.log(JSON.stringify({sharp: sharp.versions.sharp, vips: sharp.versions.vips, rsvg: sharp.versions.rsvg, imageSmoke: 'PASS', namedChildProcessWorker: 'PASS'}));
})().catch(error => { console.error(error.message); process.exitCode = 1; });
''', str(worker)], package))
        markdown = directory / "formatter.md"
        # The repository deliberately ignores Markdown; use an isolated smoke config.
        (directory / ".oxfmtrc.json").write_text('{"ignorePatterns": []}\n')
        original = "#   Dependency smoke\n\n-   one\n-   two\n"
        markdown.write_text(original)
        formatter = package / "node_modules" / ".bin" / "oxfmt"
        run([str(formatter), "--write", str(markdown)], directory)
        require(markdown.read_text() != original, "Formatter did not exercise Markdown worker output")
        run([str(formatter), "--check", str(markdown)], directory)

    require(before == {p.name: digest(p) for p in (manifest_path, lock_path)},
            "Security checks changed the manifest or lockfile")
    print(json.dumps({"validation": "dependency-security", "status": "PASS", "hashes": before,
                      "installedVersions": {name: sorted(set(v)) for name, v in graph.items()},
                      "audit": counts, "native": native, "formatterMarkdown": "PASS"}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Dependency security validation failed: {error}", file=sys.stderr)
        sys.exit(1)
