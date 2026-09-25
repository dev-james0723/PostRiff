"""Live writer check of Rafii's site agent through a supported route: the person's own Claude Code CLI.

Runs the real hosted services on a disposable PostgreSQL cluster (its own port) with a seeded workspace and one live
writer: the `claude-code:*` route (ClaudeCliRuntime, the person's signed-in CLI; PostRiff pays nothing, each call is
capped by the route's own --max-budget-usd). Nothing is posted; no social account is involved.

Checks (each records model, run and draft ids, provenance, usage and cost as the app stores them):
1. rework: "Shorten this draft" → a writing run → saved as a proposed update on that draft → accepted → history kept;
2. voice: "Does this sound like me?" → measured findings plus the writer's labelled judgement;
3. fresh draft: "Write a LinkedIn post about practising slowly" from the Brand Brain and voice profile, then measured;
4. compound: "Shorten this draft, add it to the launch campaign and schedule it for Thursday at 6 PM" → steps done,
   scheduling left as a proposal waiting for approval;
5. failure: the same routes with a CLI that fails → grounded answer with `model_error`, a failed run reported as failed.

    PYTHONPATH=src:tests python scripts/site_agent_live_writer.py [--model claude-code:haiku] [--out evidence.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
PG = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
PORT = int(os.environ.get("SITE_AGENT_LIVE_PG_PORT", "55531"))
HK = "Asia/Hong_Kong"
ZONE = ZoneInfo(HK)
DRAFT_TEXT = ("Most adults who come back to the piano after twenty years make the same mistake: they try to play the whole piece every time they sit down, "
              "and then they wonder why nothing improves. I did it too when I started teaching adults, and I watched students do it week after week. "
              "The fix is almost boring. You choose one bar that trips you up, you play it slowly three times with your eyes on the keys, and then you stop for the day. "
              "It feels like too little. It is not. Over a month those small sessions add up to a piece you can play from start to finish, and you enjoy practising again. "
              "Try it tonight with the one bar you always stumble on.")


def cluster():
    tmp = Path(tempfile.mkdtemp(prefix="site-agent-live-"))
    data = tmp / "data"
    subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(tmp / "postgres.log"), "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
    for schema in ("tests/phase2/rls.sql", "migrations/postriff/017_cli_reasoning.sql"):
        # The test schema plus 017, which lets a run record a CLI's own reasoning level (low … max), as production has.
        subprocess.run([str(PG / "psql"), f"host=127.0.0.1 port={PORT} dbname=postgres", "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / schema)], check=True, stdout=subprocess.DEVNULL)
    return tmp, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-code:haiku")
    parser.add_argument("--out", default=str(ROOT / "docs/design/site-agent/evidence/live-writer.json"))
    parser.add_argument("--checks", default="rework,voice,fresh,compound,failure", help="comma-separated subset to run")
    parser.add_argument("--voice-repeats", type=int, default=3, help="how many times to ask the voice question (the model's phrasing can be rejected)")
    args = parser.parse_args()
    if shutil.which(os.environ.get("POSTRIFF_CLAUDE_BIN") or "claude") is None:
        print(json.dumps({"status": "BLOCKED", "reason": "the Claude Code CLI is not installed on this machine"}))
        return 3
    tmp, data = cluster()
    try:
        return run(args)
    finally:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=False, stdout=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


def run(args):
    # The checks are about the writer, so web research stays off (as in the PostgreSQL suites): a fresh draft is written
    # from the Brand Brain and voice profile only, and nothing is looked up on the live web.
    os.environ["POSTRIFF_RESEARCH"] = "0"
    import psycopg
    from postriff_alpha import learning, visuals
    from postriff_alpha.domain import AlphaError
    from postriff_phase2 import campaigns
    from postriff_phase2.hosted import HostedWorkspaceService
    from consumer_fixtures import approve_budgets

    dsn = f"host=127.0.0.1 port={PORT} dbname=postgres"
    users = {"owner-token-0000000000000000": "00000000-0000-0000-0000-000000000001"}
    owner = "owner-token-0000000000000000"

    def connection():
        return psycopg.connect(dsn, client_encoding="utf8")

    def verify(token):
        if token not in users:
            raise AlphaError("Verified session required.", 401)
        return users[token]

    now0 = time.time()
    verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
    verify.auth_time = lambda token, principal: now0
    with connection() as db:
        wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (users[owner],)).fetchone()[0])
        db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
        db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (users[owner],))
    service = HostedWorkspaceService(connection, verify)
    service.bootstrap(owner, "studio")
    approve_budgets(connection, wid)
    agent, ideas = service.site_agent, service.ideas
    catalog = [m["id"] for m in ideas.model_catalog()["models"]]
    if args.model not in catalog:
        print(json.dumps({"status": "BLOCKED", "reason": f"{args.model} is not an available writer here", "available": catalog}))
        return 3

    def state():
        return service.get(wid, owner)["state"]

    def revision():
        return service.get(wid, owner)["revision"]

    def command(fn):
        return service.repository.command(wid, owner, revision(), fn)

    def act(action, payload):
        return service.mutate(wid, owner, revision(), action, payload)

    def variant(variant_id):
        return next(v for v in state()["variants"] if v["id"] == variant_id)

    # --- seed: one account, Brand Brain, voice, two realistic drafts, one campaign ------------------------------------
    channel = {"id": uuid.uuid4().hex, "platform": "LinkedIn", "account": "Studio page", "accountType": "member", "scopes": ["w_member_social"], "verifiedAt": time.time(),
               "expiresAt": time.time() + 10**8, "capabilityVersion": 1, "providerAccountId": "urn:li:studio"}
    command(lambda s, actor: service.commands.upsert_verified_channel(s, actor, channel))

    def seed_brand(s, actor):
        s["brandHub"].update(purpose="Help adult piano learners practise with focus", audience="Adult piano learners returning to the instrument after years away",
                             subject="Piano practice and musicianship", mode="educator", speaker="Studio")
        visuals.apply(None, s, "you_identity", {"value": "I help adults come back to the piano."})
        s["speaker"]["revisions"] = [{"revision": 1, "approvedAt": time.time() - 86400, "reason": "Approved from two writing samples",
                                      "profile": {"tone": "warm", "observations": ["Opens with a short question to the reader.", "Keeps paragraphs to two sentences.",
                                                                                  "Ends with one practical step to try today."],
                                                  "writingExample": "Ever sat down at the piano and forgotten where to start? Pick one bar. Play it slowly three times.",
                                                  "unknowns": [], "fields": []}}]
        s["speaker"]["activeRevision"] = 1
        learning.remember(s, {"type": "writing_preference", "ruleKey": "emoji.use", "polarity": "avoid", "scope": {"platform": "LinkedIn"},
                              "statement": "Never use emoji on LinkedIn", "source": "chat"}, actor, time.time())
        learning.remember(s, {"type": "writing_preference", "ruleKey": "paragraphs.density", "polarity": "do", "scope": {}, "statement": "Keep paragraphs short",
                              "source": "chat"}, actor, time.time())
        return s

    command(seed_brand)

    def seeded_draft(topic):
        run = ideas.quick_start(wid, owner, revision(), {"text": topic, "confirmUse": True, "ownContent": True, "model": "deterministic-preview", "timeZone": HK,
                                                         "destinations": [{"platform": "LinkedIn", "language": "en", "channelId": channel["id"]}], "voiceMode": "neutral"})
        # Each seeded draft is its own draft (`separate`), not a refresh of the other one on the same account.
        ideas.apply(wid, owner, revision(), run["runId"], run["artifactHash"], separate=True)
        made = next(v for v in state()["variants"] if (v.get("provenance") or {}).get("runId") == run["runId"])
        act("variant_edit", {"variantId": made["id"], "variantRevision": made["revision"], "text": DRAFT_TEXT})
        return made["id"]

    draft_one = seeded_draft("Why adults should practise one bar at a time")
    draft_two = seeded_draft("Slow practice for returning adult pianists")

    def save_campaign(s, actor):
        campaigns.apply_action(s, "raffi_recurrence_save", {"name": "Autumn launch reflections", "goal": "Autumn product launch of the practice journal", "audience": "Adult piano learners",
                                                             "facts": {}, "schedule": {"weekdays": ["Friday"], "localTime": "09:00", "timeZone": HK},
                                                             "destinations": [{"platform": "LinkedIn", "language": "en", "channelId": channel["id"]}], "contentType": None,
                                                             "route": "deterministic-preview", "reasoning": "quick", "maxCostUsdMicro": 0, "sourceIds": [], "include": None,
                                                             "voiceMode": "neutral", "workflow": {"policy": "review"}}, actor, time.time())
        return s

    command(save_campaign)
    campaign_id = state()["raffi"]["campaignPlanning"]["campaigns"][0]["id"]

    def ask(message, entity=None, route="/app/queue", conversation=None, model=None):
        body = {"message": message, "idempotencyKey": uuid.uuid4().hex, "model": model or args.model, "timeZone": HK, "pageContext": {"route": route, **({"selectedEntity": entity} if entity else {})}}
        if conversation:
            body["conversationId"] = conversation
        return agent.turn(wid, owner, body)

    def wait(run_id, timeout=420):
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            events = ideas.events(wid, owner, run_id)
            if events["status"] not in ("running", "queued"):
                return events, round(time.monotonic() - started, 1)
            time.sleep(2)
        return ideas.events(wid, owner, run_id), round(time.monotonic() - started, 1)

    def apply_run(run_id, events):
        """Save a completed candidate as drafts; a refusal is recorded with what the run was given and what it cited."""
        if events["status"] != "completed":
            return {}
        try:
            return ideas.apply(wid, owner, revision(), run_id, events["artifactHash"])
        except AlphaError as error:
            artifact = events.get("artifact") or {}
            report.setdefault("applyRefusals", []).append({"runId": run_id, "error": str(error), "status": error.status,
                                                           "given": sorted(b["id"] for b in artifact.get("sourceBindings") or []),
                                                           "cited": [v.get("sourceIds") for v in artifact.get("variants") or []]})
            print(json.dumps(report["applyRefusals"][-1]), flush=True)
            return {}

    def warnings_of(site):
        return [{"code": b.get("code"), "message": b.get("text") or b.get("message")} for b in site.get("blocks") or [] if b.get("type") == "warning"]

    def run_row(run_id):
        with connection() as db:
            row = db.execute("SELECT status, model, reasoning, usage FROM public.pr_agent_runs WHERE id::text=%s", (run_id,)).fetchone()
        return {"status": row[0], "model": row[1], "reasoning": row[2], "usage": {k: row[3].get(k) for k in ("provenance", "modelRequests", "costUsd", "cliCostUsd", "billing", "ledgerCostState") if k in (row[3] or {})}}

    def ledger(run_id):
        with connection() as db:
            return [{"kind": r[0], "costState": r[1], "estimatedUsdMicro": r[2], "actualUsdMicro": r[3], "provider": r[4], "model": r[5]} for r in
                    db.execute("SELECT kind, cost_state, estimated_usd_micro, actual_usd_micro, provider, model FROM public.pr_usage_ledger WHERE run_id::text=%s ORDER BY at", (run_id,)).fetchall()]

    from postriff_phase2.site_agent import voice_check
    report = {"model": args.model, "route": "claude-code (ClaudeCliRuntime: the person's signed-in Claude Code CLI on this machine; a cloud route for source and memory egress, since the text goes to Anthropic; capped by --max-budget-usd per call)",
              "startedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "workspace": "disposable local PostgreSQL", "webResearch": "off (POSTRIFF_RESEARCH=0)", "checks": []}

    wanted = set(args.checks.split(","))

    def record(name, ok, **evidence):
        report["checks"].append({"check": name, "verdict": "PASS" if ok else "FAIL", **evidence})
        print(f"{'PASS' if ok else 'FAIL'} {name}", flush=True)

    # 1. rework: shorten a seeded draft through the writing pipeline, on exactly that draft -----------------------------
    if "rework" in wanted:
        before = variant(draft_one)
        turn = ask("Shorten this draft", {"type": "draft", "id": draft_one})
        events, seconds = wait(turn["runId"])
        candidate = (events.get("artifact") or {}).get("variants", [{}])[0].get("text", "")
        applied = apply_run(turn["runId"], events)
        proposed = variant(draft_one).get("proposedUpdate") or {}
        act("accept_update", {"variantId": draft_one}) if proposed else None
        after = variant(draft_one)
        kept_before = any(r.get("revision") == before["revision"] and r.get("text") == before["text"] for r in after["revisions"])
        latest = max(after["revisions"], key=lambda r: r.get("revision") or 0)
        ok = (events["status"] == "completed" and 0 < len(candidate) < len(before["text"]) and proposed.get("runId") == turn["runId"]
              and after["revision"] == before["revision"] + 1 and kept_before and latest.get("revision") == after["revision"] and latest.get("text") == candidate
              and after["text"] == candidate)
        record("rework: Shorten this draft", ok, runId=turn["runId"], seconds=seconds, run=run_row(turn["runId"]), ledger=ledger(turn["runId"]), draftId=draft_one,
               before={"characters": len(before["text"]), "revision": before["revision"]}, candidate={"characters": len(candidate), "text": candidate},
               after={"revision": after["revision"], "historyKept": kept_before, "history": [{"revision": r.get("revision"), "origin": r.get("origin"), "characters": len(r.get("text") or "")} for r in after["revisions"]]}, appliedAs=applied.get("variantIds"),
               reworkOf=(events.get("artifact") or {}).get("reworkOf"))

    # 2. voice: "Does this sound like me?" — measured findings plus the writer's labelled judgement ---------------------
    # Asked several times: the writer's phrasing is checked against what it was given and discarded when it cites
    # anything else, so the evidence reports how often it was accepted, and that every rejection fell back honestly.
    if "voice" in wanted:
        attempts = []
        for _ in range(max(1, args.voice_repeats)):
            turn = ask("Does this sound like me?", {"type": "draft", "id": draft_two})
            composed = agent.compose(wid, owner, turn["runId"]) if turn.get("needsCompose") else turn
            site = (composed.get("message") or {}).get("siteAgent") or {}
            texts = [b.get("text") or "" for b in site.get("blocks") or [] if b.get("type") == "text"]
            cards = [b for b in site.get("blocks") or [] if b.get("type") == "result_list"]
            with connection() as db:
                trace = (db.execute("SELECT artifact->'trace' FROM public.pr_agent_runs WHERE id::text=%s", (turn["runId"],)).fetchone() or [None])[0] or {}
                ledger_rows = db.execute("SELECT count(*) FROM public.pr_usage_ledger WHERE run_id::text=%s", (turn["runId"],)).fetchone()[0]
            by = (site.get("model") or {}).get("composedBy")
            warned = warnings_of(site)
            labelled = by == "model" and any(t.startswith("**Writer's judgement**") for t in texts)
            honest = (by == "grounded" and bool(warned) and (warned[0]["code"] or "").startswith("model_")
                      and any(phrase in (warned[0]["message"] or "") for phrase in ("didn't pass its checks", "didn't answer")))
            attempts.append({"runId": turn["runId"], "composedBy": by, "phrasedBy": (site.get("model") or {}).get("phrasedBy"), "tier": trace.get("tier") or None,
                             "labelledJudgement": labelled, "honestFallback": honest, "warning": warned[0] if warned else None,
                             "rejectedRefs": trace.get("rejectedRefs"), "fallbackDetail": trace.get("fallbackDetail"), "measuredCard": any(c["title"] == "Checked against your stored voice" for c in cards),
                             "measured": [i["title"] for c in cards for i in c["items"]][:10], "ledgerRows": ledger_rows,
                             "judgement": next((t for t in texts if t.startswith("**Writer's judgement**")), None)})
        accepted = sum(a["composedBy"] == "model" for a in attempts)
        ok = accepted >= 1 and all((a["labelledJudgement"] or a["honestFallback"]) and a["measuredCard"] for a in attempts)
        record("voice: Does this sound like me?", ok, modelAccepted=f"{accepted}/{len(attempts)}", attempts=attempts,
               note="Local CLI route: no PostRiff ledger reservation (the person's own plan pays). A rejected phrasing leaves the measured answer with a warning.")

    # 3. a fresh draft from the Brand Brain and voice profile, then measured against it ---------------------------------
    if "fresh" in wanted:
        turn = ask("Write a LinkedIn post about practising slowly", route="/app")
        events, seconds = wait(turn["runId"])
        fresh = (events.get("artifact") or {}).get("variants", [{}])[0]
        saved = apply_run(turn["runId"], events)
        fresh_id = next((item["variantId"] for item in saved.get("variantIds") or []), None)
        measured = voice_check.analyze(state(), fresh.get("text", ""), "LinkedIn") if fresh.get("text") else {}
        ok = events["status"] == "completed" and bool(fresh_id) and bool(fresh.get("text")) and (variant(fresh_id).get("provenance") or {}).get("model") == args.model
        record("fresh draft from Brand Brain + voice", ok, runId=turn["runId"], seconds=seconds, run=run_row(turn["runId"]), ledger=ledger(turn["runId"]), draftId=fresh_id,
               provenance=variant(fresh_id).get("provenance") if fresh_id else None, text=fresh.get("text"),
               voiceCheck={"summary": measured.get("summary"), "findings": [(f["trait"], f["verdict"], f["basis"]) for f in measured.get("findings", [])]})

    # 4. compound: rework + link + a scheduling proposal that waits for approval ------------------------------------------
    # 4a runs while the workspace's rewritten sources still need public-use approval: scheduling must stop at that gate
    # exactly when the saved rewrite cites such a source (the model decides what it cites). 4b runs after the owner
    # approves public use (the real `source_use_approve` action) and must end with one proposal waiting for approval.
    if "compound" in wanted:
        from postriff_phase2.source_policy import facts_digest, use_approved

        def compound_request(label):
            turn = ask("Shorten this draft, add it to the launch campaign and schedule it for Thursday at 6 PM", {"type": "draft", "id": draft_two})
            compound = ((turn.get("message") or {}).get("siteAgent") or {}).get("compound") or {}
            with connection() as db:
                stored = (db.execute("SELECT body->'siteAgent'->'compound' FROM public.pr_messages WHERE id::text=%s", (turn["messageId"],)).fetchone() or [None])[0] or {}
            first = {"pending": compound.get("pending"), "storedHasText": bool(stored.get("text")), "steps": {k: v.get("state") for k, v in (compound.get("status") or {}).items()}}
            run_id = compound.get("runId")
            events, seconds = wait(run_id) if run_id else ({"status": "none"}, 0)
            finished = (agent.compound_continue(wid, owner, {"conversationId": turn["conversationId"], "messageId": turn["messageId"], "timeZone": HK})
                        if compound.get("pending") else {"message": turn["message"]})
            site = (finished["message"] or {}).get("siteAgent") or {}
            steps = (site.get("compound") or {}).get("status", {})
            now_state = state()
            cited = ((variant(draft_two).get("proposedUpdate") or {}).get("sourceIds") or [])
            gated = [s["id"] for s in now_state.get("sources", []) if s["id"] in cited and s.get("active") and s.get("sourcePolicy") == "rewrite_approval" and not use_approved(s)]
            evidence = {"runId": run_id, "seconds": seconds, "firstAnswer": first, "steps": {k: v.get("state") for k, v in steps.items()},
                        "stepDetails": {k: v.get("detail") for k, v in steps.items()}, "citedSources": cited, "citedNeedingUseApproval": gated,
                        "proposals": [{k: p.get(k) for k in ("type", "localTime", "summary", "needsEdit", "status")} for p in site.get("proposals") or []],
                        "run": run_row(run_id) if run_id else None, "warnings": warnings_of(site)}
            common = ([steps.get(k, {}).get("state") for k in ("revise", "save", "link")] == ["done"] * 3 and first["pending"] and first["storedHasText"]
                      and draft_two in {i.get("variantId") for i in next(c for c in now_state["raffi"]["campaignPlanning"]["campaigns"] if c["id"] == campaign_id).get("items") or []}
                      and not any(r["manifest"]["variantId"] == draft_two for r in now_state["phase2"]["reviews"]))
            return evidence, steps, site.get("proposals") or [], gated, common

        evidence, steps, props, gated, common = compound_request("before approval")
        if gated:
            ok = common and steps.get("schedule", {}).get("state") == "needs_you" and "Approve public use" in steps["schedule"].get("detail", "") and not props
            expected = "scheduling stops: the rewrite cites a rewritten source that still needs public-use approval"
        else:
            ok = common and steps.get("schedule", {}).get("state") == "waiting" and len(props) == 1
            expected = "the rewrite cites no source needing approval, so scheduling is a proposal waiting for approval"
        record("compound (4a): shorten + link + schedule, before rewritten sources are approved", ok, expected=expected, **evidence)

        approved = []
        for source in state().get("sources", []):
            if source.get("active") and source.get("sourcePolicy") == "rewrite_approval" and not use_approved(source):
                act("source_use_approve", {"sourceId": source["id"], "factsDigest": facts_digest(source), "confirmed": True})
                approved.append(source["id"])
        evidence, steps, props, gated, common = compound_request("after approval")
        ok = (common and not gated and steps.get("schedule", {}).get("state") == "waiting" and len(props) == 1 and props[0].get("status") == "proposed"
              and "use the rewrite" in " ".join(props[0].get("summary") or []))
        record("compound (4b): shorten + link + schedule proposal, after the owner approves public use", ok, sourcesApprovedByOwner=approved,
               gatedBy="nothing is scheduled: the proposal must be applied, then the review approved", **evidence)

    # 5. failure: a CLI that fails -------------------------------------------------------------------------------------
    if "failure" in wanted:
        failing = Path(tempfile.mkdtemp()) / "claude"
        failing.write_text("#!/bin/sh\necho 'simulated writer failure' >&2\nexit 1\n")
        failing.chmod(0o755)
        previous = os.environ.get("POSTRIFF_CLAUDE_BIN")
        os.environ["POSTRIFF_CLAUDE_BIN"] = str(failing)
        try:
            turn = ask("Does this sound like me?", {"type": "draft", "id": draft_two})
            composed = agent.compose(wid, owner, turn["runId"]) if turn.get("needsCompose") else turn
            site = (composed.get("message") or {}).get("siteAgent") or {}
            # Two real modes, depending on when the CLI's sign-in is next checked: found unavailable before the call
            # (`writer_unavailable`, with the fix), or failing during the call (`model_*`, "didn't answer"). Either way the
            # grounded answer, with its measurements, is what the person gets.
            warning = next(iter(warnings_of(site)), {})
            code, said = warning.get("code") or "", warning.get("message") or ""
            mode = ("found unavailable before the call" if code == "writer_unavailable" else "failed during the call" if code.startswith("model_") else "unexpected")
            worded = ("claude auth login" in said) if code == "writer_unavailable" else ("didn't answer" in said)
            measured_card = any(b.get("type") == "result_list" and b.get("title") == "Checked against your stored voice" for b in site.get("blocks") or [])
            ok = site.get("model", {}).get("composedBy") == "grounded" and mode != "unexpected" and worded and measured_card
            record("failure: voice answer when the writer fails", ok, composedBy=site.get("model"), mode=mode, warning=warning, measuredCardKept=measured_card)
            # Either the CLI is found signed out before a run starts (the request is refused with the fix, nothing starts),
            # or it fails during the run (the run fails with its reason). Either way the draft is untouched.
            before_failure = variant(draft_two)
            try:
                turn = ask("Shorten this draft", {"type": "draft", "id": draft_two})
                events, seconds = wait(turn["runId"], timeout=120)
                failed = next((e.get("message") for e in events.get("events") or [] if e.get("type") == "run.failed"), None)
                mode = {"mode": "run failed", "runId": turn["runId"], "status": events["status"], "message": failed}
                refused_ok = events["status"] == "failed" and bool(failed)
            except AlphaError as error:
                mode = {"mode": "refused before any run", "status": error.status, "message": str(error)}
                refused_ok = error.status in (409, 503) and "claude" in str(error).lower()
            unchanged = variant(draft_two)
            untouched = unchanged["text"] == before_failure["text"] and unchanged["revision"] == before_failure["revision"] and unchanged.get("proposedUpdate") == before_failure.get("proposedUpdate")
            record("failure: writing request when the writer fails", refused_ok and untouched, draftUntouched=untouched, **mode)
        finally:
            if previous is None:
                os.environ.pop("POSTRIFF_CLAUDE_BIN", None)
            else:
                os.environ["POSTRIFF_CLAUDE_BIN"] = previous

    report["finishedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["summary"] = {v: sum(1 for c in report["checks"] if c["verdict"] == v) for v in ("PASS", "FAIL")}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(json.dumps(report["summary"]))
    return 0 if not report["summary"]["FAIL"] else 1


if __name__ == "__main__":
    sys.exit(main())
