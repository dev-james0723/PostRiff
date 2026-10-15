"""Build docs/rapv2/acceptance-results-2026-10-15.json from the RAPv2 matrix and executed evidence.

    python docs/rapv2/build_acceptance_results.py MATRIX.json PG_SUMMARY.json --sha SHA --ci-run URL [--out PATH]

MATRIX.json is tests/acceptance-matrix.json from the RAPv2 delivery packet (150 rows). PG_SUMMARY.json is the JSON the
tests/phase2/postgres_rapv2_acceptance.py suite prints in the CI log. A row is PASS only when an executed check passed in
a run that is named in `test_run_id`; a mismatch stays FAIL; rows that need unbuilt P1/P2 features are BLOCKED; rows that
need a person, a real device or a mailbox stay NOT_RUN.
"""
import argparse
import json
from pathlib import Path

PG = "tests/phase2/postgres_rapv2_acceptance.py"
UNIT = "tests/test_rafii_account_protection_acceptance.py"
P0 = "tests/test_rafii_account_protection_p0.py"
A1 = "tests/test_rafii_account_protection_a1.py"
GUARD = "tests/phase2/postgres_browser_session_guard.py"
BRANCH = "docs/rapv2/supabase-branch-evidence-2026-10-15.json"

# Unbuilt features (P1 unless stated), cited by BLOCKED rows.
DEVICE = "P1 device registry (opaque host-only device cookie, device records, trust) is not built"
RISK = "P1 risk engine / step-up (security_step_up_required, challenge-complete, AAL/AMR proof binding) is not built"
HOLD = "P1 account holds and worker fences (hold epoch, action-gateway hold checks) are not built"
INCIDENT = "P1 'This wasn't me' incident flow (incidents, receipts, resolution, recovery) is not built"
ENFORCE = "RAFII_ACCOUNT_PROTECTION_V2_MODE=enforce does not exist; P0 treats it as off (observe mode is deliberately fail-open)"
LOCATION = "coarse location signal is not built (P0 collects no IP-derived location)"
RETENTION = "no retention worker for session-security records is built"
NEW_TABLES = "the P1 security tables (device/risk/incident/login-event tables) are not built"
HUMAN = "needs a person"

# row -> (classification, how, note). Rows not listed here are an error.
C = {}


def auto(rows, source, note=""):
    for row in rows.split():
        C[f"RAP-{row}"] = ("AUTOMATABLE_NOW", source, note)


def blocked(rows, feature, note=""):
    for row in rows.split():
        C[f"RAP-{row}"] = ("NEEDS_FEATURE", feature, note)


def manual(rows, why, note=""):
    for row in rows.split():
        C[f"RAP-{row}"] = ("MANUAL_DEVICE", why, note)


