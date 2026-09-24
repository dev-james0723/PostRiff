#!/usr/bin/env python3
"""Read-only social deployment checks. Reports presence/readiness, never secret values.

Run in the target server environment; this does not load .env files or contact a
social provider. Exit 0 means static configuration passed, not live OAuth success.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_phase2.oauth import CredentialVault, OAuthService
from postriff_phase2.providers import registry_from_environment


def inspect_environment(values):
    issues = []
    try:
        vault = CredentialVault(values.get('POSTRIFF_CREDENTIAL_KEY'))
    except (ValueError, TypeError):
        # Never render an exception carrying a malformed key.
        vault = CredentialVault(None)
        issues.append('POSTRIFF_CREDENTIAL_KEY is invalid; use a valid Fernet key in server secrets.')
    base = values.get('POSTRIFF_PUBLIC_BASE_URL', '').rstrip('/')
    web = values.get('NEXT_PUBLIC_APP_URL', '').rstrip('/')
    if not web or web != base:
        issues.append('NEXT_PUBLIC_APP_URL and POSTRIFF_PUBLIC_BASE_URL must match the fixed HTTPS app origin.')
    service = OAuthService(None, None, vault, registry_from_environment(values), base)
    providers = [item for item in service.provider_catalog() if item['id'] in ('instagram', 'linkedin')]
    return {'configured': not issues and all(item['connectReady'] for item in providers), 'issues': issues, 'providers': providers,
            'liveOAuthVerified': False, 'liveHistoryVerified': False,
            'note': 'Static configuration only. Provider app roles/approval, granted permissions, real callbacks, token refresh and AI budgets still need verification.'}


if __name__ == '__main__':
    report = inspect_environment(os.environ)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['configured'] else 1)
