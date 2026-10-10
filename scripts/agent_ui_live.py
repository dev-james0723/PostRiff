"""Budget-capped LIVE acceptance runner for Rafii Generative UI (rafii-genui/1; 04-ACCEPTANCE sample plan; D-A31).

Two ways to measure a deployed origin, neither of which ever puts a credential on disk:

* BROWSER mode (production sign-in is a passkey in a real browser). The release owner drives the real UI; this script only
  prints what to run and turns the results into evidence:
      plan             the fixed sample plan: the frozen G03 corpus of 60 normal generations (6 prompts × J01–J09 + 6 composite;
                       D-A53), 9 edits, fault cases, and the run order (each edit right after its journey's first conversation; J09 in the founder panel)
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

from agent_ui_acceptance import evidence, redaction  # noqa: E402
from agent_ui_acceptance.client import Api  # noqa: E402

EVIDENCE_DIR = ROOT / "docs/design/openui-production-2026-10-08/evidence/g"
TOKEN_ENV = "RAFII_LIVE_SESSION_TOKEN"
MAX_BUDGET_USD = 25.0
# One Manager turn + one presentation (+ at most one repair). Run 3 (2026-10-09) cost 2.29 USD for 27 cases + 8 edits, about
# 0.065 USD per generation with the Manager turn, so 0.07 stays conservative.
DEFAULT_CASE_ESTIMATE_USD = 0.07
FIRST_COMPONENT_P95_MS = 8000
FULL_UI_P95_MS = 30000

# --- the G03 live corpus (D-A53, James 2026-10-09) ----------------------------------------------------------------------------
# FIXED before any measurement: the denominator never changes afterwards, and no case is dropped or replaced because it fails.
# v1 (JOURNEY_PROMPTS / COMPOSITE_PROMPTS, cases a–c) stays byte-identical and first; v2 appends cases d–f per journey and
# CMP-d..f. Each journey's d–f run as one conversation, so a follow-up refers to the turn before it. Changing, dropping,
# replacing or reordering a case is a new corpus: it needs a new decision and a new G03_CORPUS_ID, and the pinned hash in
# tests/agent_ui_acceptance/test_agent_ui_acceptance_release.py fails until then.
G03_CORPUS_ID = "g03-live-60/v2"
G03_FIRST_PASS_AT_LEAST = 59           # of 60 (98.3%) first-pass valid; all 60 functional after at most one repair

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
# v2 (D-A53): cases d, e, f per journey, written from 01-ENGINEERING-SPEC §4 J01–J09. About a third are Hong Kong Cantonese in
# Traditional Chinese and some mix English and Chinese; several ask for data that may be partial, empty or unknown (the truthful
# answer is the pass); J09 stays read-only on the founder surface. The ids in V2_FOLLOW_UPS only make sense as a later turn of
# their journey's conversation. Every v2 case asks to SEE something (a table, agenda, timeline, gallery, list, comparison or
# chart): spec §2.3 keeps plain questions native, so a case whose correct answer has no view could never be functional. The
# feasibility review that reworded 20 of them to say so, before anything was measured, is recorded in D-A53.
JOURNEY_PROMPTS_V2 = {
    "J01": ("Pull up every draft I've touched in the last two weeks in a table with platform, language and when I last edited it, and put the English and Chinese versions side by side",
            "將第二篇同第四篇並排比較吓，邊篇比較啱 Instagram？我揀咗嘅寫手同語氣唔好改",
            "Of those two, which one isn't scheduled yet? Show me the draft with its current revision so I can edit it"),
    "J02": ("下個禮拜每日幾點出帖？用香港時間排個 agenda 出嚟，撞時間嘅幫我標示",
            "Now show that same week as an agenda in New York time and flag anything that lands between midnight and 6am there",
            "Has anything in the publishing queue failed or got stuck since 1 October? Group it by platform with the original scheduled time and time zone"),
    "J03": ("Search my Library for anything about Chopin (photos, audio, documents, links) and show it as a gallery with previews and where each item came from",
            "淨係要相同片，由新到舊排序，再幫我揀頭兩樣用嚟寫稿",
            "Have I got any audio from my September concerts in the Library? List all of it with the length and recording date of each"),
    "J04": ("Which of my sources is Rafii allowed to learn my voice from? 我想用表格睇埋每個 source 嘅 cloud consent 狀態",
            "For the ones that aren't eligible, show me the reason for each in a table, and whether my last voice-learning job actually finished",
            "Rafii 而家覺得我寫嘢係咩風格？已經學咗嘅同仲係建議緊嘅用表格分開列，每樣都要有證據同信心度"),
    "J05": ("Break my current campaign down by channel in a table: which posts belong to it, what status each one is in, and what it's waiting on",
            "仲有邊幾步未做完？用時間線顯示，邊樣卡住邊樣都要標明",
            "If I push the launch post back three days, which later steps does that affect? Just show me on the campaign timeline; don't change anything yet"),
    "J06": ("Chart my Instagram vs YouTube views for 1-30 September, day by day in Hong Kong time, and show how many posts each day is based on",
            "有幾日冇數，幫我用表格逐日列返出嚟，分清楚邊啲係真係零、邊啲係未有數據",
            "Drill into the best day on that chart: which posts drove it, with likes, comments and saves, and when those numbers were last updated"),
    "J07": ("幫我執好我儲低咗關於拉赫曼尼諾夫第二號鋼琴協奏曲嘅資料，做個列表，每個來源都要有日期同連結",
            "Put those sources in a comparison matrix: what each one says, its date, and which of my drafts already cites it",
            "Show the research briefs I made this month with how many citations each has and the date of its newest source"),
    "J08": ("Which of my automations run on weekends? Show me the schedule and next run of each in a table, in its own time zone and in Hong Kong time",
            "For the weekly one, show me the last five runs as a timeline, with what each one produced and any errors",
            "我嘅 Instagram 同 YouTube 連接有冇出問題？有嘅話逐個話我知喺 app 入面點整返"),
    "J09": ("Give me a breakdown of this month's model cost by provider and by surface, and show which days have incomplete cost data",
            "Drill into the most expensive day: show me the runs and workspaces that drove it in a table. Read-only, I only want to look",
            "今個月 MRR 同上個月比較係點？冇真實數據支持嘅數字就唔好估，話我知缺咗啲咩"),
}
COMPOSITE_PROMPTS_V2 = ("Find the Library photo from my last recital that got the most saves on Instagram, draft a Threads post around it in my voice, and slot it into next week's calendar where nothing collides; show me the week as an agenda",
                        "將頭先份草稿改做 LinkedIn 版本，加埋我儲低嘅研究來源，再放入而家個 campaign 度，同原本嗰份並排比較",
                        "Campaign 入面已經出咗嘅 posts 表現點？Show it in a table next to the campaign plan, and tell me which upcoming steps still have no content")
V2_FOLLOW_UPS = ("J01-e", "J01-f", "J02-e", "J03-e", "J04-e", "J05-e", "J05-f", "J06-e", "J06-f", "J07-e", "J08-e", "J09-e", "CMP-e")


def _surface(journey: str) -> str:
    return "founder" if journey == "J09" else "chat"


def _cases(journey_prompts: dict, composite: tuple, first: int) -> list:
    out = [{"caseId": f"{j}-{chr(97 + first + i)}", "journey": j, "kind": "generate", "surface": _surface(j), "prompt": p}
           for j, prompts in journey_prompts.items() for i, p in enumerate(prompts)]
    return out + [{"caseId": f"CMP-{chr(97 + first + i)}", "journey": "composite", "kind": "generate", "surface": "chat", "prompt": p}
                  for i, p in enumerate(composite)]


def corpus_sha256(normal: list) -> str:
    return hashlib.sha256(json.dumps(normal, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def run_order(normal: list, edits: list) -> list:
    """Deterministic: one entry per conversation step. Per journey: its v1 cases as one new conversation, then its edit in
    that same conversation ("continue": edit the base case's view while it is still in the thread), then its v2 cases as a
    second new conversation. Consumer chat first (J01–J08, then the composites), then the founder panel (J09-1, J09-edit,
    J09-2). Nothing is ever reopened: the founder panel's "New conversation" clears its in-memory thread."""
    groups: list = []
    edit_of = {edit["baseCase"]: edit for edit in edits}
    for journey in [*JOURNEY_PROMPTS, "composite"]:
        mine = [c for c in normal if c["journey"] == journey]
        prefix = "CMP" if journey == "composite" else journey
        for part, cases in ((1, mine[:3]), (2, mine[3:])):
            name = f"{prefix}-{part}"
            groups.append({"conversation": name, "journey": journey, "surface": _surface(journey), "start": "new", "cases": [c["caseId"] for c in cases]})
            for case in cases:
                edit = edit_of.get(case["caseId"])
                if edit is not None:
                    groups.append({"conversation": name, "journey": edit["journey"], "surface": edit["surface"], "start": "continue",
                                   "editOf": edit["baseCase"], "cases": [edit["caseId"]]})
    return sorted(groups, key=lambda g: g["surface"] == "founder")     # stable: order within each surface is kept


def run_sequence(plan: dict) -> list:
    return [case_id for group in plan["runOrder"] for case_id in group["cases"]]


def sample_plan() -> dict:
    normal = _cases(JOURNEY_PROMPTS, COMPOSITE_PROMPTS, 0) + _cases(JOURNEY_PROMPTS_V2, COMPOSITE_PROMPTS_V2, 3)
    edits = [{"caseId": f"{j}-edit", "journey": j, "kind": "edit", "baseCase": f"{j}-a", "surface": "founder" if j == "J09" else "chat", "instruction": text}
             for j, text in EDIT_CASES.items()]
    faults = [{"caseId": "F-cancel", "kind": "fault", "fault": "user cancel mid-stream", "expect": "ui.canceled; native answer kept; settled once"},
              {"caseId": "F-disconnect", "kind": "fault", "fault": "close the tab mid-stream", "expect": "interrupted; settled once; reopen shows last valid revision"},
              {"caseId": "F-retry", "kind": "fault", "fault": "explicit Try again after a failure", "expect": "cost/consent shown first; a new attempt, never automatic"}]
    return {"contractVersion": "rafii-genui/1",
            "corpus": {"id": G03_CORPUS_ID, "decision": "D-A53", "decidedBy": "James, 2026-10-09", "normalCases": len(normal), "sha256": corpus_sha256(normal),
                       "frozen": "at the merge commit of PR #157, which introduced it; cases 1–30 are the v1 corpus byte for byte",
                       "rule": "fixed before any measurement; the denominator never changes; no case is dropped or replaced because it fails",
                       "followUps": list(V2_FOLLOW_UPS)},
            "normal": normal, "edits": edits, "faults": faults, "runOrder": run_order(normal, edits),
            "denominators": {"G03": {"firstPassValidAtLeast": G03_FIRST_PASS_AT_LEAST, "of": len(normal), "functionalAfterOneRepair": len(normal)}},
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


LIVE_GATE_KINDS = {"G03": ("live-provider", "production-canary"), "G04": ("production-canary",), "G05": ("production-canary",),
                   "G10-live": ("live-provider",), "G17": ("live-provider",), "G18": ("production-canary",)}


def gate_records(verdicts: dict, *, sha: str, origin: str, data_scope: str, evidence_path: str) -> list:
    """Release-checkable records (evidence.record shape) for the gates a live browser run can evidence."""
    out = []
    for name, kinds in LIVE_GATE_KINDS.items():
        verdict = verdicts.get(name) or {}
        status = verdict.get("status") or "unverified"
        gate = name.split("-")[0]
        actual = json.dumps({k: v for k, v in verdict.items() if k not in ("status", "timeOrigins")}, ensure_ascii=False)[:900]
        for kind in kinds:
            out.append(evidence.record(gate, status, kind=kind, origin=origin, sha=sha, actor="A (real UI, passkey session) + G runner",
                                       command="scripts/agent_ui_live.py ingest (browser mode; docs/design/openui-production-2026-10-08/evidence/g/live-runbook.md)",
                                       expected=f"04-ACCEPTANCE {gate} live criteria", actual=actual, data_scope=f"allowlisted test workspace {data_scope}",
                                       evidence_paths=[evidence_path]))
    return out


def merge_browser(files) -> dict:
    """Several window.__rafiiLive.collect() files (e.g. the consumer chat page and the founder panel, or one page before and
    after a reload) as one collection. Each mark and resource keeps its page's performance.timeOrigin as `_origin`, so items
    from different pages order by wall-clock time (`_when`); timings are still taken within one page."""
    merged = {"cases": {}, "marks": [], "resources": []}
    for file in files:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        origin = data.get("timeOrigin") if isinstance(data.get("timeOrigin"), (int, float)) else 0.0
        merged["cases"].update(data.get("cases") or {})
        merged["marks"] += [{**m, "_origin": origin} for m in data.get("marks") or [] if isinstance(m, dict)]
        merged["resources"] += [{**r, "_origin": origin} for r in data.get("resources") or [] if isinstance(r, dict)]
        for key in ("probe", "filterCheck", "hiddenCheck", "userAgent", "faults"):
            if data.get(key) is not None and key not in merged:
                merged[key] = data[key]
    return merged


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


FIRST_MARK, READY_MARK = "rafii-genui:first-component", "rafii-genui:ready"


def _when(item: dict, key: str) -> float:
    """Wall-clock order of a browser mark/resource: its page's timeOrigin (set by merge_browser) plus its startTime."""
    value = item.get(key)
    return float(item.get("_origin") or 0.0) + (float(value) if isinstance(value, (int, float)) else 0.0)


def ingest(browser: dict, rows: list, plan: dict) -> dict:
    """Join browser marks (by artifactId) with server attempt rows; compute the G03/G04/G05/G17/G18 verdicts.

    G03 counts the plan's fixed corpus only (D-A53), and only each case's FIRST attempt: a case id outside the plan is
    reported as unplanned and never counted; a planned case without a collection stays missing. A generate case's artifact is
    the earliest one of its own (an artifact first seen under an earlier case, e.g. re-rendered after a reload, belongs to that
    case). A case run more than once under its id (more than one turn, or more than one artifact of its own) is `repeated`:
    it is neither first-pass valid nor functional, whatever a later attempt did, so a failed case can never be replaced by
    running it again. Server artifacts no case counts are listed as `uncountedArtifacts` for review (fault cases make some).
    Cases are listed in run order, so the cold case is the first case run."""
    by_artifact: dict = {}
    for row in rows:
        by_artifact.setdefault(str(row.get("artifact_id")), []).append(row)
    marks = sorted((m for m in browser.get("marks") or [] if isinstance(m, dict)), key=lambda m: _when(m, "at"))
    resources = sorted((r for r in browser.get("resources") or [] if isinstance(r, dict)), key=lambda r: _when(r, "start"))
    cases = []
    plan_cases = {c["caseId"]: c for c in plan["normal"] + plan["edits"]}

    def kind_of(case_id):
        return (plan_cases.get(case_id) or {}).get("kind") or ("edit" if case_id.endswith("-edit") else "generate")

    owner: dict = {}                          # artifactId -> the generate case it was first seen under (marks are in time order)
    for m in marks:
        if m.get("artifactId") and m.get("caseId") and kind_of(str(m["caseId"])) == "generate":
            owner.setdefault(m["artifactId"], m["caseId"])
    order = {case_id: index for index, case_id in enumerate(run_sequence(plan))}
    for case_id, meta in sorted((browser.get("cases") or {}).items(), key=lambda item: (order.get(item[0], len(order)), item[0])):
        planned = plan_cases.get(case_id, {})
        kind = kind_of(case_id)
        mine = [m for m in marks if m.get("caseId") == case_id]
        seen = list(dict.fromkeys(m["artifactId"] for m in mine if m.get("artifactId")))
        own = [a for a in seen if owner.get(a) == case_id] if kind == "generate" else seen
        artifact = own[0] if own else None
        first = next((m for m in mine if m.get("name") == FIRST_MARK and m.get("artifactId") == artifact), None)
        ready = next((m for m in mine if m.get("name") == READY_MARK and m.get("artifactId") == artifact), None)
        res = [r for r in resources if r.get("caseId") == case_id]
        turns = [r for r in res if str(r.get("route") or "").endswith("/agent/turns")]
        turn = turns[0] if turns else None
        present = next((r for r in res if re.search(r"/agent/ui/presentations(/:id/edits)?$", str(r.get("route") or ""))), None)
        attempts = sorted(by_artifact.get(str(artifact), []), key=lambda r: str(r.get("admitted_at")))
        repeated = kind == "generate" and (len(turns) > 1 or len(own) > 1)
        relevant = [a for a in attempts if (a.get("kind") in ("edit",) if kind == "edit" else a.get("kind") in ("generate", "repair"))]
        initial = next((a for a in relevant if a.get("kind") in ("generate", "edit")), None)
        repair = next((a for a in relevant if a.get("kind") == "repair"), None)
        final = repair or initial or {}
        cost = sum(int(a["cost_usd_micro"]) for a in relevant if a.get("cost_usd_micro") is not None)
        cases.append({
            "caseId": case_id, "journey": planned.get("journey"), "kind": kind, "planned": bool(planned), "repeated": repeated,
            "turns": len(turns), "artifactId": artifact, "revision": (ready or {}).get("revision"),
            "firstPassValid": bool(not repeated and initial and initial.get("state") == "ready" and initial.get("accepted") is not False),
            "repaired": bool(repair), "functional": not repeated and final.get("state") == "ready", "reason": final.get("reason"),
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
            "usable": not repeated and bool(ready) and final.get("state") == "ready",
        })
    normal = [c for c in cases if c["kind"] == "generate" and c["planned"]]
    edits = [c for c in cases if c["kind"] == "edit" and c["planned"]]
    unplanned = [c["caseId"] for c in cases if not c["planned"]]
    counted = {c["artifactId"] for c in cases if c["planned"] and c["artifactId"]}
    uncounted = sorted({str(r.get("artifact_id")) for r in rows if r.get("artifact_id") and r.get("kind") in ("generate", "repair")} - counted)
    missing_normal = sorted(set(c["caseId"] for c in plan["normal"]) - {c["caseId"] for c in normal})
    missing_edits = sorted(set(c["caseId"] for c in plan["edits"]) - {c["caseId"] for c in edits})
    first_pass = sum(1 for c in normal if c["firstPassValid"])
    functional = sum(1 for c in normal if c["functional"])
    warm = normal[1:] if len(normal) > 1 else []
    need = plan["denominators"]["G03"]
    misses = len(normal) - first_pass
    # The denominator is fixed: known misses beyond the allowance or a non-functional case fail the gate even while other
    # cases are missing; otherwise a short sample stays unverified.
    g03 = ("fail" if misses > need["of"] - need["firstPassValidAtLeast"] or functional < len(normal) else
           "unverified" if missing_normal else
           "pass" if first_pass >= need["firstPassValidAtLeast"] and functional == need["functionalAfterOneRepair"] == len(plan["normal"]) else "fail")
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
            "G03": {"status": g03, "firstPassValid": first_pass, "firstPassValidAtLeast": need["firstPassValidAtLeast"], "functional": functional,
                    "normalCases": len(normal), "required": len(plan["normal"]), "missingCases": missing_normal,
                    "repeatedCases": [c["caseId"] for c in normal if c["repeated"]], "unplannedCases": unplanned, "uncountedArtifacts": uncounted,
                    "corpus": {"id": plan["corpus"]["id"], "sha256": plan["corpus"]["sha256"]}},
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
            "G05": {"status": "unverified" if not filt or filt.get("modelAttemptDelta") is None else
                    ("pass" if filt.get("modelAttemptDelta") == 0 and filt.get("queryRequests", 0) >= 1 and not filt.get("presentationOrEditRequests") else "fail"), **filt},
            "G18": {"status": "unverified" if not hidden else ("pass" if hidden.get("hiddenCount") == 0 else "fail"), **hidden},
        },
    }