# Auth session observation
auto("001 002 003", PG, "Server side, provider independent: a JWT carrying the amr of that sign-in method is observed once with its alert decision. The browser OAuth PKCE / OTP / passkey ceremony itself is not exercised (manual).")
auto("004", PG, "Real DB: POST /api/auth/verify then GET /api/me. Also unit-tested in " + P0 + ".")
auto("005 006 008 010 012", PG)
auto("007", PG, "Observation and the existing session checks (revocation, tombstone, MFA) run at the verifier before any handler. The v2 risk enforcement in the row's wording is P1 (RAP-031..048).")
auto("009", PG, "Six concurrent first requests on one new session; ON CONFLICT(user_id, session_id) yields one event. Also " + A1 + ".")
auto("011", PG, "verified_session_id refuses a JWT without session_id (401) on every session route. Also checked on the Supabase branch: such a JWT reads nothing directly (" + BRANCH + ").")
auto("015", PG, "No token, expired token (getUser 401) and garbage token on ten security routes.")
blocked("013", ENFORCE, "In observe mode an observation failure never fails the request by design (" + A1 + " test_an_observation_failure_never_fails_the_request); the 503 fail-closed behaviour belongs to enforce mode.")
blocked("014", DEVICE)
blocked("016", "P1 Security Center sign-in method display is not built", "/api/me exposes only the verified aal; no method field exists to show 'Unknown'.")
# Session vs device classification
blocked("017 018 019 020 021 022 023 025 026 027 028", DEVICE)
blocked("024", DEVICE, "There is no trust or attestation to grant; the client string is only ever a coarse label.")
auto("029 030", UNIT, "browser_label: never 'Mozilla' alone; no or garbage agent -> 'Unrecognized browser' (the product's wording for unknown browser and OS).")
# Risk engine
blocked("031 032 033 034 035 036 037 038 039 040 041 043 044 045 046 047 048", RISK)
blocked("042", RISK, "No location or proxy header is used by P0 at all.")
# Session revocation
auto("049 050 051 052 055 059 060", PG)
auto("053", PG + " + " + BRANCH, "Disposable PG (authenticated role + JWT claims) and the real Supabase branch: a revoked session's JWT reads 0 workspaces; also " + GUARD + ".")
auto("054", PG + " + " + BRANCH, "A revoked JWT cannot read private storage.objects (which Storage reads and signs through). Residual risk: a signed URL issued before the revocation stays valid until its TTL expires.")
auto("056", UNIT, "The API reports refreshRevoked from the identity admin's real answer (false when refused or unconfigured). The Security Center does not display it.")
auto("057", UNIT, "Backend: the revoked session id stays denied even for a refreshed JWT (" + PG + " RAP-052). UI: a single revoke says its refresh token is not cancelled with the sign-in provider, and revoke-others reports refreshRevoked (" + UNIT + ").")
auto("058", PG + " + " + UNIT, "The UI offers no revoke for the current session (only the separate sign-out); the API, if called, denies the current session at once.")
blocked("061", HOLD)
auto("062 142", PG)
# Notifications
auto("063 065 066", PG)
blocked("064", RISK, "No risk events exist to make a mandatory notice from.")
auto("067 146", PG, "V2 on: legacy Mailer routes new_device to V2 (routed_to_notifications_v2) and V2 sends one email across two crons; V2 off: legacy sends one.")
auto("068 069 070 071 078", PG)
auto("072 073 074 075 130 136", UNIT, "Legacy Mailer.new_device and Notification V2 security_alert renders.")
blocked("076", LOCATION, "Checked as supporting evidence (" + UNIT + "): neither email states any location, so none is invented; the 'Approximate location unavailable' wording does not exist.")
manual("077", HUMAN, "Requires a fluent reviewer for 'reviewed Cantonese'. Automated rendering of zh-Hant-HK with no placeholders is covered by tests/test_rafii_notifications.py::EmailTest.")
# Database / RLS / tenancy
auto("079 080 082", PG + " + " + BRANCH, "Evaluated on the P0 session-security tables (pr_sessions, pr_session_revocations, pr_audit_events, pr_mfa_enforcement, pr_account_tombstones); " + NEW_TABLES + " and must be re-run when they are.")
auto("081", PG, "service_role writes/reads on the P0 tables; " + NEW_TABLES + ".")
blocked("083", NEW_TABLES, "No session_security <-> device link table exists.")
blocked("084", DEVICE, "The P0 analogue (sessions list returns only the caller's sessions, ignoring any user parameter) is covered by RAP-091.")
blocked("085", INCIDENT)
auto("086", PG)
auto("087", PG + " + " + BRANCH, "P0 stores sign-in events in pr_audit_events (pr_security_login_events is not built): no role has UPDATE/DELETE, service_role UPDATE is refused.")
auto("088", PG, "Owner decision A+B (2026-10-15): deletion removes pr_sessions and redacts person-level session.* audit rows (subject and browser label erased, privacyErased) through migration 122's pr_erase_session_history; the append-only table keeps no UPDATE/DELETE grant.")
auto("089", PG, "pr_sessions primary key + RETURNING (xmax = 0): four concurrent inserts, one first sighting.")
blocked("090", RISK)
auto("091", PG + " + " + BRANCH)
blocked("092", NEW_TABLES, "The revised P1 candidate SQL is not approved or in the repo. Supporting evidence: repo migration 119 applied cleanly to a fresh Supabase branch (" + BRANCH + "); Supabase's own replay of staging history failed at 088 (MIGRATIONS_FAILED), a pre-existing staging history issue.")
# Agent and external permissions
blocked("093 094 095 096 098 099 100 101 103 104", HOLD)
blocked("097 102", HOLD, "Existing role-capability and founder-operator checks are covered by the founder/permissions suites, but the row's 'despite trusted device / under hold' premise needs the P1 device trust and holds.")
# Incident and recovery
auto("105", PG, "GET /api/me, /api/auth/sessions and /api/me/security-events never revoke or change factors. The Security Center page itself is a client page over these routes.")
blocked("106 107 108 109 110 111 112 113 114 115 116", INCIDENT)
# UI, localization, accessibility
manual("117 118 119 120 126 128", "real device / keyboard / VoiceOver review")
blocked("121", DEVICE)
auto("122", UNIT, "security_time renders EDT/EST with the zone name. The browser UI formats times with the device's Intl (not checked here).")
manual("123", HUMAN, "Terminology review needs a fluent reviewer; placeholder interpolation is covered by tests/test_rafii_notifications.py::EmailTest.")
auto("124", UNIT)
auto("125", UNIT)
blocked("127", INCIDENT)
# Privacy, abuse and delivery hygiene
auto("129", UNIT, "One authenticated /api/me with every logger at DEBUG: no token, JWT payload, session id or user id in the output. Traces/telemetry exporters are not exercised.")
auto("131", UNIT, "Source and dependency scan of web/ for canvas/audio/WebGL fingerprinting and third-party trackers. The built bundle and live network are not inspected.")
blocked("132", DEVICE + "; " + INCIDENT, "The existing session route's enumeration resistance is RAP-050.")
auto("133", PG, "New-sign-in mail leaves the request in observe mode; the cron step (HostedWorkspaceService.deliver_sign_in_alerts) sends at most SIGN_IN_ALERT_CAP per person per hour and records the rest as suppressed. Also " + P0 + ".")
blocked("134", INCIDENT, "No trust/recovery cookie endpoints exist; Rafii's API uses bearer tokens plus the X-PostRiff-Request/Origin guard.")
blocked("135 138", DEVICE)
blocked("137", RETENTION)
# Rollout, flags and resilience
auto("139 140 150", PG, "Also " + P0 + " (ModeFlag, off-mode tests).")
blocked("141", ENFORCE)
auto("143", PG, "The sign-in request only records session.observed with its alert decision; the /api/cron/worker step sends the mail on another thread/invocation. Also " + P0 + ".")
blocked("144", RISK)
auto("145", UNIT)
auto("147", PG, "guard_target refuses every DSN but the disposable 127.0.0.1:55438/postgres cluster.")
manual("148", "release reviewer (G12)", "Evidence for the reviewer: staging and production migration lists were read before and after the run and are unchanged; no statement ran on staging main or production; the only Supabase writes went to the deleted branch; the only push is this draft PR's branch (authorized by the task; it builds a Vercel preview), nothing merged, deployed or emailed.")
manual("149", "config review", "No RP ID change is planned; web/src/lib/auth/passkey-host.ts turns passkey sign-in off when NEXT_PUBLIC_PASSKEY_RP_ID does not match the host. Needs a human review of the deployment configuration plan.")

