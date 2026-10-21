"""Reproduce the legacy X OAuth constraint failure and validate its forward migration.

Provider responses are synthetic. Persistence and constraint enforcement use real,
disposable PostgreSQL. This never exchanges a token or calls a metered endpoint.
"""
import base64
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts"))
import psycopg
from postriff_alpha.domain import AlphaError
from postriff_migrate import body
from postriff_phase2.hosted import HostedWorkspaceService
from postriff_phase2.oauth import CredentialVault

ROOT = Path(__file__).resolve().parents[2]
ONE = "00000000-0000-0000-0000-000000000001"


def connection():
    return psycopg.connect("host=127.0.0.1 port=55438 dbname=postgres", client_encoding="utf8")


def verify(token):
    if token != "one":
        raise AlphaError("Verified session required.", 401)
    return ONE


class SyntheticIdentity:
    def __init__(self, platform, scopes):
        self.platform, self.scopes = platform, scopes

    def capability_scopes(self, capability):
        return self.scopes if capability == "identity" else []

    def explain(self, capability):
        return "Synthetic identity-only connection."

    def authorize_url(self, redirect, state, challenge, scopes):
        return "https://provider.example/authorize?" + urlencode({
            "redirect_uri": redirect, "state": state,
            "code_challenge": challenge, "scope": " ".join(scopes),
        })


vault = CredentialVault(CredentialVault.generate_key())
service = HostedWorkspaceService(connection, verify, vault=vault, providers={
    "linkedin": SyntheticIdentity("LinkedIn", ["openid", "profile"]),
    "x": SyntheticIdentity("X", ["users.read", "tweet.read", "offline.access"]),
}, public_base_url="https://app.postriff.example")
wid = service.bootstrap("one", "studio")["workspaceId"]

# Recreate the deployed 006 constraint, keeping an existing non-X transaction.
with connection() as db:
    db.execute("ALTER TABLE public.pr_oauth_transactions DROP CONSTRAINT pr_oauth_transactions_provider_check")
    db.execute("ALTER TABLE public.pr_oauth_transactions ADD CONSTRAINT pr_oauth_transactions_provider_check CHECK (length(provider) BETWEEN 2 AND 40)")
legacy = service.oauth.start(wid, "one", "linkedin", "identity")
try:
    service.oauth.start(wid, "one", "x", "identity")
except psycopg.errors.CheckViolation as error:
    assert error.diag.constraint_name == "pr_oauth_transactions_provider_check"
else:
    raise AssertionError("legacy schema unexpectedly accepted X")

# Execute the actual forward migration, not a corrected test-only schema.
with connection() as db:
    db.execute(body(ROOT / "migrations/postriff/101_x_oauth_provider.sql"), prepare=False)
    assert db.execute("SELECT provider FROM public.pr_oauth_transactions WHERE id=%s", (legacy["transactionId"],)).fetchone()[0] == "linkedin"
    assert db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='public.pr_oauth_transactions'::regclass").fetchone() == (True, True)

started = service.oauth.start(wid, "one", "x", "identity")
query = parse_qs(urlparse(started["authorizeUrl"]).query)
assert query["redirect_uri"] == ["https://app.postriff.example/api/oauth/x/callback"]
assert query["scope"] == ["users.read tweet.read offline.access"]
with connection() as db:
    row = db.execute("SELECT provider,capability,state_hash,verifier_ciphertext,scopes,key_id FROM public.pr_oauth_transactions WHERE id=%s", (started["transactionId"],)).fetchone()
assert row[0:2] == ("x", "identity")
assert row[2] == hashlib.sha256(query["state"][0].encode()).hexdigest()
verifier = vault.decrypt(row[3], row[5])
assert row[3] != verifier and len(verifier) >= 43
assert query["code_challenge"] == [base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")]
assert row[4] == ["users.read", "tweet.read", "offline.access"]

# The exception is exactly 'x'; empty, unrelated one-character and long IDs stay invalid.
for invalid in ("", "q", "x" * 41):
    try:
        with connection() as db:
            db.execute("UPDATE public.pr_oauth_transactions SET provider=%s WHERE id=%s", (invalid, started["transactionId"]))
    except psycopg.errors.CheckViolation as error:
        assert error.diag.constraint_name == "pr_oauth_transactions_provider_check"
    else:
        raise AssertionError(f"invalid provider ID accepted: {invalid!r}")

print(json.dumps({"status": "pass", "execution": "synthetic-provider-real-postgres", "checks": [
    "legacy X OAuth start reproduces the production constraint violation",
    "forward migration preserves the existing transaction and forced RLS",
    "X identity start persists hashed state and encrypted PKCE with exact scopes",
    "empty, unrelated one-character and oversized provider IDs remain rejected",
], "providerCalls": 0}))