# --- API mode ------------------------------------------------------------------------------------------------------------------
def api_case(api: Api, token: str, workspace: str, case: dict, budget: Budget, conversation_id: str | None = None) -> dict:
    """One normal case as one turn (+ its presentation). `conversation_id` continues the case's conversation; the returned
    `_conversationId` is for the caller only and is removed before anything is written."""
    from agent_ui_acceptance.client import new_key
    if not budget.admit():
        return {"caseId": case["caseId"], "status": "unverified", "reason": "budget cap reached before this case", "_conversationId": conversation_id}
    t0 = time.monotonic()
    body = {"message": case["prompt"], "idempotencyKey": new_key("live"), "modality": "text", **({"conversationId": conversation_id} if conversation_id else {})}
    turn = api.request("POST", f"/api/workspaces/{workspace}/agent/turns", token, body, timeout=180)
    t_turn = time.monotonic()
    raw = turn.json() or {}
    result = {**(raw.get("result") if isinstance(raw.get("result"), dict) else {}), **{k: raw[k] for k in ("runId", "conversationId", "messageId") if raw.get(k)}}
    conversation = result.get("conversationId") or conversation_id
    turn_cost = ((result.get("usage") or {}).get("costUsdMicro"))
    if turn.status not in (200, 201) or not (result.get("ui") or {}).get("eligible"):
        budget.charge(turn_cost)
        return {"caseId": case["caseId"], "status": "fail" if turn.status not in (200, 201) else "not_eligible", "turnStatus": turn.status,
                "ui": {k: (result.get("ui") or {}).get(k) for k in ("eligible", "reason", "journeyIds")}, "_conversationId": conversation}
    t_admit = time.monotonic()
    stream = api.stream("POST", f"/api/workspaces/{workspace}/agent/ui/presentations", token,
                        {"parentRunId": result["runId"], "slot": "main", "surface": "chat", "idempotencyKey": new_key("livep")}, timeout=60)
    if stream.body_if_json is not None:
        budget.charge(turn_cost)
        return {"caseId": case["caseId"], "status": "fail", "presentationStatus": stream.status, "_conversationId": conversation}
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
            "costUsdMicro": ui_cost, "costKnown": ui_cost is not None, "_conversationId": conversation}