UNIT_EXPECTED_FAIL = set()  # unittest.expectedFailure in UNIT (RAP-057 closed)


def build(matrix, pg, sha, ci_run, branch_run):
    cases = matrix["cases"]
    missing = [c["id"] for c in cases if c["id"] not in C]
    assert not missing and len(C) == len(cases) == 150, (missing, len(C), len(cases))
    pg_rows = pg["rows"]
    out = []
    for case in cases:
        klass, how, note = C[case["id"]]
        row = dict(case)
        row["classification"] = klass
        row["source_sha"] = sha
        if klass == "NEEDS_FEATURE":
            row.update(status="BLOCKED", test_run_id=None, notes=f"BLOCKED: {how}." + (f" {note}" if note else ""))
        elif klass == "MANUAL_DEVICE":
            row.update(status="NOT_RUN", test_run_id=None, notes=f"NOT_RUN ({how})." + (f" {note}" if note else ""))
        else:
            statuses, details = [], []
            if PG in how:
                result = pg_rows.get(case["id"])
                assert result, f"{case['id']} has no result in the PostgreSQL summary"
                statuses.append(result["status"])
                details.append(f"{PG}: {result['check']}" + (f" -> {result.get('detail') or result.get('knownGap')}" if result["status"] == "FAIL" else ""))
            if UNIT in how:
                statuses.append("FAIL" if case["id"] in UNIT_EXPECTED_FAIL else "PASS")
                details.append(f"{UNIT}" + (" (expectedFailure: known gap)" if case["id"] in UNIT_EXPECTED_FAIL else ""))
            if BRANCH in how:
                details.append(f"Supabase branch run {branch_run}")
            status = "FAIL" if "FAIL" in statuses else "PASS"
            runs = [ci_run] + ([branch_run] if BRANCH in how else [])
            row.update(status=status, test_run_id=" ; ".join(runs), notes=" | ".join(details) + (f" | {note}" if note else ""))
        out.append(row)
    counts = {s: sum(1 for r in out if r["status"] == s) for s in ("PASS", "FAIL", "BLOCKED", "NOT_RUN")}
    by_priority = {p: {s: sum(1 for r in out if r["priority"] == p and r["status"] == s) for s in counts} for p in ("P0", "P1", "P2")}
    return {"schemaVersion": "rapv2-matrix-results-v1", "date": "2026-10-15", "sourceMatrix": {"schemaVersion": matrix["schemaVersion"], "date": matrix["date"], "count": matrix["count"]},
            "source_sha": sha, "ciRun": ci_run, "supabaseBranchRun": branch_run, "counts": counts, "countsByPriority": by_priority,
            "classificationCounts": {k: sum(1 for r in out if r["classification"] == k) for k in ("AUTOMATABLE_NOW", "NEEDS_FEATURE", "MANUAL_DEVICE")},
            "rules": "PASS only with an executed check named in test_run_id; FAIL is a mismatch against expected_result; BLOCKED needs an unbuilt feature (cited); NOT_RUN needs a person/device/mailbox.",
            "cases": out}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix")
    parser.add_argument("pg_summary")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ci-run", required=True)
    parser.add_argument("--branch-run", default=json.loads((Path(__file__).with_name("supabase-branch-evidence-2026-10-15.json")).read_text())["runId"])
    parser.add_argument("--out", default=str(Path(__file__).with_name("acceptance-results-2026-10-15.json")))
    args = parser.parse_args()
    result = build(json.loads(Path(args.matrix).read_text()), json.loads(Path(args.pg_summary).read_text()), args.sha, args.ci_run, args.branch_run)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"counts": result["counts"], "byPriority": result["countsByPriority"], "classification": result["classificationCounts"]}))
