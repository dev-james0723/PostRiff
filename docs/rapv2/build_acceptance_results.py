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

# Features still not built after RAPv2 P1 shipped (consumer-saas 5e4f4e13), cited by BLOCKED rows.
LOCATION = "coarse location signal is not built (no IP-derived location is collected)"
RETENTION = "no retention worker for session-security records is built"
METHOD_DISPLAY = "the Security Center shows no sign-in method (no method field exists to display 'Unknown')"
DEVICE_LIST = "no device list / device revoke API or Security Center device view is built (P1 shipped the registry without one)"
RECOVERY = "no factor-recovery route is built"
RESOLUTION = "no incident resolution or hold release route is built (security_holds.release has no caller)"
INCIDENT_UI = "the web app has no 'This wasn't me' dialog (the API exists, the UI does not)"
P1 = "RAPv2 P1 as shipped (device registry 120, risk engine + step-up, holds 121, incidents 122); flags set in-test only"
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
auto("013", PG, P1 + ". Enforce mode, device_trust.observe made to fail: the export is refused, but with 403 security_step_up_required rather than 503.")
auto("014", PG, P1)
blocked("016", METHOD_DISPLAY, "/api/me exposes only the verified aal.")
# Session vs device classification
auto("017 018 019 020 021 022 023 025 026 027 028", PG, P1)
auto("024", PG, P1 + ". Native-surface headers and body fields leave the device at surface=web, state=observed.")
auto("029 030", UNIT, "browser_label: never 'Mozilla' alone; no or garbage agent -> 'Unrecognized browser' (the product's wording for unknown browser and OS).")
# Risk engine
auto("031 032 033 034 035 036 037 038 039 040 041 043 044 045 046 047 048", PG, P1 + ". Sensitive capability used: GET /api/workspaces/{id}/export (exports).")
auto("042", PG, P1 + ". No location is used at all: spoofed proxy/geo headers change no decision and are stored nowhere.")
# Session revocation
auto("049 050 051 052 055 059 060", PG)
auto("053", PG + " + " + BRANCH, "Disposable PG (authenticated role + JWT claims) and the real Supabase branch: a revoked session's JWT reads 0 workspaces; also " + GUARD + ".")
auto("054", PG + " + " + BRANCH, "A revoked JWT cannot read private storage.objects (which Storage reads and signs through). Residual risk: a signed URL issued before the revocation stays valid until its TTL expires.")
auto("056", UNIT, "The API reports refreshRevoked from the identity admin's real answer (false when refused or unconfigured). The Security Center does not display it.")
auto("057", UNIT, "Backend: the revoked session id stays denied even for a refreshed JWT (" + PG + " RAP-052). UI: a single revoke says its refresh token is not cancelled with the sign-in provider, and revoke-others reports refreshRevoked (" + UNIT + ").")
auto("058", PG + " + " + UNIT, "The UI offers no revoke for the current session (only the separate sign-out); the API, if called, denies the current session at once.")
auto("061", PG, P1)
auto("062 142", PG)
# Notifications
auto("063 065 066", PG)
auto("064", PG, P1 + ". Checked with the Notification V2 security detector after an incident report with routine alerts off.")
auto("067 146", PG, "V2 on: legacy Mailer routes new_device to V2 (routed_to_notifications_v2) and V2 sends one email across two crons; V2 off: legacy sends one.")
auto("068 069 070 071 078", PG)
auto("072 073 074 075 130 136", UNIT, "Legacy Mailer.new_device and Notification V2 security_alert renders.")
blocked("076", LOCATION, "Checked as supporting evidence (" + UNIT + "): neither email states any location, so none is invented; the 'Approximate location unavailable' wording does not exist.")
manual("077", HUMAN, "Requires a fluent reviewer for 'reviewed Cantonese'. Automated rendering of zh-Hant-HK with no placeholders is covered by tests/test_rafii_notifications.py::EmailTest.")
# Database / RLS / tenancy
auto("079 080 082", PG + " + " + BRANCH, "Disposable PostgreSQL: the five P0 session-security tables and the five P1 tables (pr_security_devices, pr_session_security, pr_security_login_events, pr_security_account_controls, pr_security_incidents). The Supabase branch run (2026-10-15 01:31Z) covered the P0 tables only.")
auto("081", PG, "service_role writes/reads on the P0 tables. The P1 tables' service_role grants (no ledger update/delete, holds only via pr_security_set_hold) are covered by tests/phase2/postgres_device_registry.py and postgres_account_holds.py.")
auto("083", PG, P1)
blocked("084", DEVICE_LIST, "The sessions list returns only the caller's sessions, ignoring any user parameter (RAP-091).")
auto("085", PG, P1 + ". GET of incidents only; there is no resolve route (" + RESOLUTION + ").")
auto("086", PG)
auto("087", PG + " + " + BRANCH, "P0 stores sign-in events in pr_audit_events (pr_security_login_events is not built): no role has UPDATE/DELETE, service_role UPDATE is refused.")
auto("088", PG, "Owner decision A+B (2026-10-15): deletion removes pr_sessions and redacts person-level session.* audit rows (subject and browser label erased, privacyErased) through migration 123's pr_erase_session_history; the append-only table keeps no UPDATE/DELETE grant.")
auto("089", PG, "pr_sessions primary key + RETURNING (xmax = 0): four concurrent inserts, one first sighting.")
auto("090", PG, P1)
auto("091", PG + " + " + BRANCH)
auto("092", PG + " + " + UNIT, "Migrations 120-123 apply in the disposable database and every P1 table/function exists with forced RLS (" + PG + "); rollback is documented in 120 and 121 only, and 123 still says it is not applied anywhere (expectedFailure in " + UNIT + ").")
# Agent and external permissions
auto("093 094 095 096 098 099 101 104", PG, P1 + ". Worker rows drive automation_runs.principal_repository, the fence every worker, phone schedule and Agent step opens its transactions through.")
auto("100", UNIT, "No connector can send email as the person (Gmail is read-only); account mail to the person is not an action as them.")
auto("103", UNIT, "Only the security modules, account deletion and session observation can write risk, trust or hold state; no Agent, tool or ideas code can.")
auto("097 102", PG, P1)
# Incident and recovery
auto("105", PG, "GET /api/me, /api/auth/sessions and /api/me/security-events never revoke or change factors. The Security Center page itself is a client page over these routes.")
auto("106 107 108 109 110 114 115 116", PG, P1 + ". POST/GET /api/auth/security/incidents with RAFII_SECURITY_INCIDENT_HOLD on.")
blocked("111", RECOVERY)
blocked("112 113", RESOLUTION)
# UI, localization, accessibility
manual("117 118 119 120 126 128", "real device / keyboard / VoiceOver review")
blocked("121", DEVICE_LIST)
auto("122", UNIT, "security_time renders EDT/EST with the zone name. The browser UI formats times with the device's Intl (not checked here).")
manual("123", HUMAN, "Terminology review needs a fluent reviewer; placeholder interpolation is covered by tests/test_rafii_notifications.py::EmailTest.")
auto("124", UNIT)
auto("125", UNIT)
blocked("127", INCIDENT_UI, "The API receipt does explain the effects (RAP-115).")
# Privacy, abuse and delivery hygiene
auto("129", UNIT, "One authenticated /api/me with every logger at DEBUG: no token, JWT payload, session id or user id in the output. Traces/telemetry exporters are not exercised.")
auto("131", UNIT, "Source and dependency scan of web/ for canvas/audio/WebGL fingerprinting and third-party trackers. The built bundle and live network are not inspected.")
auto("132", PG, P1 + ". The incident route is the only P1 route taking an id; there is no device route (" + DEVICE_LIST + ").")
auto("133", PG, "New-sign-in mail leaves the request in observe mode; the cron step (HostedWorkspaceService.deliver_sign_in_alerts) sends at most SIGN_IN_ALERT_CAP per person per hour and records the rest as suppressed. Also " + P0 + ".")
auto("134", PG, P1 + ". The incident report is the only P1 recovery-type mutation; Rafii uses bearer tokens plus the Origin/X-PostRiff-Request guard.")
auto("135 138", PG, P1)
blocked("137", RETENTION)
# Rollout, flags and resilience
auto("139 140 150", PG, "Also " + P0 + " (ModeFlag, off-mode tests).")
auto("141", PG, P1)
auto("143", PG, "The sign-in request only records session.observed with its alert decision; the /api/cron/worker step sends the mail on another thread/invocation. Also " + P0 + ".")
auto("144", PG, P1 + ". Connecting an account (oauth start) is the gated step before any connected publish.")
auto("145", UNIT)
auto("147", PG, "guard_target refuses every DSN but the disposable 127.0.0.1:55438/postgres cluster.")
manual("148", "release reviewer (G12)", "Evidence for the reviewer. 2026-10-15 first run: staging and production migration lists were read before and after and are unchanged; the only Supabase writes went to a dev branch deleted after 2 minutes. P1 re-run: no Supabase branch, migration, flag, env or production action; the only push is the tests/docs PR branch (it builds a Vercel preview); nothing merged, deployed or emailed.")
manual("149", "config review", "No RP ID change is planned; web/src/lib/auth/passkey-host.ts turns passkey sign-in off when NEXT_PUBLIC_PASSKEY_RP_ID does not match the host. Needs a human review of the deployment configuration plan.")

UNIT_EXPECTED_FAIL = {"RAP-092"}  # unittest.expectedFailure in UNIT


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