def run_conversations(api, token: str, workspace: str, plan: dict, selected, budget: Budget, case_fn=None):
    """API mode: the plan's normal cases in run order, one conversation per "new" runOrder entry (each later turn passes the
    conversation id its first turn returned; edit entries run in browser mode only). Founder cases are only listed: they
    need the founder surface (browser mode).
    `selected` (a set of case ids, or None for all) keeps run order; a follow-up run without its earlier turns starts a new
    conversation, so such a result is not corpus evidence."""
    case_fn = case_fn or api_case
    by_id = {c["caseId"]: c for c in plan["normal"]}
    results, founder = [], []
    for group in plan["runOrder"]:
        conversation = None
        for case_id in group["cases"]:
            case = by_id.get(case_id)
            if case is None or (selected is not None and case_id not in selected):
                continue                                   # edits run in browser mode only
            if group["surface"] == "founder":
                founder.append(case_id)
                continue
            result = case_fn(api, token, workspace, case, budget, conversation_id=conversation)
            conversation = result.pop("_conversationId", None) or conversation
            results.append(result)
    return results, founder


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
            if not isinstance(workspace, str) or not workspace:
                # The first sign-in itself failed under load: recorded as such (never a request to /workspaces/None).
                results.append({"i": i, "status": f"verify_failed:{workspace}", "ms": 0.0, "foreignRead": None})
                return
            turn = api.request("POST", f"/api/workspaces/{workspace}/agent/turns", token, {"message": prompt, "idempotencyKey": new_key("cc")}, timeout=180)
            raw = turn.json() or {}
            body = {**(raw.get("result") if isinstance(raw.get("result"), dict) else {}), "runId": raw.get("runId")}
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
            p.add_argument("--browser-results", type=Path, nargs="+", required=True,
                           help="JSON from window.__rafiiLive.collect() (+ probe/filterCheck/hiddenCheck); one file per page (consumer, founder)")
            p.add_argument("--server-rows", type=Path, required=True, help="JSON array from server-sql")
        if name == "run":
            p.add_argument("--cases", default="normal", help="normal | all | comma list of case ids (always run in plan run order, one conversation per runOrder entry)")
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
        browser = merge_browser(args.browser_results)
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
        shown = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        records = gate_records(merged["verdicts"], sha=sha, origin=args.origin, data_scope=scope_hash(args.workspace), evidence_path=shown)
        results = (path.parent / "results") if args.out is None else path.parent
        results.mkdir(parents=True, exist_ok=True)
        record_path = results / (path.stem + ".records.json")
        redaction.assert_clean({"records": records})
        record_path.write_text(json.dumps({"records": records}, indent=1, ensure_ascii=False))
        print(json.dumps({"written": shown, "gateRecords": str(record_path), "verdicts": {k: v["status"] for k, v in merged["verdicts"].items()}}))
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
            answer = api.request("POST", "/api/auth/verify", token, {})
            return (answer.json() or {}).get("workspaceId") if answer.status in (200, 201) else answer.status
        levels = [int(x) for x in str(args.levels).split(",") if x.strip()]
        # The harness QA script's J05 flow (campaign specialist → campaign_list) with an explicit UI intent: eligible for a view.
        result = concurrency(api, token_factory, workspace_factory, levels, "Chart what's missing in the campaign by status")
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
    selected = None if args.cases in ("normal", "all") else set(args.cases.split(","))
    cases, founder = run_conversations(api, token, args.workspace, plan, selected, budget)
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
