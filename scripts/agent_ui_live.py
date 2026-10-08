"""Budget-capped LIVE acceptance runner for Rafii Generative UI (rafii-genui/1; 04-ACCEPTANCE sample plan; D-A31).

Two ways to measure a deployed origin, neither of which ever puts a credential on disk:

* BROWSER mode (production sign-in is a passkey in a real browser). The release owner drives the real UI; this script only
  prints what to run and turns the results into evidence:
      plan             the fixed sample plan (30 normal generations = 3 prompts × J01–J09 + 3 composite; 9 edits; fault cases)
      browser-snippet  JavaScript to evaluate in the signed-in page: installs window.__rafiiLive, which tags each case, observes
                       lane C's performance marks 'rafii-genui:first-component' / 'rafii-genui:ready' (detail {artifactId,
                       revision}) and the resource timing of the turn and presentation requests, runs the G04 probe in-page
                       (the page's own session, never returned), counts UI requests while hidden (G18) and during a filter
                       change (G05), and returns timings only
      server-sql       the read-only SQL the release owner runs against the production DB: attempt timings
                       (admitted_at / first_delta_at / ready_at), provider attempts, usage and cost from the server's own
                       records, validation outcome and hashes — no source, no message text
      ingest           merge the browser collection and the server rows into evidence/g/live-<sha>-<timestamp>.json with the
                       G03 / G04 / G05 / G17 / G18 verdicts (unverified, with the exact missing cases, when the sample is short)
* API mode (optional, when a session bearer is available): `run` / `stream` call the deployed API directly with a bearer read
  ONLY from the environment variable RAFII_LIVE_SESSION_TOKEN at run time (never an argument, file or log).
* `concurrency` (1 / 5 / 20 sessions) runs against the loopback acceptance harness only (fixture provider; never production).

Every live command refuses without RAFII_LIVE_CHECKS=1, an explicit --origin (no default; https, or loopback http for the
harness), --workspace and --budget-usd. Spend is capped: before each generation the runner adds a conservative per-case
estimate; unknown provider cost counts as the estimate, never zero; reaching the cap stops the run and the missing cases stay
unverified. Evidence passes tests/agent_ui_acceptance/redaction.py before it is written (the repository is public).

    python scripts/agent_ui_live.py plan
    python scripts/agent_ui_live.py browser-snippet > /tmp/snippet.js
    python scripts/agent_ui_live.py server-sql --workspace <uuid> --since 2026-10-09T00:00:00Z
    RAFII_LIVE_CHECKS=1 python scripts/agent_ui_live.py ingest --origin https://rafii.io --workspace <uuid> --budget-usd 5 \
        --browser-results results.json --server-rows attempts.json [--sha <deployed sha>]
    RAFII_LIVE_CHECKS=1 RAFII_LIVE_SESSION_TOKEN=… python scripts/agent_ui_live.py run --origin https://rafii.io --workspace <uuid> --budget-usd 5
    RAFII_LIVE_CHECKS=1 python scripts/agent_ui_live.py concurrency --origin http://127.0.0.1:4538 --workspace <uuid> --budget-usd 0.01 --levels 1,5,20
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from agent_ui_acceptance import redaction  # noqa: E402
from agent_ui_acceptance.client import Api  # noqa: E402

EVIDENCE_DIR = ROOT / "docs/design/openui-production-2026-10-08/evidence/g"
TOKEN_ENV = "RAFII_LIVE_SESSION_TOKEN"
MAX_BUDGET_USD = 25.0
DEFAULT_CASE_ESTIMATE_USD = 0.06       # one Manager turn + one presentation (+ at most one repair), conservative
FIRST_COMPONENT_P95_MS = 8000
FULL_UI_P95_MS = 30000

JOURNEY_PROMPTS = {
    "J01": ("Compare my latest LinkedIn and Threads drafts side by side", "Show my unscheduled drafts in a table with platform and language",
            "Which of my drafts still need review? Lay them out so I can filter by platform"),
    "J02": ("Show my publishing calendar for next week as an agenda", "What's in the publishing queue, and do any time slots collide?",
            "Lay out next month's scheduled posts week by week"),
    "J03": ("Browse my Library for piano practice photos I could use", "Show my Library items about the recital with previews",
            "Find the Library videos I added last month and compare their details"),
    "J04": ("Show which sources Rafii can learn my writing voice from", "What has Rafii learned about my voice so far, with the evidence?",
            "Compare proposed and learned voice traits in a table"),
    "J05": ("Show the plan for my current campaign as a table", "What's still missing in my campaign? Show progress by step",
            "Lay out my campaign timeline with its dependencies"),
    "J06": ("Chart my post views over the last 30 days by platform", "Compare engagement for my last 10 posts in a table",
            "Show which of my metrics are unknown or missing, and why"),
    "J07": ("Show the research brief for my next post with its citations", "Compare the sources behind my recital post by date",
            "List the research I saved, with each source's date"),
    "J08": ("Show my automations with their next run and time zone", "What happened in my last automation runs?",
            "Which connections need attention before my automations can run?"),
    "J09": ("Show this week's revenue and cost summary", "Show reliability by surface for the last 24 hours", "Show the support queue grouped by status"),
}
COMPOSITE_PROMPTS = ("Pick two Library photos for my recital post, draft a LinkedIn post in my voice, and propose it for Thursday 18:00",
                     "Use the selected Library video to draft a Threads post in my voice and add it to my campaign plan",
                     "From my Library recital photos, draft an Instagram caption in my voice and show where it fits in next week's calendar")
EDIT_CASES = {"J01": "Compare only the two selected drafts", "J02": "Change the period to next month", "J03": "Show only videos",
              "J04": "Add a column with the evidence for each trait", "J05": "Add a chart of progress by step", "J06": "Change the period to the last 7 days",
              "J07": "Sort the sources by date, newest first", "J08": "Show only paused automations", "J09": "Add last week for comparison"}


def sample_plan() -> dict:
    normal = [{"caseId": f"{j}-{chr(97 + i)}", "journey": j, "kind": "generate", "surface": "founder" if j == "J09" else "chat", "prompt": p}
              for j, prompts in JOURNEY_PROMPTS.items() for i, p in enumerate(prompts)]
    normal += [{"caseId": f"CMP-{chr(97 + i)}", "journey": "composite", "kind": "generate", "surface": "chat", "prompt": p} for i, p in enumerate(COMPOSITE_PROMPTS)]
    edits = [{"caseId": f"{j}-edit", "journey": j, "kind": "edit", "baseCase": f"{j}-a", "surface": "founder" if j == "J09" else "chat", "instruction": text}
             for j, text in EDIT_CASES.items()]
    faults = [{"caseId": "F-cancel", "kind": "fault", "fault": "user cancel mid-stream", "expect": "ui.canceled; native answer kept; settled once"},
              {"caseId": "F-disconnect", "kind": "fault", "fault": "close the tab mid-stream", "expect": "interrupted; settled once; reopen shows last valid revision"},
              {"caseId": "F-retry", "kind": "fault", "fault": "explicit Try again after a failure", "expect": "cost/consent shown first; a new attempt, never automatic"}]
    return {"contractVersion": "rafii-genui/1", "normal": normal, "edits": edits, "faults": faults,
            "denominators": {"G03": {"firstPassValidAtLeast": 29, "of": len(normal), "functionalAfterOneRepair": len(normal)}},
            "targets": {"G17": {"firstUsefulComponentP95Ms": FIRST_COMPONENT_P95_MS, "fullUiP95Ms": FULL_UI_P95_MS, "localInteractionP95Ms": 200}},
            "note": "Engineering acceptance sample, not a statistical guarantee. Fault-injected malformed/truncated output is the CI harness's job."}


# --- guards --------------------------------------------------------------------------------------------------------------------
class Refused(SystemExit):
    def __init__(self, reason):
        print(json.dumps({"status": "REFUSED", "reason": reason}), file=sys.stderr)
        super().__init__(64)


TOKENISH = re.compile(r"(?i)(bearer\s|eyJ[A-Za-z0-9_-]{8,}\.|\bsk-[A-Za-z0-9_-]{8,}|prt_[A-Za-z0-9_-]{8,}|dev:[0-9a-f-]{36}|access_token=)")


def guard_argv(argv) -> None:
    for item in argv:
        if TOKENISH.search(str(item)):
            raise Refused("a credential-looking value was passed on the command line; the session bearer is read only from the environment")


def guard_live(args, *, needs_token: bool) -> str | None:
    if os.environ.get("RAFII_LIVE_CHECKS") != "1":
        raise Refused("live checks are opt-in: set RAFII_LIVE_CHECKS=1")
    origin = getattr(args, "origin", None)
    if not origin:
        raise Refused("--origin is required (no default; e.g. https://rafii.io or the verified production alias)")
    parts = urlsplit(origin)
    loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise Refused("--origin must be https (http is accepted only for the loopback acceptance harness)")
    if parts.path not in ("", "/") or parts.query or parts.username or parts.password:
        raise Refused("--origin is an origin only (scheme://host[:port]) and never carries credentials")
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(getattr(args, "workspace", "") or "")):
        raise Refused("--workspace <uuid> of the allowlisted test workspace is required")
    budget = getattr(args, "budget_usd", None)
    if budget is None or not (0 < budget <= MAX_BUDGET_USD):
        raise Refused(f"--budget-usd is required and must be > 0 and <= {MAX_BUDGET_USD}")
    if needs_token:
        token = os.environ.get(TOKEN_ENV)
        if not token or len(token) < 21:
            raise Refused(f"API mode needs a session bearer in the environment variable {TOKEN_ENV} (or use browser mode: plan / browser-snippet / ingest)")
        return token
    return None


def scope_hash(workspace: str) -> str:
    return "ws:" + hashlib.sha256(workspace.encode()).hexdigest()[:12]


def head_sha() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def p95(values):
    data = sorted(v for v in values if isinstance(v, (int, float)))
    if not data:
        return None
    return data[max(0, math.ceil(0.95 * len(data)) - 1)]


class Budget:
    def __init__(self, cap_usd: float, estimate_usd: float):
        self.cap, self.estimate, self.spent, self.unknown = cap_usd, estimate_usd, 0.0, 0
        self.lock = threading.Lock()

    def admit(self) -> bool:
        with self.lock:
            return self.spent + self.estimate <= self.cap + 1e-9

    def charge(self, usd_micro):
        with self.lock:
            if usd_micro is None:
                self.unknown += 1
                self.spent += self.estimate          # unknown is never zero
            else:
                self.spent += usd_micro / 1_000_000

    def report(self):
        return {"capUsd": self.cap, "perCaseEstimateUsd": self.estimate, "spentUsd": round(self.spent, 6), "unknownCostCases": self.unknown,
                "costSource": "server-reported usage (unknown counted at the per-case estimate)"}


def write_evidence(payload: dict, out: Path | None, sha: str) -> Path:
    redaction.assert_clean(payload)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out or EVIDENCE_DIR / f"live-{sha[:12]}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    return path


# --- browser mode ----------------------------------------------------------------------------------------------------------------
BROWSER_SNIPPET = r"""
(() => {
  // Rafii live acceptance collector (lane G). Timings and counts only: no tokens, no message text, no DSL leave the page.
  if (window.__rafiiLive) return 'already installed';
  const MARKS = ['rafii-genui:first-component', 'rafii-genui:ready'];
  const UI = /\/agent\/ui\/(presentations|queries|actions|messages|diagnostics)/;
  const state = { caseId: null, cases: {}, marks: [], resources: [], installedAt: performance.now(), timeOrigin: performance.timeOrigin, hidden: [] };
  const tag = () => state.caseId;
  new PerformanceObserver((list) => {
    for (const m of list.getEntries()) if (MARKS.includes(m.name)) state.marks.push({ caseId: tag(), name: m.name, at: m.startTime, artifactId: m.detail?.artifactId ?? null, revision: m.detail?.revision ?? null });
  }).observe({ type: 'mark', buffered: true });
  new PerformanceObserver((list) => {
    for (const r of list.getEntries()) {
      const path = new URL(r.name, location.href).pathname;
      if (!/\/agent\/(turns|ui\/)/.test(path)) continue;
      state.resources.push({ caseId: tag(), route: path.replace(/[0-9a-f-]{36}/g, ':id'), start: r.startTime, responseStart: r.responseStart, end: r.responseEnd, hidden: document.visibilityState === 'hidden' });
    }
  }).observe({ type: 'resource', buffered: false });
  document.addEventListener('visibilitychange', () => state.hidden.push({ at: performance.now(), state: document.visibilityState }));
  const session = () => {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (/^sb-.*-auth-token$/.test(key)) { try { return JSON.parse(localStorage.getItem(key)).access_token || null; } catch { return null; } }
    }
    return null;
  };
  window.__rafiiLive = {
    begin(caseId) { state.caseId = String(caseId).slice(0, 40); state.cases[state.caseId] = { begunAt: performance.now() }; return state.caseId; },
    end() { if (state.caseId) state.cases[state.caseId].endedAt = performance.now(); const id = state.caseId; state.caseId = null; return id; },
    collect() { return JSON.parse(JSON.stringify({ v: 1, origin: location.origin, userAgent: navigator.userAgent, ...state })); },
    async probe(workspaceId) {
      // G04 in the signed-in page: the session stays inside the browser; only arrival times and decode results are returned.
      const token = session();
      if (!token) return { ok: false, reason: 'no Supabase session in this page (sign in first)' };
      const started = performance.now();
      const res = await fetch(`/api/workspaces/${workspaceId}/agent/ui/diagnostics/stream`, { headers: { Authorization: `Bearer ${token}`, 'X-PostRiff-Request': 'founder-alpha', Accept: 'text/event-stream' } });
      const out = { ok: res.ok, status: res.status, contentType: res.headers.get('content-type'), chunks: [], frames: [], splitInsideCharacter: false };
      if (!res.ok || !res.body) return out;
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8', { fatal: true });
      let buffer = '';
      let decodeError = false;
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        const at = performance.now() - started;
        if (value.length && (value[0] & 0xc0) === 0x80) out.splitInsideCharacter = true;
        out.chunks.push({ at, bytes: value.length });
        try { buffer += decoder.decode(value, { stream: true }); } catch { decodeError = true; }
        let cut;
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const frame = buffer.slice(0, cut); buffer = buffer.slice(cut + 2);
          const event = (frame.match(/^event: (.*)$/m) || [])[1] || 'message';
          const data = (frame.match(/^data: (.*)$/m) || [])[1] || '';
          let multibyte = false; try { multibyte = [...JSON.stringify(JSON.parse(data))].some((c) => c.codePointAt(0) > 0x7ff); } catch {}
          out.frames.push({ at, event, multibyte });
        }
      }
      out.endedAt = performance.now() - started;
      out.decodeError = decodeError;
      return out;
    },
    count(routePattern, ms) {
      // G05/G18: UI requests matching a route pattern within the next `ms` milliseconds (filter change, or while hidden).
      const from = performance.now();
      return new Promise((resolve) => setTimeout(() => {
        const re = new RegExp(routePattern);
        const hits = state.resources.filter((r) => r.start >= from && re.test(r.route));
        resolve({ from, ms, count: hits.length, hiddenCount: hits.filter((h) => h.hidden).length, routes: hits.map((h) => h.route) });
      }, ms));
    },
  };
  return 'installed';
})();
""".strip()

SERVER_SQL = """-- Rafii live acceptance export (lane G). Read-only; returns timings, attempts, usage, cost and hashes, never source or text.
-- Run against the production DB for the allowlisted test workspace and save the JSON result as attempts.json.
select coalesce(json_agg(row_to_json(x) order by x.admitted_at), '[]'::json) from (
  select t.artifact_id, t.id as attempt_id, t.kind, t.target_revision, t.state, t.reason, t.provider_attempts, t.cost_state, t.cost_usd_micro,
         t.usage->>'model' as model, (t.usage->>'inputTokens')::int as input_tokens, (t.usage->>'outputTokens')::int as output_tokens,
         t.admitted_at, t.first_delta_at, t.ready_at, t.finished_at, t.retry_of,
         a.parent_run_id, a.surface, a.journey_ids, a.scope, a.library_version, a.library_hash, a.prompt_hash,
         r.source_hash, (r.validation->>'accepted')::boolean as accepted, (r.validation->>'statementCount')::int as statement_count,
         r.validation->'componentNames' as component_names, r.validation->'queryNames' as query_names, r.validation->'actionIds' as action_ids,
         (select sum(coalesce(l.actual_usd_micro, l.estimated_usd_micro)) from public.pr_usage_ledger l
            where l.workspace_id = t.workspace_id and l.run_id = a.parent_run_id and l.kind = 'settle'
              and l.idempotency_key not like 'agent:%:ui:%') as turn_cost_usd_micro
  from public.pr_ui_attempts t
  join public.pr_ui_artifacts a on a.id = t.artifact_id
  left join public.pr_ui_revisions r on r.artifact_id = t.artifact_id and r.attempt_id = t.id
  where t.workspace_id = '{workspace}'::uuid and t.admitted_at >= '{since}'::timestamptz
) x;"""


def _ms(a, b):
    if not a or not b:
        return None
    da, db = (datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in (a, b))
    return round((db - da).total_seconds() * 1000, 1)


def ingest(browser: dict, rows: list, plan: dict) -> dict:
    """Join browser marks (by artifactId) with server attempt rows; compute the G03/G04/G05/G17/G18 verdicts."""
    by_artifact: dict = {}
    for row in rows:
        by_artifact.setdefault(str(row.get("artifact_id")), []).append(row)
    marks = browser.get("marks") or []
    resources = browser.get("resources") or []
    cases = []
    plan_cases = {c["caseId"]: c for c in plan["normal"] + plan["edits"]}
    for case_id, meta in sorted((browser.get("cases") or {}).items()):
        mine = [m for m in marks if m.get("caseId") == case_id]
        first = next((m for m in mine if m["name"] == "rafii-genui:first-component"), None)
        ready = next((m for m in mine if m["name"] == "rafii-genui:ready"), None)
        artifact = (ready or first or {}).get("artifactId")
        res = [r for r in resources if r.get("caseId") == case_id]
        turn = next((r for r in res if r["route"].endswith("/agent/turns")), None)
        present = next((r for r in res if re.search(r"/agent/ui/presentations(/:id/edits)?$", r["route"])), None)
        attempts = sorted(by_artifact.get(str(artifact), []), key=lambda r: str(r.get("admitted_at")))
        planned = plan_cases.get(case_id, {})
        kind = planned.get("kind") or ("edit" if case_id.endswith("-edit") else "generate")
        relevant = [a for a in attempts if (a.get("kind") in ("edit",) if kind == "edit" else a.get("kind") in ("generate", "repair"))]
        initial = next((a for a in relevant if a.get("kind") in ("generate", "edit")), None)
        repair = next((a for a in relevant if a.get("kind") == "repair"), None)
        final = repair or initial or {}
        cost = sum(int(a["cost_usd_micro"]) for a in relevant if a.get("cost_usd_micro") is not None)
        cases.append({
            "caseId": case_id, "journey": planned.get("journey"), "kind": kind, "artifactId": artifact, "revision": (ready or {}).get("revision"),
            "firstPassValid": bool(initial and initial.get("state") == "ready" and initial.get("accepted") is not False),
            "repaired": bool(repair), "functional": final.get("state") == "ready", "reason": final.get("reason"),
            "providerAttempts": sum(int(a.get("provider_attempts") or 0) for a in relevant), "sourceHash": final.get("source_hash"),
            "statementCount": final.get("statement_count"), "componentNames": final.get("component_names"), "queryNames": final.get("query_names"),
            "actionIds": final.get("action_ids"), "costUsdMicro": cost if relevant else None,
            "costState": sorted({a.get("cost_state") for a in relevant if a.get("cost_state")}),
            "server": {"admissionToFirstDeltaMs": _ms((initial or {}).get("admitted_at"), (initial or {}).get("first_delta_at")),
                       "admissionToReadyMs": _ms((initial or {}).get("admitted_at"), final.get("ready_at"))},
            "client": {"presentationStartToFirstComponentMs": round(first["at"] - present["start"], 1) if first and present else None,
                       "presentationStartToReadyMs": round(ready["at"] - present["start"], 1) if ready and present else None,
                       "turnStartToReadyMs": round(ready["at"] - turn["start"], 1) if ready and turn else None,
                       "rendered": bool(ready)},
            "usable": bool(ready) and final.get("state") == "ready",
        })
    normal = [c for c in cases if c["kind"] == "generate"]
    edits = [c for c in cases if c["kind"] == "edit"]
    missing_normal = sorted(set(c["caseId"] for c in plan["normal"]) - {c["caseId"] for c in normal})
    missing_edits = sorted(set(c["caseId"] for c in plan["edits"]) - {c["caseId"] for c in edits})
    first_pass = sum(1 for c in normal if c["firstPassValid"])
    functional = sum(1 for c in normal if c["functional"])
    warm = normal[1:] if len(normal) > 1 else []
    g03 = ("unverified" if missing_normal else "pass" if first_pass >= 29 and functional == len(plan["normal"]) else "fail")
    fc = p95([c["client"]["presentationStartToFirstComponentMs"] for c in warm])
    full = p95([c["client"]["presentationStartToReadyMs"] for c in warm])
    g17 = "unverified" if missing_normal or fc is None or full is None else ("pass" if fc <= FIRST_COMPONENT_P95_MS and full <= FULL_UI_P95_MS else "fail")
    probe = browser.get("probe") or {}
    frames = [f for f in probe.get("frames") or [] if f.get("event") != "ui.heartbeat"]
    g04 = "unverified"
    if probe:
        spaced = len(frames) >= 3 and frames[2]["at"] - frames[0]["at"] >= 1000 and frames[2]["at"] < (probe.get("endedAt") or 0)
        g04 = "pass" if probe.get("ok") and spaced and not probe.get("decodeError") and any(f.get("multibyte") for f in frames) else "fail"
    filt = browser.get("filterCheck") or {}
    hidden = browser.get("hiddenCheck") or {}
    return {
        "cases": cases,
        "verdicts": {
            "G03": {"status": g03, "firstPassValid": first_pass, "functional": functional, "normalCases": len(normal), "required": len(plan["normal"]),
                    "missingCases": missing_normal},
            "G10-live": {"status": "unverified" if missing_edits else ("pass" if all(c["functional"] for c in edits) else "fail"), "edits": len(edits),
                         "missingCases": missing_edits},
            "G17": {"status": g17, "firstUsefulComponentP95Ms": fc, "fullUiP95Ms": full, "coldCase": normal[0]["caseId"] if normal else None,
                    "coldFirstComponentMs": normal[0]["client"]["presentationStartToFirstComponentMs"] if normal else None,
                    "timeOrigins": {"client": "performance.timeOrigin of the signed-in page; t0 = startTime of the POST …/agent/ui/presentations request",
                                    "server": "pr_ui_attempts.admitted_at (presentation admission) → first_delta_at / ready_at",
                                    "endToEnd": "startTime of POST …/agent/turns → 'rafii-genui:ready' (reported separately, never as presenter time)"},
                    "targets": {"firstUsefulComponentP95Ms": FIRST_COMPONENT_P95_MS, "fullUiP95Ms": FULL_UI_P95_MS}},
            "G04": {"status": g04, "frames": len(frames), "splitInsideCharacterObserved": probe.get("splitInsideCharacter"),
                    "spanMs": round(frames[-1]["at"] - frames[0]["at"], 1) if len(frames) >= 2 else None},
            "G05": {"status": "unverified" if not filt else ("pass" if filt.get("modelAttemptDelta") == 0 and filt.get("queryRequests", 0) >= 1 else "fail"), **filt},
            "G18": {"status": "unverified" if not hidden else ("pass" if hidden.get("hiddenCount") == 0 else "fail"), **hidden},
        },
    }


# --- API mode ------------------------------------------------------------------------------------------------------------------
def api_case(api: Api, token: str, workspace: str, case: dict, budget: Budget) -> dict:
    from agent_ui_acceptance.client import new_key
    if not budget.admit():
        return {"caseId": case["caseId"], "status": "unverified", "reason": "budget cap reached before this case"}
    t0 = time.monotonic()
    turn = api.request("POST", f"/api/workspaces/{workspace}/agent/turns", token, {"message": case["prompt"], "idempotencyKey": new_key("live"),
                                                                                    "modality": "text"}, timeout=180)
    t_turn = time.monotonic()
    result = turn.json() or {}
    turn_cost = ((result.get("usage") or {}).get("costUsdMicro"))
    if turn.status not in (200, 201) or not (result.get("ui") or {}).get("eligible"):
        budget.charge(turn_cost)
        return {"caseId": case["caseId"], "status": "fail" if turn.status not in (200, 201) else "not_eligible", "turnStatus": turn.status,
                "ui": {k: (result.get("ui") or {}).get(k) for k in ("eligible", "reason", "journeyIds")}}
    t_admit = time.monotonic()
    stream = api.stream("POST", f"/api/workspaces/{workspace}/agent/ui/presentations", token,
                        {"parentRunId": result["runId"], "slot": "main", "surface": "chat", "idempotencyKey": new_key("livep")}, timeout=60)
    if stream.body_if_json is not None:
        budget.charge(turn_cost)
        return {"caseId": case["caseId"], "status": "fail", "presentationStatus": stream.status}
    first_delta = ready = None
    events = []
    for event in stream.iter_events(max_seconds=90):
        events.append(event.get("event"))
        if event.get("event") == "ui.delta" and first_delta is None:
            first_delta = event["at"]
        if event.get("event") == "ui.ready":
            ready = event
    stream.close()
    terminal = stream.terminal or {}
    payload = (terminal.get("data") or {}).get("payload") or {}
    usage = payload.get("usage") or {}
    ui_cost = usage.get("costUsdMicro") if isinstance(usage, dict) else None
    budget.charge(None if turn_cost is None or ui_cost is None else int(turn_cost) + int(ui_cost))
    return {"caseId": case["caseId"], "journey": case.get("journey"), "status": "ready" if ready else (terminal.get("event") or "no_terminal"),
            "reason": payload.get("reason"), "artifactId": (terminal.get("data") or {}).get("artifactId"), "sourceHash": payload.get("sourceHash"),
            "deltas": events.count("ui.delta"), "turnMs": round((t_turn - t0) * 1000, 1),
            "admissionToFirstDeltaMs": round((first_delta - t_admit) * 1000, 1) if first_delta else None,
            "admissionToReadyMs": round((ready["at"] - t_admit) * 1000, 1) if ready else None,
            "timeOrigin": "client monotonic clock; t0 = POST …/presentations sent (API mode, no browser render)",
            "costUsdMicro": ui_cost, "costKnown": ui_cost is not None}


def stream_check(api: Api, token: str, workspace: str) -> dict:
    stream = api.stream("GET", f"/api/workspaces/{workspace}/agent/ui/diagnostics/stream", token, timeout=30)
    if stream.body_if_json is not None:
        return {"status": "fail", "httpStatus": stream.status}
    events = [e for e in stream.drain(max_seconds=30) if e.get("event") != "ui.heartbeat"]
    ended = stream.ended or time.monotonic()
    stream.close()
    spaced = len(events) >= 3 and events[2]["at"] - events[0]["at"] >= 1.0 and events[2]["at"] < ended
    return {"status": "pass" if spaced and stream.reader.decode_errors == 0 else "fail", "frames": len(events), "decodeErrors": stream.reader.decode_errors,
            "splitInsideCharacterObserved": stream.reader.split_inside_character(), "contentType": stream.headers.get("content-type"),
            "contentLengthAbsent": "content-length" not in stream.headers, "spanS": round(events[-1]["at"] - events[0]["at"], 3) if events else None}


def concurrency(api: Api, token_factory, workspace_factory, levels, prompt) -> list:
    """N parallel sessions, each its own principal/workspace on the loopback harness: no cross-tenant data, no duplicate effects."""
    from agent_ui_acceptance.client import new_key
    out = []
    for level in levels:
        results, threads = [], []

        def one(i):
            token = token_factory()
            workspace = workspace_factory(token)
            t0 = time.monotonic()
            turn = api.request("POST", f"/api/workspaces/{workspace}/agent/turns", token, {"message": prompt, "idempotencyKey": new_key("cc")}, timeout=180)
            body = turn.json() or {}
            status = "turn_failed" if turn.status not in (200, 201) else "not_eligible"
            artifact = None
            if (body.get("ui") or {}).get("eligible"):
                stream = api.stream("POST", f"/api/workspaces/{workspace}/agent/ui/presentations", token,
                                    {"parentRunId": body["runId"], "slot": "main", "surface": "chat", "idempotencyKey": new_key("ccp")}, timeout=60)
                if stream.body_if_json is None:
                    stream.drain(max_seconds=120)
                    stream.close()
                    status = (stream.terminal or {}).get("event") or "no_terminal"
                    artifact = ((stream.terminal or {}).get("data") or {}).get("artifactId")
                else:
                    status = f"http_{stream.status}"
            foreign = api.request("GET", f"/api/workspaces/{workspace}/agent/ui/presentations/{artifact}", token_factory()) if artifact else None
            results.append({"i": i, "status": status, "ms": round((time.monotonic() - t0) * 1000, 1), "foreignRead": foreign.status if foreign else None})
        threads = [threading.Thread(target=one, args=(i,)) for i in range(level)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(300)
        out.append({"level": level, "statuses": sorted({r["status"] for r in results}), "p95Ms": p95([r["ms"] for r in results]),
                    "crossTenantReads": [r["foreignRead"] for r in results if r["foreignRead"] not in (None, 403, 404)], "completed": len(results)})
    return out


# --- commands --------------------------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    guard_argv(argv)
    parser = argparse.ArgumentParser(description="Rafii Generative UI live acceptance (lane G)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    sub.add_parser("browser-snippet")
    sql = sub.add_parser("server-sql")
    sql.add_argument("--workspace", required=True)
    sql.add_argument("--since", required=True)
    for name in ("ingest", "run", "stream", "concurrency"):
        p = sub.add_parser(name)
        p.add_argument("--origin")
        p.add_argument("--workspace")
        p.add_argument("--budget-usd", type=float)
        p.add_argument("--sha", help="the deployed candidate SHA (default: this checkout's HEAD)")
        p.add_argument("--out", type=Path)
        p.add_argument("--case-estimate-usd", type=float, default=DEFAULT_CASE_ESTIMATE_USD)
        if name == "ingest":
            p.add_argument("--browser-results", type=Path, required=True, help="JSON from window.__rafiiLive.collect() (+ probe/filterCheck/hiddenCheck)")
            p.add_argument("--server-rows", type=Path, required=True, help="JSON array from server-sql")
        if name == "run":
            p.add_argument("--cases", default="normal", help="normal | all | comma list of case ids")
        if name == "concurrency":
            p.add_argument("--levels", default="1,5,20")
    args = parser.parse_args(argv)
    if args.command == "plan":
        print(json.dumps(sample_plan(), indent=1, ensure_ascii=False))
        return 0
    if args.command == "browser-snippet":
        print(BROWSER_SNIPPET)
        return 0
    if args.command == "server-sql":
        if not re.fullmatch(r"[0-9a-f-]{36}", args.workspace) or not re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.]+Z?", args.since):
            raise Refused("--workspace must be a uuid and --since an ISO timestamp")
        print(SERVER_SQL.format(workspace=args.workspace, since=args.since))
        return 0
    sha = args.sha or head_sha()
    plan = sample_plan()
    if args.command == "ingest":
        guard_live(args, needs_token=False)
        browser = json.loads(args.browser_results.read_text(encoding="utf-8"))
        rows = json.loads(args.server_rows.read_text(encoding="utf-8"))
        rows = rows[0] if rows and isinstance(rows[0], list) else rows
        merged = ingest(browser, rows if isinstance(rows, list) else [], plan)
        spent = sum(c["costUsdMicro"] or 0 for c in merged["cases"]) / 1_000_000
        unknown = sum(1 for c in merged["cases"] if c["costUsdMicro"] is None)
        payload = {"kind": "live-provider", "mode": "browser", "candidateSha": sha, "origin": args.origin, "dataScope": scope_hash(args.workspace),
                   "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "actor": "A (release owner) driving the real UI; G runner",
                   "userAgent": browser.get("userAgent"), "budget": {"capUsd": args.budget_usd, "serverReportedSpentUsd": round(spent, 6), "unknownCostCases": unknown,
                                                                    "overCap": spent > args.budget_usd},
                   **merged}
        path = write_evidence(payload, args.out, sha)
        print(json.dumps({"written": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path), "verdicts": {k: v["status"] for k, v in merged["verdicts"].items()}}))
        return 0 if all(v["status"] == "pass" for v in merged["verdicts"].values()) else 1
    if args.command == "concurrency":
        if os.environ.get("RAFII_LIVE_CHECKS") != "1":
            raise Refused("set RAFII_LIVE_CHECKS=1 (concurrency still issues many requests)")
        host = urlsplit(args.origin or "").hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise Refused("concurrency runs against the loopback acceptance harness only (fixture provider), never production")
        api = Api(args.origin)

        def token_factory():
            return f"dev:{uuid.uuid4()}"

        def workspace_factory(token):
            return (api.request("POST", "/api/auth/verify", token, {}).json() or {}).get("workspaceId")
        levels = [int(x) for x in str(args.levels).split(",") if x.strip()]
        result = concurrency(api, token_factory, workspace_factory, levels, "Show what's still left in a table I can filter")
        payload = {"kind": "ci-harness", "mode": "concurrency", "candidateSha": sha, "origin": args.origin, "provider": "fixture", "levels": result,
                   "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        path = write_evidence(payload, args.out or EVIDENCE_DIR / f"concurrency-{sha[:12]}.json", sha)
        print(json.dumps({"written": str(path), "levels": result}))
        return 0 if all(not r["crossTenantReads"] for r in result) else 1
    token = guard_live(args, needs_token=True)
    api = Api(args.origin)
    if args.command == "stream":
        result = stream_check(api, token, args.workspace)
        payload = {"kind": "production-canary", "mode": "api-stream", "gate": "G04", "candidateSha": sha, "origin": args.origin,
                   "dataScope": scope_hash(args.workspace), "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "probe": result}
        path = write_evidence(payload, args.out, sha)
        print(json.dumps({"written": str(path), "G04-probe": result["status"]}))
        return 0 if result["status"] == "pass" else 1
    budget = Budget(args.budget_usd, args.case_estimate_usd)
    chosen = plan["normal"] if args.cases in ("normal", "all") else [c for c in plan["normal"] if c["caseId"] in args.cases.split(",")]
    cases = [api_case(api, token, args.workspace, case, budget) for case in chosen if case["surface"] != "founder"]
    founder = [c["caseId"] for c in chosen if c["surface"] == "founder"]
    ready = [c for c in cases if c.get("status") == "ready"]
    payload = {"kind": "live-provider", "mode": "api", "candidateSha": sha, "origin": args.origin, "dataScope": scope_hash(args.workspace),
               "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "budget": budget.report(), "cases": cases,
               "unverified": {"founderCasesNeedTheFounderSurface": founder, "budgetSkipped": [c["caseId"] for c in cases if c.get("status") == "unverified"]},
               "summary": {"ready": len(ready), "ran": len(cases), "admissionToFirstDeltaP95Ms": p95([c.get("admissionToFirstDeltaMs") for c in ready[1:]]),
                           "admissionToReadyP95Ms": p95([c.get("admissionToReadyMs") for c in ready[1:]]),
                           "note": "API mode measures stream arrival, not rendered components; G17 render timings come from browser mode"}}
    path = write_evidence(payload, args.out, sha)
    print(json.dumps({"written": str(path), "summary": payload["summary"], "budget": payload["budget"]}))
    return 0 if len(ready) == len(cases) and not founder else 1


if __name__ == "__main__":
    raise SystemExit(main())
