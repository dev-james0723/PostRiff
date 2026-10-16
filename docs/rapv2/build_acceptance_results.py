"""Build docs/rapv2/acceptance-results-2026-10-15.json from the RAPv2 matrix and executed evidence.

    python docs/rapv2/build_acceptance_results.py MATRIX.json PG_SUMMARY.json --sha SHA --ci-run URL \
        [--scene-summary SCENE_RESULTS.json --scene-run URL] [--out PATH]

MATRIX.json is tests/acceptance-matrix.json from the RAPv2 delivery packet (150 rows). PG_SUMMARY.json is the JSON the
tests/phase2/postgres_rapv2_acceptance.py suite prints in the CI log. A row is PASS only when an executed check passed in
a run that is named in `test_run_id`; a mismatch stays FAIL; rows that need unbuilt P1/P2 features are BLOCKED; rows that
need a person, a real device or a mailbox stay NOT_RUN. SCENE_RESULTS.json is the results.json that
web/tests/rapv2-security-center-browser.cjs writes in the "Rafii browser scenes" workflow (its own run, --scene-run).
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
SCENE = "web/tests/rapv2-security-center-browser.cjs"

# The nine rows BLOCKED after RAPv2 P1 shipped, built by claude/rapv2-blocked-features (flags set in-test only).
BUILT = "Built for the BLOCKED rows (claude/rapv2-blocked-features)"
DETAILS = "RAFII_SIGN_IN_DETAILS (off by default)"
SCENE_NOTE = "Playwright scene against the dev-harness web app with the account-security routes answered by fixed synthetic bodies"
P1 = "RAPv2 P1 as shipped (device registry 120, risk engine + step-up, holds 121, incidents 122); flags set in-test only"
GAPS = "Closed by the P1 gap fixes (claude/rapv2-close-p1-gaps)"
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
auto("013", PG, P1 + ". Enforce mode, device_trust.observe made to fail: the session has no security record, so the export answers 503 security_state_unavailable. " + GAPS + ".")
auto("014", PG, P1)
auto("016", PG + " + " + UNIT + " + " + SCENE, BUILT + ". /api/me `signIn` and each session's `signInMethod` come from the verified amr only (a recorded first sighting under " + DETAILS + " for other sessions); no amr reads 'unknown' with no second factor. The Security Center shows 'Unknown' (" + SCENE_NOTE + ").")
# Session vs device classification
auto("017 018 019 020 022 023 025 026 027 028", PG, P1)
auto("021", PG, P1 + ". A known browser is not proof: without a fresh factor a sensitive capability needs a low-risk AAL2 session (policy v2). " + GAPS + ".")
auto("024", PG, P1 + ". Native-surface headers and body fields leave the device at surface=web, state=observed.")
auto("029 030", UNIT, "browser_label: never 'Mozilla' alone; no or garbage agent -> 'Unrecognized browser' (the product's wording for unknown browser and OS).")
# Risk engine
auto("031 032 034 035 036 037 038 040 041 043 044 047 048", PG, P1 + ". Sensitive capability used: GET /api/workspaces/{id}/export (exports).")
auto("033", PG, P1 + ". Private workspace reads (GET /api/workspaces/{id}...) are a gated capability at high risk only, and fail open when the security state is unreadable. " + GAPS + ".")
auto("039", PG, P1 + ". The step-up gate checks the account hold before the policy: 403 security_account_hold even with fresh AAL2 proof on a known browser. " + GAPS + ".")
auto("045", PG, P1 + ". The identity service's verified factors decide the next step: enroll_mfa with none, complete_mfa with one or when it cannot say. " + GAPS + ".")
auto("046", PG, P1 + ". A proof made at or before the latest mfa.disabled is void (policy v2). " + GAPS + ".")
auto("042", PG, P1 + ". No location takes part in any decision: spoofed proxy/geo headers change none and are stored nowhere. (" + DETAILS + " may record Vercel's own edge geo headers for display only, never off Vercel; RAP-076.)")
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
auto("064", PG, P1 + ". Checked with the Notification V2 security detector after an incident report with routine alerts off: security.incident_reported is a transactional security.account_change notice. Risk decisions (step-up challenges) still queue no notice: that policy is not approved yet. " + GAPS + ".")
auto("067 146", PG, "V2 on: legacy Mailer routes new_device to V2 (routed_to_notifications_v2) and V2 sends one email across two crons; V2 off: legacy sends one.")
auto("068 069 070 071 078", PG)
auto("072 073 074 075 130 136", UNIT, "Legacy Mailer.new_device and Notification V2 security_alert renders.")
auto("076", PG + " + " + UNIT, BUILT + ". " + DETAILS + " at a location level records country/region/city only from Vercel's edge geo headers (x-vercel-ip-*, read only with VERCEL=1); none: the legacy and V2 notices say the approximate location is unavailable. No IP is stored; the location takes no part in any decision (RAP-042).")
manual("077", HUMAN, "Requires a fluent reviewer for 'reviewed Cantonese'. Automated rendering of zh-Hant-HK with no placeholders is covered by tests/test_rafii_notifications.py::EmailTest.")
# Database / RLS / tenancy
auto("079 080 082", PG + " + " + BRANCH, "Disposable PostgreSQL: the five P0 session-security tables and the five P1 tables (pr_security_devices, pr_session_security, pr_security_login_events, pr_security_account_controls, pr_security_incidents). The Supabase branch run (2026-10-15 01:31Z) covered the P0 tables only.")
auto("081", PG, "service_role writes/reads on the P0 tables. The P1 tables' service_role grants (no ledger update/delete, holds only via pr_security_set_hold) are covered by tests/phase2/postgres_device_registry.py and postgres_account_holds.py.")
auto("083", PG, P1)
auto("084", PG, BUILT + ". GET /api/auth/devices (RAFII_DEVICE_TRUST_V2; 404 while off) reads only the verified bearer's browsers, ignoring any user parameter or header; another person's browser cannot be revoked (404).")
auto("085", PG, P1 + ". GET of incidents; the resolve route added later (RAP-113) also answers only the caller's own incident.")
auto("086", PG)
auto("087", PG + " + " + BRANCH, "P0 stores sign-in events in pr_audit_events (pr_security_login_events is not built): no role has UPDATE/DELETE, service_role UPDATE is refused.")
auto("088", PG, "Owner decision A+B (2026-10-15): deletion removes pr_sessions and redacts person-level session.* audit rows (subject and browser label erased, privacyErased) through migration 123's pr_erase_session_history; the append-only table keeps no UPDATE/DELETE grant.")
auto("089", PG, "pr_sessions primary key + RETURNING (xmax = 0): four concurrent inserts, one first sighting.")
auto("090", PG, P1)
auto("091", PG + " + " + BRANCH)
auto("092", PG + " + " + UNIT, "Migrations 120-123 apply in the disposable database and every P1 table/function exists with forced RLS (" + PG + "); each header documents its rollback and 123 records that it is applied to staging and production (" + UNIT + "). " + GAPS + ".")
# Agent and external permissions
auto("093 094 095 096 098 099 101", PG, P1 + ". Worker rows drive automation_runs.principal_repository, the fence every worker, phone schedule and Agent step opens its transactions through.")
auto("104", PG, P1 + ". With RAFII_SECURITY_INCIDENT_HOLD off an active hold is still enforced (fail-open core check); only the epoch fences and the incident route turn off. " + GAPS + ".")
auto("100", UNIT, "No connector can send email as the person (Gmail is read-only); account mail to the person is not an action as them.")
auto("103", UNIT, "Only the security modules, account deletion and session observation can write risk, trust or hold state; no Agent, tool or ideas code can.")
auto("097 102", PG, P1)
# Incident and recovery
auto("105", PG, "GET /api/me, /api/auth/sessions and /api/me/security-events never revoke or change factors. The Security Center page itself is a client page over these routes.")
auto("106 107 108 109 110 115 116", PG, P1 + ". POST/GET /api/auth/security/incidents with RAFII_SECURITY_INCIDENT_HOLD on.")
auto("114", PG, P1 + ". The report queues a mandatory security notice to the account's verified email (Notification V2); notifying an older address after a recent email change is not built. " + GAPS + ".")
auto("111", PG, BUILT + ". GET/POST /api/auth/security/recovery (RAFII_SECURITY_INCIDENT_HOLD): with no factor from before the report the only path is support; an email code or a factor enrolled after the report is refused, MFA enforcement cannot be turned on during the hold, and a support request keeps the hold.")
auto("112", PG, BUILT + ". POST /api/auth/security/incidents/{id}/resolve: an old TOTP, a proof older than the report or an AAL1 email code answers 403 security_step_up_required and the hold stays.")
auto("113", PG, BUILT + ". Fresh TOTP (AAL2, after the report, factor enrolled before it): the hold is released once (hold_epoch 1 -> 2, one account.hold_released and one incident.resolved ledger event); a repeat and four concurrent resolves release nothing more.")
# UI, localization, accessibility
auto("117", SCENE, SCENE_NOTE + ". 375px CSS viewport: no horizontal overflow; every session and browser action is on screen and at least 32px tall. A real iPhone is not used.")
auto("118", SCENE, SCENE_NOTE + ". Keyboard only: visible focus on the trigger, Enter opens the dialog with focus inside, Escape cancels and returns focus; every visible action is named and tabbable.")
auto("119", SCENE, SCENE_NOTE + ". axe-core finds no serious or critical issue in the Security section; states are words. VoiceOver itself is not run (manual supplement).")
auto("120", SCENE, SCENE_NOTE + ". prefers-reduced-motion: reduce: the incident dialog is fully shown with every effect stated and no looping animation.")
auto("121", PG + " + " + SCENE, BUILT + ". Two sessions in one browser: the API reports 1 recognized browser and 2 active sessions; the Security Center shows '1 recognized browser · 2 sessions'. Revoking another browser ends its sessions; this browser cannot be revoked.")
auto("126", SCENE, SCENE_NOTE + ". 'Sign out others' with 2 active others and 1 revoked: the dialog says 2, with explicit 'Sign out others' and 'Keep them'.")
auto("128", SCENE, SCENE_NOTE + ". GET /api/auth/sessions answers 503: an announced error with Retry and a support pointer that says it cannot tell whether anything is wrong; nothing says the account is secure.")
auto("122", UNIT, "security_time renders EDT/EST with the zone name. The browser UI formats times with the device's Intl (not checked here).")
manual("123", HUMAN, "Terminology review needs a fluent reviewer; placeholder interpolation is covered by tests/test_rafii_notifications.py::EmailTest.")
auto("124", UNIT)
auto("125", UNIT)
auto("127", SCENE, SCENE_NOTE + ". The 'This wasn't me' dialog (added with P1) names the hold, what stops acting, renewed approvals, that published posts can't be undone and that connected accounts stay connected; cancelling sends nothing. The API receipt explains the same (RAP-115).")
# Privacy, abuse and delivery hygiene
auto("129", UNIT, "One authenticated /api/me with every logger at DEBUG: no token, JWT payload, session id or user id in the output. Traces/telemetry exporters are not exercised.")
auto("131", UNIT, "Source and dependency scan of web/ for canvas/audio/WebGL fingerprinting and third-party trackers. The built bundle and live network are not inspected.")
auto("132", PG, P1 + ". Routes taking an id (incidents; devices and incident resolution added later) answer another person's id with the same 404 (RAP-084, RAP-111..113).")
auto("133", PG, "New-sign-in mail leaves the request in observe mode; the cron step (HostedWorkspaceService.deliver_sign_in_alerts) sends at most SIGN_IN_ALERT_CAP per person per hour and records the rest as suppressed. Also " + P0 + ".")
auto("134", PG, P1 + ". The incident report is the only P1 recovery-type mutation; Rafii uses bearer tokens plus the Origin/X-PostRiff-Request guard.")
auto("135", PG, P1)
auto("138", PG, P1 + ". A browser unseen for 180 days is expired on its return (old record revoked, reason inactive) and registered as new. " + GAPS + ".")
auto("137", PG, BUILT + ". public.pr_security_retention_purge (migration 127) via security_retention.py (RAFII_SECURITY_RETENTION off|dry_run|on, RAFII_SECURITY_RETENTION_DAYS default 400, floor 90): the dry run deletes nothing; the real run removes only ledger events, session state and browsers past 400 days; incidents, cited events and every record of a person with an open incident are kept.")
# Rollout, flags and resilience
auto("139 140 150", PG, "Also " + P0 + " (ModeFlag, off-mode tests).")
auto("141", PG, P1)
auto("143", PG, "The sign-in request only records session.observed with its alert decision; the /api/cron/worker step sends the mail on another thread/invocation. Also " + P0 + ".")
auto("144", PG, P1 + ". Connecting an account (oauth start) is the gated step before any connected publish.")
auto("145", UNIT)
auto("147", PG, "guard_target refuses every DSN but the disposable 127.0.0.1:55438/postgres cluster.")
manual("148", "release reviewer (G12)", "Evidence for the reviewer. 2026-10-15 first run: staging and production migration lists were read before and after and are unchanged; the only Supabase writes went to a dev branch deleted after 2 minutes. P1 re-run: no Supabase branch, migration, flag, env or production action; the only push is the tests/docs PR branch (it builds a Vercel preview); nothing merged, deployed or emailed.")
manual("149", "config review", "No RP ID change is planned; web/src/lib/auth/passkey-host.ts turns passkey sign-in off when NEXT_PUBLIC_PASSKEY_RP_ID does not match the host. Needs a human review of the deployment configuration plan.")

UNIT_EXPECTED_FAIL = set()  # rows that are a unittest.expectedFailure in UNIT


def build(matrix, pg, sha, ci_run, branch_run, scene=None, scene_run=None):
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
            if SCENE in how:
                result = (scene or {}).get("rows", {}).get(case["id"])
                assert result, f"{case['id']} has no result in the browser scene summary"
                statuses.append(result["status"])
                details.append(f"{SCENE} ({(scene or {}).get('browser', 'chromium')}): " + "; ".join(c["name"] for c in result["checks"])
                               + ("" if result["status"] == "PASS" else " -> " + json.dumps([c for c in result["checks"] if not c["ok"]])[:300]))
            if BRANCH in how:
                details.append(f"Supabase branch run {branch_run}")
            status = "FAIL" if "FAIL" in statuses else "PASS"
            runs = ([ci_run] if PG in how or UNIT in how else []) + ([scene_run] if SCENE in how else []) + ([branch_run] if BRANCH in how else [])
            row.update(status=status, test_run_id=" ; ".join(runs), notes=" | ".join(details) + (f" | {note}" if note else ""))
        out.append(row)
    counts = {s: sum(1 for r in out if r["status"] == s) for s in ("PASS", "FAIL", "BLOCKED", "NOT_RUN")}
    by_priority = {p: {s: sum(1 for r in out if r["priority"] == p and r["status"] == s) for s in counts} for p in ("P0", "P1", "P2")}
    return {"schemaVersion": "rapv2-matrix-results-v1", "date": "2026-10-15", "sourceMatrix": {"schemaVersion": matrix["schemaVersion"], "date": matrix["date"], "count": matrix["count"]},
            "source_sha": sha, "ciRun": ci_run, "sceneRun": scene_run, "supabaseBranchRun": branch_run, "counts": counts, "countsByPriority": by_priority,
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
    parser.add_argument("--scene-summary")
    parser.add_argument("--scene-run")
    parser.add_argument("--out", default=str(Path(__file__).with_name("acceptance-results-2026-10-15.json")))
    args = parser.parse_args()
    scene = json.loads(Path(args.scene_summary).read_text()) if args.scene_summary else None
    result = build(json.loads(Path(args.matrix).read_text()), json.loads(Path(args.pg_summary).read_text()), args.sha, args.ci_run, args.branch_run, scene, args.scene_run)
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"counts": result["counts"], "byPriority": result["countsByPriority"], "classification": result["classificationCounts"]}))
