"""Machine-readable verification report for the Rafii Adaptive Social Coworker (never edited by hand).

    PYTHONPATH=src:tests POSTRIFF_RESEARCH=0 POSTRIFF_LOCAL_CLI=0 python scripts/rafii_coworker_verify.py [--full] [--web]

Runs the gates it can run in-process or as subprocesses (capability registry, the coworker unit suites, optionally
the full Python suite and the web contract tests, the secret scan) and folds in the evidence files the browser and
PostgreSQL gates write themselves (evidence/pg-coworker.json from tests/phase2/postgres_coworker.py with
RAFII_COWORKER_EVIDENCE set; evidence/email-render.json from scripts/rafii_email_render_check.cjs). Also regenerates
NOTIFICATION_CATALOG.md from the code. Output: docs/design/site-agent/adaptive-social-coworker/evidence/verification.json.
Every result carries the command that produced it. Nothing here calls a live provider.
"""
import argparse
import datetime as dt
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DOCS = ROOT / "docs/design/site-agent/adaptive-social-coworker"
EVIDENCE = DOCS / "evidence"
UNIT_MODULES = ("tests.test_rafii_skill_registry", "tests.test_rafii_humanizer", "tests.test_rafii_notifications", "tests.test_rafii_workflows",
                "tests.test_rafii_runtime_convergence", "tests.test_rafii_review_fixes")
NODE = os.environ.get("RAFII_NODE", "/opt/homebrew/opt/node@24/bin/node")


def run(command, env=None, timeout=1800):
    started = dt.datetime.now(dt.timezone.utc)
    result = subprocess.run(command, cwd=ROOT, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)
    return {"command": " ".join(command), "exitCode": result.returncode, "startedAt": started.isoformat(), "tail": (result.stdout + result.stderr)[-3000:]}


def unittest_counts(output):
    ran = re.search(r"Ran (\d+) tests?", output)
    failed = re.search(r"FAILED \((.*?)\)", output)
    skipped = re.search(r"skipped=(\d+)", output)
    counts = {"ran": int(ran.group(1)) if ran else 0, "failures": 0, "errors": 0, "skipped": int(skipped.group(1)) if skipped else 0}
    if failed:
        for part in failed.group(1).split(","):
            key, _, value = part.strip().partition("=")
            if key in ("failures", "errors") and value.isdigit():
                counts[key] = int(value)
    return counts


def registry_gate():
    from postriff_phase2 import skill_registry
    report = skill_registry.check()
    return {"gate": "capability_registry", "command": "python scripts/rafii_skill_registry.py --check", "status": "PASS" if report.ok else "FAIL", **report.as_dict()}


def unit_gate(modules, name):
    result = run([sys.executable, "-m", "unittest", *modules], env={"PYTHONPATH": "src:tests", "POSTRIFF_RESEARCH": "0", "POSTRIFF_LOCAL_CLI": "0", "PYTHONDONTWRITEBYTECODE": "1"})
    counts = unittest_counts(result["tail"])
    ok = result["exitCode"] == 0 and counts["ran"] > 0
    return {"gate": name, "status": "PASS" if ok else "FAIL", "counts": counts, "command": result["command"], "exitCode": result["exitCode"], "at": result["startedAt"],
            **({"tail": result["tail"][-1500:]} if not ok else {})}


# What each evidence file covers: when any of these changed after the evidence was written, the gate is STALE (the
# evidence no longer describes the code), never PASS.
COVERS = {
    "postgres_coworker_scenarios": ("src/postriff_phase2/coworker/**/*.py", "src/postriff_phase2/notifications/**/*.py", "migrations/postriff/024_*.sql",
                                    "migrations/postriff/025_*.sql", "tests/phase2/postgres_coworker.py", "src/postriff_phase2/email.py"),
    "email_render_accessibility": ("src/postriff_phase2/notifications/email_render.py", "src/postriff_phase2/notifications/email_locales.json",
                                   "scripts/rafii_email_render_check.cjs", "scripts/rafii_email_previews.py"),
    "web_browser_coworker": ("web/src/features/coworker/**/*", "web/src/lib/coworker/**/*", "web/src/app/app/weekly/**/*", "web/src/app/app/workspace/personalization/**/*",
                             "web/public/sw.js", "web/tests/coworker-browser.cjs", "src/postriff_phase2/coworker/**/*.py"),
}


def newest_source(name):
    newest, which = 0.0, None
    for pattern in COVERS.get(name, ()):
        for path in ROOT.glob(pattern):
            if path.is_file() and path.stat().st_mtime > newest:
                newest, which = path.stat().st_mtime, str(path.relative_to(ROOT))
    return newest, which


