#!/usr/bin/env python3
"""Secret-safe structural and environment preflight for hosted Phase 2."""
import argparse
import ast
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENV = (
    "POSTRIFF_DATABASE_URL",
    "POSTRIFF_SUPABASE_URL",
    "POSTRIFF_SUPABASE_PUBLISHABLE_KEY",
    "POSTRIFF_SUPABASE_SECRET_KEY",
    "CRON_SECRET",
)
PLACEHOLDERS = ("YOUR_", "GENERATE_", "PASSWORD", "HOST.pooler", "PROJECT_REF")


def _result(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def load_env_file(path):
    values = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def validate_structure(root=ROOT):
    checks = []
    required = [
        "api/index.py", "requirements.txt", ".python-version", ".env.example",
        ".gitignore", ".vercelignore", "vercel.json", "migrations/postriff/001_phase2.sql",
        "migrations/postriff/002_hosted_account_lifecycle.sql",
        "migrations/postriff/004_consumer_web_tenancy.sql",
        "migrations/postriff/005_consumer_web_ideas.sql",
        "migrations/postriff/006_consumer_web_channels.sql",
        "migrations/postriff/007_consumer_web_billing.sql",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    checks.append(_result("deployment-files", "pass" if not missing else "fail", "complete" if not missing else "missing: " + ", ".join(missing)))
    if missing:
        return checks

    config = json.loads((root / "vercel.json").read_text())
    services = config.get("services", {})
    routes = config.get("rewrites", [])
    api = services.get("postriff_api", {})
    web = services.get("postriff_web", {})
    valid_services = (
        api.get("runtime") == "python"
        and api.get("entrypoint") == "api.index:app"
        and web.get("root") == "studio/web/"
        and web.get("outputDirectory") == "dist-alpha"
        and len(routes) >= 2
        and routes[0].get("source") == "/api/(.*)"
        and routes[0].get("destination", {}).get("service") == "postriff_api"
    )
    checks.append(_result("vercel-services-routing", "pass" if valid_services else "fail", "API route precedes SPA route and preserves the original request path"))
    exclusions = api.get("functions", {}).get("api/index.py", {}).get("excludeFiles", "")
    private_exclusions = all(marker in exclusions for marker in (".env*", "broker.key", "*.command", "src/james_au_social/**", ".venv/**", ".phase3-build-venv/**", "desktop/**", "vendor/**"))
    checks.append(_result("function-bundle-boundary", "pass" if private_exclusions else "fail", "local credentials, launchers, private social modules, tests and evidence are excluded"))
    upload_rules = (root / ".vercelignore").read_text().splitlines()
    upload_boundary = all(rule in upload_rules for rule in (".env*", ".*-broker-*", ".upgrade-*", "broker.key", ".phase3-build-venv/", "desktop/", "vendor/", "src/james_au_social/", "studio/broker/", "studio/web/node_modules/", "docs/", "tests/")) and not any(rule.startswith("!") for rule in upload_rules)
    checks.append(_result("source-upload-boundary", "pass" if upload_boundary else "fail", "explicit blocklist excludes credentials, hidden broker state, caches, private modules, tests and evidence from source upload"))

    dependencies = set((root / "requirements.txt").read_text().splitlines())
    pinned = "Pillow==12.3.0" in dependencies and "psycopg[binary]==3.3.5" in dependencies
    checks.append(_result("python-runtime", "pass" if pinned and (root / ".python-version").read_text().strip() == "3.12" else "fail", "Python 3.12 with pinned Pillow and psycopg binary wheels"))

    ignored = (root / ".gitignore").read_text().splitlines()
    secret_safe = ".env.*" in ignored and "!.env.example" in ignored and ".vercel/" in ignored
    checks.append(_result("secret-exclusions", "pass" if secret_safe else "fail", "local environment files and Vercel link metadata are excluded"))

    for relative in ("api/index.py", "src/postriff_phase2/media.py", "src/postriff_phase2/hosted_app.py", "src/postriff_phase2/hosted_identity.py"):
        ast.parse((root / relative).read_text(), filename=relative)
    checks.append(_result("python-syntax", "pass", "hosted entrypoint and runtime modules parse"))

    samples = (root / ".env.example").read_text()
    leaked = re.search(r"(?:sb_secret_|sk-proj-)[A-Za-z0-9_-]{16,}", samples)
    checks.append(_result("environment-template", "fail" if leaked else "pass", "placeholder-only contract; no secret-shaped literal found"))
    crons = config.get("crons", [])
    exact_cron = crons == [{"path": "/api/cron/worker", "schedule": "* * * * *"}]
    checks.append(_result("production-cron-candidate", "pass" if exact_cron else "pending", "one-minute authenticated worker candidate" if exact_cron else "add the reviewed production cadence before promotion"))
    checks.append(_result("vercel-project-link", "pass" if (root / ".vercel/project.json").is_file() else "pending", "linked" if (root / ".vercel/project.json").is_file() else "no Vercel project selected"))
    return checks


def validate_environment(values):
    checks = []
    missing = [key for key in REQUIRED_ENV if not values.get(key) or any(marker in values.get(key, "") for marker in PLACEHOLDERS)]
    checks.append(_result("required-environment", "pass" if not missing else "pending", "all required names are populated" if not missing else "missing or placeholder: " + ", ".join(missing)))
    if missing:
        return checks

    database = urlparse(values["POSTRIFF_DATABASE_URL"])
    query = parse_qs(database.query)
    pooler = database.scheme in ("postgres", "postgresql") and bool(database.hostname) and database.hostname.endswith(".pooler.supabase.com") and database.port == 6543
    tls = query.get("sslmode", [""])[0] in ("require", "verify-full")
    checks.append(_result("database-connection", "pass" if pooler and tls else "fail", "Supabase transaction pooler on port 6543 with enforced TLS"))

    project = urlparse(values["POSTRIFF_SUPABASE_URL"])
    exact_project = project.scheme == "https" and bool(project.hostname) and project.hostname.endswith(".supabase.co") and project.path in ("", "/")
    checks.append(_result("supabase-project-url", "pass" if exact_project else "fail", "exact HTTPS project origin"))
    checks.append(_result("supabase-publishable-key", "pass" if len(values["POSTRIFF_SUPABASE_PUBLISHABLE_KEY"]) >= 20 else "fail", "present; value not printed"))
    checks.append(_result("supabase-secret-key", "pass" if len(values["POSTRIFF_SUPABASE_SECRET_KEY"]) >= 20 else "fail", "present; value not printed"))
    checks.append(_result("cron-secret", "pass" if len(values["CRON_SECRET"]) >= 32 else "fail", "at least 32 characters; value not printed"))
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, help="Optional local environment file; values are never printed")
    parser.add_argument("--require-environment", action="store_true", help="Fail when hosted values are absent")
    args = parser.parse_args(argv)
    values = dict(os.environ)
    if args.env_file:
        values.update(load_env_file(args.env_file))
    checks = validate_structure()
    environment = validate_environment(values)
    checks.extend(environment)
    failures = [item for item in checks if item["status"] == "fail"]
    pending = [item for item in checks if item["status"] == "pending"]
    status = "fail" if failures else "pending" if pending else "pass"
    print(json.dumps({"status": status, "execution": "local-preflight-only", "checks": checks}, indent=2))
    return 1 if failures or args.require_environment and pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
