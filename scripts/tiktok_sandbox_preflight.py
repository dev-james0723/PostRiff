#!/usr/bin/env python3
"""Secret-free, read-only TikTok Sandbox OAuth readiness probe.

Never starts OAuth, exchanges tokens, stores secrets or contacts TikTok.
Use with an isolated Preview HTTPS callback registered in TikTok Sandbox.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.providers import registry_from_environment


def evaluate(values):
    sandbox_requested = str(values.get("POSTRIFF_TIKTOK_SANDBOX_ENABLED", "")).lower() == "true"
    errors = []
    if not sandbox_requested:
        errors.append("Enable POSTRIFF_TIKTOK_SANDBOX_ENABLED=true only in an isolated Preview.")
    try:
        vault = CredentialVault(values.get("POSTRIFF_CREDENTIAL_KEY"))
    except (ValueError, TypeError, ImportError):
        vault = CredentialVault()
        errors.append("POSTRIFF_CREDENTIAL_KEY is not a valid Fernet key.")
    registry = registry_from_environment(values)
    base = values.get("POSTRIFF_PUBLIC_BASE_URL")
    service = OAuthService(None, None, vault, registry, base)
    catalog = next(item for item in service.provider_catalog() if item["id"] == "tiktok")
    adapter = registry.get("tiktok")
    sandbox_mounted = bool(adapter and getattr(adapter, "sandbox_mode", False))
    callback = catalog.get("callbackUri")
    expected_scopes = ["user.info.basic"]
    errors.extend(catalog.get("setupIssues", []))
    if not sandbox_mounted and sandbox_requested and not errors:
        errors.append("TikTok Sandbox credentials could not be mounted.")
    # Never report production identity credentials as a ready Sandbox flow.
    ready = bool(sandbox_requested and sandbox_mounted and catalog["connectReady"] and
                 not getattr(adapter, "production_reviewed", False) and not errors)
    return {
        "kind": "tiktok_sandbox_oauth_preflight",
        "readyForHumanIdentityOAuth": ready,
        "configurationState": catalog["configurationState"],
        "sandboxCredentialsSelected": sandbox_mounted,
        "callbackUri": callback,
        "scopesToRequest": expected_scopes,
        "issues": errors,
        "liveOAuthVerified": False,
        "providerApprovalVerified": False,
        "postingAuthorized": False,
        "providerRequestsMade": 0,
    }


def main():
    report = evaluate(os.environ)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["readyForHumanIdentityOAuth"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