def stale(name, evidence_mtime):
    newest, which = newest_source(name)
    return (which if newest > evidence_mtime else None)


def file_gate(name, path, command, summary_key="summary"):
    if not path.is_file():
        return {"gate": name, "status": "NOT_RUN", "reason": f"{path.relative_to(ROOT)} not found; run: {command}"}
    data = json.loads(path.read_text())
    summary = data.get(summary_key) or {}
    failed = summary.get("FAIL", summary.get("failed", 0)) or 0
    errors = summary.get("errors") or []
    ok = failed == 0 and not errors and (summary.get("PASS", summary.get("passed", 0)) or 0) > 0
    changed = stale(name, path.stat().st_mtime)
    status = "STALE" if ok and changed else "PASS" if ok else "FAIL"
    return {"gate": name, "status": status, "summary": summary, "evidence": str(path.relative_to(ROOT)), "command": command,
            "generatedAt": data.get("generatedAt"), "execution": data.get("execution"), "mode": "evidence file (not re-run by this script)",
            **({"staleBecause": f"{changed} changed after the evidence was written; re-run: {command}"} if changed else {})}


def browser_gate():
    """UI browser QA (Chromium and WebKit, axe): every recorded check must be ok, and both browsers must have run."""
    command = "node web/tests/coworker-browser.cjs --browser=chromium|webkit (local next dev + local API harness; synthetic data)"
    per, at = {}, {}
    for browser in ("chromium", "webkit"):
        path = DOCS / f"web/evidence/{browser}-results.json"
        if not path.is_file():
            return {"gate": "web_browser_coworker", "status": "NOT_RUN", "reason": f"{path.relative_to(ROOT)} not found; run: {command}"}
        data = json.loads(path.read_text())
        results = data.get("results") or []
        per[browser] = {"ran": len(results), "ok": sum(1 for r in results if r.get("ok") is True)}
        at[browser] = data.get("at")
    ok = all(v["ran"] > 0 and v["ok"] == v["ran"] for v in per.values())
    oldest = min((DOCS / f"web/evidence/{b}-results.json").stat().st_mtime for b in ("chromium", "webkit"))
    changed = stale("web_browser_coworker", oldest)
    return {"gate": "web_browser_coworker", "status": "STALE" if ok and changed else "PASS" if ok else "FAIL", "summary": per,
            "evidence": str((DOCS / "web/evidence").relative_to(ROOT)), "command": command, "generatedAt": at, "execution": "local only (not live)",
            "mode": "evidence file (not re-run by this script)", **({"staleBecause": f"{changed} changed after the evidence was written"} if changed else {})}


def secret_gate():
    result = run([sys.executable, "scripts/consumer_ready_secrets.py"], env={"PYTHONPATH": "src:tests"})
    try:
        payload = json.loads(result["tail"].strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload = {}
    ok = result["exitCode"] == 0 and payload.get("status") == "PASS"
    return {"gate": "secret_scan", "status": "PASS" if ok else "FAIL", "files": payload.get("files"), "unexpected": len(payload.get("unexpected") or []),
            "command": result["command"], "exitCode": result["exitCode"]}


def web_gate():
    tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "web/tests").glob("*.test.*")) + ["web/src/lib/locales/core.test.mjs"]
    result = run([NODE, "--test", *tests])
    passed = re.search(r"(?:#|ℹ) pass (\d+)", result["tail"])   # TAP ("# pass") or Node's spec reporter ("ℹ pass")
    failed = re.search(r"(?:#|ℹ) fail (\d+)", result["tail"])
    ok = result["exitCode"] == 0
    return {"gate": "web_contract_tests", "status": "PASS" if ok else "FAIL", "pass": int(passed.group(1)) if passed else None, "fail": int(failed.group(1)) if failed else None,
            "command": result["command"][:200] + ("…" if len(result["command"]) > 200 else ""), "exitCode": result["exitCode"]}


def web_static_gates():
    """TypeScript and lint over the whole web app (the coworker UI included), with the same node as the tests."""
    env = {"PATH": f"{os.path.dirname(NODE)}:{os.environ.get('PATH', '')}"}
    npm = os.path.join(os.path.dirname(NODE), "npm")
    gates = []
    for script in ("typecheck", "lint"):
        result = run([npm, "--prefix", "web", "run", script], env=env)
        gates.append({"gate": f"web_{script}", "status": "PASS" if result["exitCode"] == 0 else "FAIL", "command": f"npm --prefix web run {script}",
                      "exitCode": result["exitCode"], "tail": result["tail"][-300:]})
    return gates


def notification_catalog_md():
    from postriff_phase2.notifications import catalog, email_render
    rows = ["| Event | Category | Severity | Recipients (permission) | In-app | Email | Push | Transactional | Template |", "|---|---|---|---|---|---|---|---|---|"]
    for name, spec in catalog.EVENTS.items():
        rows.append(f"| `{name}` | {spec['category']} | {spec['severity']} | {spec['audience']} | always | {spec['email']} | {spec['push']} | "
                    f"{'yes' if spec.get('transactional') else 'no'} | `{spec['template']}` |")
    index = json.loads((EVIDENCE / "email" / "index.json").read_text()) if (EVIDENCE / "email" / "index.json").is_file() else {"previews": []}
    previews = ["| Template | Locale | Subject | Preheader | HTML bytes | List-Unsubscribe |", "|---|---|---|---|---|---|"]
    for item in index["previews"]:
        if item["locale"] in ("en", "zh-Hant-HK"):
            previews.append(f"| `{item['template']}` | {item['locale']} | {item['subject']} | {item['preheader']} | {item['htmlBytes']} | {'yes' if item['listUnsubscribe'] else 'no (transactional)'} |")
    text = ("# Notification event and email template catalogue\n\n"
            "Generated by `scripts/rafii_coworker_verify.py` from `notifications/catalog.py` and `evidence/email/index.json`. Do not edit by hand.\n\n"
            f"Catalogue version `{catalog.CATALOG_VERSION}` · template version `{email_render.TEMPLATE_VERSION}` · locales en, zh-Hant-HK (also used for yue), zh-Hant, zh-Hans.\n\n"
            "## Events and defaults\n\n" + "\n".join(rows) +
            f"\n\nQuiet hours may be broken only by `{', '.join(catalog.BREAKS_QUIET_HOURS)}`. Rate limits per person per hour: {json.dumps(catalog.RATE_LIMITS)} "
            "(beyond them email goes to the digest and push is suppressed, except for critical and security events). The daily digest goes out at "
            f"{catalog.DIGEST_HOUR}:00 local time, and the weekly digest on Monday.\n\n"
            "## Email previews (en and zh-Hant-HK shown; all 4 locales are in evidence/email/)\n\n" + "\n".join(previews) + "\n")
    (DOCS / "NOTIFICATION_CATALOG.md").write_text(text)
    return len(catalog.EVENTS), len(index["previews"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also run the whole Python unit suite")
    parser.add_argument("--web", action="store_true", help="also run the web node contract tests")
    args = parser.parse_args()
    gates = [registry_gate(), unit_gate(UNIT_MODULES, "coworker_unit_tests")]
    if args.full:
        full = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"], env={"PYTHONPATH": "src:tests", "POSTRIFF_RESEARCH": "0", "POSTRIFF_LOCAL_CLI": "0", "PYTHONDONTWRITEBYTECODE": "1"})
        counts = unittest_counts(full["tail"])
        gates.append({"gate": "python_unit_full", "status": "PASS" if full["exitCode"] == 0 and counts["ran"] else "FAIL", "counts": counts, "command": full["command"], "at": full["startedAt"]})
    gates.append(file_gate("postgres_coworker_scenarios", EVIDENCE / "pg-coworker.json",
                           "RAFII_COWORKER_EVIDENCE=docs/design/site-agent/adaptive-social-coworker/evidence/pg-coworker.json python scripts/postriff_pg_suite.py postgres_coworker"))
    gates.append(file_gate("email_render_accessibility", EVIDENCE / "email-render.json", "node scripts/rafii_email_render_check.cjs"))
    gates.append(browser_gate())
    gates.append(secret_gate())
    if args.web:
        gates.append(web_gate())
        gates.extend(web_static_gates())
    events, previews = notification_catalog_md()
    from postriff_phase2 import skill_registry
    report = {"schema": "rafii.coworker-verification.v1", "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
              "environment": {"python": platform.python_version(), "platform": platform.platform(), "research": os.environ.get("POSTRIFF_RESEARCH"),
                              "registryRelease": skill_registry.default_registry().release()},
              "live": {"verified": [], "note": "No live provider, email, push, model, image, payment, publishing, migration or deployment was exercised. Every result here is local or synthetic."},
              "catalog": {"events": events, "emailPreviews": previews}, "gates": gates,
              "summary": {s: sum(1 for g in gates if g["status"] == s) for s in ("PASS", "FAIL", "STALE", "NOT_RUN")}}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps(report["summary"]))
    for gate in gates:
        print(f"{gate['status']:8} {gate['gate']}")
    return 1 if report["summary"]["FAIL"] or report["summary"]["STALE"] else 0


if __name__ == "__main__":
    sys.exit(main())
