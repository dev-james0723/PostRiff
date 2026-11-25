"""Real-model personal-writing evaluation through the person's own signed-in CLI (HUMAN-EVALUATION.md).

Runs the real hosted services on a disposable PostgreSQL cluster (its own port) and drives the actual product
path: retain authored samples with separate grants -> local-rules analysis -> owner approval -> neutral and
personalized drafts for the same fixed brief -> one-off correction -> remembered correction (pending, accepted,
paused, retired) in fresh service sessions. The writer is the `claude-code:*` or `codex:*` route (the person's own
subscription; a cloud route for egress, since the text goes to the vendor). Nothing is posted or published.

The script records what happened; it never scores voice. A person judges the blind packet it writes. Every
attempt is kept, including failures. Sample text, prompts and drafts go to --out (keep that outside the repo when
the samples are private); only hashes are needed in the repository's evidence index.

    PYTHONPATH=src:tests python scripts/pwi_real_voice_eval.py --config eval.json --out <evidence dir>

Config (JSON): {"label", "voice", "model", "fixture" (true when the samples are not the target author's),
"brand" (optional brandHub fields), "teaching": [{"key","text","platform","language","title"}],
"heldOut": [{"key","text"}] (hashed only, never imported), "briefs": {key: {"text","platform","language"}},
"blindPairs": [brief keys], "examplesArm" (true: after the blind pairs, also allow the writer to read the teaching
samples as style examples and draft each blind brief again), "oneOff": {"brief","instruction"}, "correction": {"instruction","fixedBrief",
"transferBrief","unrelated": {"platform","language"}}}.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
PG = Path(os.environ.get("POSTRIFF_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
# macOS: without a fixed C locale the postmaster aborts with "became multithreaded during startup".
os.environ.setdefault("LC_ALL", "C")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
HASHTAG = re.compile(r"(?<![\w#])#\w+")
OWNER = "owner-token-0000000000000000"
OWNER_ID = "00000000-0000-0000-0000-000000000001"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def cluster(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))   # refuse a collision before any data is loaded
    tmp = Path(tempfile.mkdtemp(prefix="pwi-real-eval-"))
    data = tmp / "data"
    try:
        subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(tmp / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
        for schema in ("tests/phase2/rls.sql", "migrations/postriff/017_cli_reasoning.sql"):
            # 017 lets a run record a CLI's own reasoning level (low … max), as production has.
            subprocess.run([str(PG / "psql"), f"host=127.0.0.1 port={port} dbname=postgres", "-v", "ON_ERROR_STOP=1", "-q", "-f", str(ROOT / schema)], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PWI_REAL_EVAL_PG_PORT", "55541")))
    parser.add_argument("--stages", default="voice,blind,examples,oneoff,correction", help="comma-separated subset")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(json.dumps({"status": "BLOCKED", "reason": "the evidence directory is not empty; earlier attempts are never overwritten"}))
        return 3
    tmp, data = cluster(args.port)
    try:
        (out / "prompts").mkdir(parents=True, exist_ok=True)
        return run(args, config, out)
    finally:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=False, stdout=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


def run(args, config, out):
    os.environ["POSTRIFF_RESEARCH"] = "0"                      # fixed facts: nothing is looked up on the live web
    os.environ["RAFII_CREATION_ALL_PLATFORMS_ENABLED"] = "1"   # the existing flag, in this process only
    os.environ["RAFII_CREATION_PROJECTION_ENABLED"] = ""
    for key in ("AI_GATEWAY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(key, None)                              # no paid route can be picked up by accident
    import psycopg
    from postriff_alpha.domain import AlphaError
    from postriff_phase2 import creation_capabilities, learning_signals
    from postriff_phase2.cli_runtime import ClaudeCliRuntime, restricted_environment
    from postriff_phase2.codex_runtime import CodexCliRuntime
    from postriff_phase2.coworker import flags
    from postriff_phase2.hosted import HostedWorkspaceService
    from consumer_fixtures import approve_budgets

    flags.attach(None)
    creation_capabilities._CACHE.clear()
    dsn = f"host=127.0.0.1 port={args.port} dbname=postgres"
    model = config["model"]
    provider = model.split(":", 1)[0]
    route = f"cloud:{provider}:{model}"
    stages = set(args.stages.split(","))
    started = time.time()
    prompts = []

    def connection():
        return psycopg.connect(dsn, client_encoding="utf8")

    def verify(token):
        if token != OWNER:
            raise AlphaError("Verified session required.", 401)
        return OWNER_ID

    verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
    verify.auth_time = lambda token, principal: started

    def observed(base):
        """The product's own runtime, unchanged, plus a record of the exact prompt it composed."""
        class Observed(base):
            def compose(self, request):
                system, user = super().compose(request)
                name = f"{len(prompts) + 1:03d}-{sha(system + user)[:12]}.json"
                (out / "prompts" / name).write_text(json.dumps({"model": request.get("model"), "reasoning": request.get("reasoning"), "system": system, "user": user}, ensure_ascii=False, indent=1))
                prompts.append({"file": f"prompts/{name}", "systemSha256": sha(system), "userSha256": sha(user), "systemChars": len(system), "userChars": len(user), "at": now()})
                return system, user
        return Observed()

    def fresh_service():
        """A new service object: no in-memory workspace, conversation or runtime state survives."""
        service = HostedWorkspaceService(connection, verify)
        service.ideas.runtimes = [observed(type(r)) if type(r) in (ClaudeCliRuntime, CodexCliRuntime) else r for r in service.ideas.runtimes]
        return service

    with connection() as db:
        wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (OWNER_ID,)).fetchone()[0])
        db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
        db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (OWNER_ID,))
        for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events"):
            db.execute(f"DELETE FROM public.{table} WHERE workspace_id=%s", (wid,))
    box = {"service": fresh_service()}
    box["service"].bootstrap(OWNER, "studio")
    approve_budgets(connection, wid)

    def service():
        return box["service"]

    def state():
        return service().get(wid, OWNER)["state"]

    def revision():
        return service().get(wid, OWNER)["revision"]

    def act(action, payload):
        return service().mutate(wid, OWNER, revision(), action, payload)

    def request_id():
        return uuid.uuid4().hex

    def voice_file():
        files = service().ideas.memory_files(wid, OWNER)["files"]
        return next((f["body"] for f in files if f["name"] == "VOICE.md"), "")

    def durable():
        with connection() as db:
            return {table: db.execute(f"SELECT count(*) FROM public.{table} WHERE workspace_id=%s", (wid,)).fetchone()[0]
                    for table in ("pr_memory_versions", "pr_memory_proposals", "pr_learning_events")}

    report = {"schema": "rafii.pwi-real-eval.v1", "label": config["label"], "voice": config["voice"], "fixture": bool(config.get("fixture")),
              "sourceSha": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
              "sourceDirty": bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "src", "skills", "migrations"], capture_output=True, text=True).stdout.strip()),
              "environment": "LOCAL real hosted services + disposable PostgreSQL; writer = the person's signed-in CLI (cloud egress to the vendor)",
              "model": model, "writerRoute": route, "webResearch": "off", "startedAt": now(), "runs": [], "checks": [], "errors": [],
              "limitations": ["A small pilot: these cases only. It cannot establish all-platform quality or a general improvement rate.",
                              "One generation per cell; model randomness can affect any single pair.",
                              "This file records outputs and receipts. It contains no voice-quality verdict: a person judges the blind packet."]}
    catalog = {m["id"]: m for m in service().ideas.model_catalog()["models"]}
    if not (catalog.get(model) or {}).get("qualified"):
        report["status"] = "BLOCKED"
        report["errors"].append({"stage": "route", "error": f"{model} is not an available signed-in writer here", "available": sorted(k for k, v in catalog.items() if v.get("qualified"))})
        (out / "raw-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        print(json.dumps({"status": "BLOCKED", "reason": report["errors"][0]["error"]}))
        return 3
    report["routeProbe"] = {k: catalog[model].get(k) for k in ("id", "label", "qualified", "costClass", "route")}
    if provider == "claude-code":
        # The run receipt keeps the alias only; ask the CLI which model the alias resolves to on this account today.
        alias = model.split(":", 1)[1]
        probe = subprocess.run(["claude", "-p", "Reply with exactly: OK", "--output-format", "json", "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                                "--no-session-persistence", *([] if alias == "default" else ["--model", alias])], capture_output=True, text=True, timeout=120, env=restricted_environment(), cwd=os.environ.get("TMPDIR", "/tmp"))
        try:
            parsed = json.loads(probe.stdout.strip().splitlines()[-1])
            report["routeProbe"]["aliasResolvesTo"] = sorted((parsed.get("modelUsage") or {}).keys())
            report["routeProbe"]["probeResult"] = parsed.get("result")
        except (ValueError, IndexError):
            report["routeProbe"]["aliasResolvesTo"] = None
            report["errors"].append({"stage": "route", "error": "alias probe returned no JSON", "stdout": probe.stdout[:400]})

    def check(name, ok, **evidence):
        report["checks"].append({"check": name, "verdict": "PASS" if ok else "FAIL", **evidence})
        print(f"{'PASS' if ok else 'FAIL'} {name}", flush=True)

    def save():
        report["prompts"] = prompts
        (out / "raw-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))

    def wait(run_id, timeout=420):
        begun = time.monotonic()
        while time.monotonic() - begun < timeout:
            events = service().ideas.events(wid, OWNER, run_id)
            if events["status"] not in ("running", "queued"):
                return events, round(time.monotonic() - begun, 1)
            time.sleep(2)
        return service().ideas.events(wid, OWNER, run_id), round(time.monotonic() - begun, 1)

    def draft(stage, label, brief_key, mode, *, destination=None, text=None):
        """One real drafting turn in a new conversation. Every attempt is recorded, whatever happened."""
        brief = config["briefs"][brief_key]
        destination = destination or {"platform": brief["platform"], "language": brief["language"]}
        record = {"stage": stage, "label": label, "brief": brief_key, "briefSha256": sha(brief["text"]), "requestedVoiceMode": mode, "destination": destination,
                  "voiceFileSha256": sha(voice_file()), "promptIndex": len(prompts), "at": now()}
        try:
            cid = service().ideas.create_conversation(wid, OWNER, f"PWI eval {label}")["conversationId"]
            turn = service().ideas.turn(wid, OWNER, cid, {"text": text or brief["text"], "destinations": [destination], "model": model, "voiceMode": mode,
                                                           "timeZone": config.get("timeZone", "Asia/Hong_Kong"), "research": False})
            record.update(conversationId=cid, runId=turn.get("runId"), turnStatus=turn.get("status"))
            events, seconds = wait(turn["runId"]) if turn.get("status") in ("running", "queued") else (turn, 0)
            artifact = events.get("artifact") or {}
            usage = events.get("usage") or {}
            variant = (artifact.get("variants") or [{}])[0]
            receipt = artifact.get("memoryReceipt") or {}
            counted = {"tokens": learning_signals.word_count(variant.get("text") or ""), "chars": len((variant.get("text") or "").strip())}
            record.update(status=events.get("status"), seconds=seconds, artifactHash=events.get("artifactHash"), reasoning=events.get("reasoning"),
                          draftedPlatform=variant.get("platform"), draftedLanguage=variant.get("language"), variantCount=len(artifact.get("variants") or []),
                          words=counted["tokens"], chars=counted["chars"], emoji=len(EMOJI.findall(variant.get("text") or "")), hashtags=len(HASHTAG.findall(variant.get("text") or "")),
                          text=variant.get("text"), textSha256=sha(variant.get("text") or ""), unknowns=variant.get("unknowns"), warnings=variant.get("warnings"),
                          sourceIds=variant.get("sourceIds"), voiceContext=artifact.get("voiceContext"),
                          memoryReceipt={k: receipt.get(k) for k in ("effectiveVoiceMode", "requestedVoiceMode", "writerRoute", "activeVoiceRevision", "filesIncluded", "filesWithheld", "withheldFragments",
                                                                      "preferenceSetDigest", "preferencesIncludedDigest", "sourceGrantDigest", "memoryContextDigest", "voiceContextDigest")},
                          preferencesUsed=(usage.get("memoryBindings") or {}).get("used"), preferencesOmitted=(usage.get("memoryBindings") or {}).get("omitted"),
                          skillBindings=usage.get("skillBindings"), usage={k: usage.get(k) for k in ("provenance", "billing", "modelRequests", "costUsd", "cliCostUsd", "durationMs", "numTurns", "model", "inputHash", "tokens") if k in usage},
                          failure=next((e.get("message") for e in events.get("events") or [] if e.get("type") == "run.failed"), None),
                          prompt=prompts[record["promptIndex"]] if len(prompts) > record["promptIndex"] else None)
        except AlphaError as error:
            record.update(status="refused", error=str(error), httpStatus=error.status)
        except Exception as error:  # noqa: BLE001 - an attempt that broke is evidence too
            record.update(status="harness_error", error=f"{type(error).__name__}: {error}")
        if record.get("status") == "completed" and record.get("draftedPlatform") != destination["platform"]:
            # A channel named in the message re-routes the turn by design; a brief must not name one.
            report["errors"].append({"stage": stage, "label": label, "error": f"drafted for {record.get('draftedPlatform')}, not the requested {destination['platform']}; this cell is not valid evidence"})
        report["runs"].append(record)
        save()
        print(f"{record.get('status')} {stage}/{label} {record.get('draftedPlatform')} {mode} -> {record.get('memoryReceipt', {}).get('effectiveVoiceMode')} prefs={record.get('preferencesUsed')} words={record.get('words')}", flush=True)
        return record

    def stage(name, fn):
        if name not in stages:
            return
        try:
            fn()
        except Exception as error:  # noqa: BLE001 - keep what was gathered and say where it stopped
            status = getattr(error, "status", None)
            report["errors"].append({"stage": name, "error": f"{type(error).__name__}: {error}", "httpStatus": status})
            print(f"ERROR {name}: {type(error).__name__}: {error}", flush=True)
        save()

    # --- F1: retain the authored samples, grant exact routes, analyse locally, approve ---------------------------------
    def teach():
        if config.get("brand"):
            service().repository.command(wid, OWNER, revision(), lambda s, actor: (s["brandHub"].update(config["brand"]), s)[1])
        act("memory_egress", {"cloud": True, "confirmed": True})
        report["heldOut"] = [{"key": item["key"], "sha256": sha(item["text"]), "chars": len(item["text"]), "imported": False} for item in config.get("heldOut", [])]
        source_ids, teaching = [], []
        for sample in config["teaching"]:
            before = {s["id"] for s in state().get("sources", [])}
            act("brand_brain_import", {"format": "pasted", "text": sample["text"], "title": sample.get("title", sample["key"]), "platform": sample.get("platform", ""),
                                       "language": sample.get("language", ""), "authorshipConfirmed": True, "retentionConfirmed": True, "requestId": request_id()})
            source_id = next(s["id"] for s in state()["sources"] if s["id"] not in before and s.get("kind") == "voice_sample")
            act("voice_sample_select", {"sourceId": source_id, "selected": True})
            act("voice_sample_grant", {"sourceId": source_id, "confirmed": True, "grants": [{"purpose": "analysis", "route": "local-rules"}, {"purpose": "generation", "route": route}]})
            source_ids.append(source_id)
            teaching.append({"key": sample["key"], "sourceId": source_id, "sha256": sha(sample["text"]), "chars": len(sample["text"]), "platform": sample.get("platform"), "language": sample.get("language")})
        act("brand_brain_analyze", {"sourceIds": source_ids, "requestId": request_id()})
        brain = state()["brandBrain"]
        proposal = state()["speaker"]["provisional"]
        report["voice"] = {"target": config["voice"], "teaching": teaching, "analysisMethod": proposal.get("analysisMethod"), "tone": proposal.get("tone"),
                           "observations": proposal.get("observations"), "unknowns": proposal.get("unknowns"), "writingExampleChars": len(proposal.get("writingExample") or ""),
                           "grants": [{"purpose": "analysis", "route": "local-rules"}, {"purpose": "generation", "route": route}]}
        act("brand_brain_approve", {"proposalDigest": brain["proposalDigest"], "impactDigest": brain["impact"]["impactDigest"], "confirmed": True, "requestId": request_id()})
        report["voice"]["activeRevision"] = state()["speaker"].get("activeRevision")
        report["voice"]["voiceFile"] = voice_file()
        held = {item["sha256"] for item in report["heldOut"]}
        check("held-out pieces were not imported", not held & {s.get("contentHash") for s in state().get("sources", [])})
        check("an approved voice revision is active", bool(report["voice"]["activeRevision"]), activeRevision=report["voice"]["activeRevision"])

    # --- F3: neutral and personalized drafts of the same fixed briefs ---------------------------------------------------
    def blind():
        for key in config["blindPairs"]:
            neutral = draft("blind", f"{key}-neutral", key, "neutral")
            personal = draft("blind", f"{key}-personalized", key, "personalized")
            check(f"{key}: neutral run carried no voice file", neutral.get("status") == "completed" and "VOICE.md" not in (neutral.get("memoryReceipt") or {}).get("filesIncluded", ["VOICE.md"]), run=neutral.get("runId"))
            check(f"{key}: personalized run carried the approved voice", personal.get("status") == "completed" and (personal.get("memoryReceipt") or {}).get("effectiveVoiceMode") == "approved",
                  run=personal.get("runId"), effective=(personal.get("memoryReceipt") or {}).get("effectiveVoiceMode"))

    def sent(record):
        """The destinations and style examples the writer was actually given for one recorded draft."""
        if not record.get("prompt"):
            return {}
        return json.loads(json.loads((out / record["prompt"]["file"]).read_text())["user"].split("INPUT\n", 1)[1])

    # --- F3 with the opt-in permission: the same briefs, the writer may also read the samples as style examples ---------
    def with_examples():
        if not config.get("examplesArm"):
            return
        leaked = [r["label"] for r in report["runs"] if r["stage"] == "blind" and sent(r).get("voiceSamples")]
        check("no sample text reached the writer before the example permission was given", not leaked, leaked=leaked)
        for sample in report["voice"]["teaching"]:
            act("voice_sample_grant", {"sourceId": sample["sourceId"], "confirmed": True, "grants": [
                {"purpose": "analysis", "route": "local-rules"}, {"purpose": "generation", "route": route}, {"purpose": "examples", "route": route}]})
        report["voice"]["grants"].append({"purpose": "examples", "route": route})
        for key in config["blindPairs"]:
            record = draft("examples", f"{key}-personalized-examples", key, "personalized")
            given = sent(record).get("voiceSamples") or []
            read = (record.get("voiceContext") or {}).get("examples") or []
            record["styleExamples"] = {"sentCount": len(given), "sentChars": [len(item.get("text") or "") for item in given], "recorded": read}
            teaching = {item["sourceId"] for item in report["voice"]["teaching"]}
            check(f"{key}: the writer read teaching samples as style examples and the run recorded which",
                  record.get("status") == "completed" and 1 <= len(given) <= 3 and len(read) == len(given) and {item["id"] for item in read} <= teaching,
                  sent=len(given), recorded=[item["id"] for item in read])
        held = [item["text"] for item in config.get("heldOut", [])]
        check("no held-out text was sent as a style example", not any(text[:200] in json.dumps(sent(r), ensure_ascii=False) for r in report["runs"] if r["stage"] == "examples" for text in held))

    # --- L1 control: a "this draft only" correction teaches nothing ------------------------------------------------------
    def one_off():
        spec = config["oneOff"]
        brief = config["briefs"][spec["brief"]]
        before = durable()
        first = draft("oneoff", "one-off-instruction", spec["brief"], "personalized", text=spec["instruction"] + "\n\n" + brief["text"])
        after = durable()
        check("one-off instruction is an ordinary draft, not a memory proposal", first.get("turnStatus") != "memory" and first.get("status") == "completed", status=first.get("status"))
        check("one-off instruction created no durable preference, proposal or learning event", before == after, before=before, after=after)
        box["service"] = fresh_service()
        later = draft("oneoff", "fresh-session-after-one-off", spec["brief"], "personalized")
        check("fresh session after the one-off binds no preference", later.get("status") == "completed" and later.get("preferencesUsed") == [], used=later.get("preferencesUsed"))

    # --- L1: a remembered correction, pending -> accepted -> fresh session -> transfer -> controls -> paused -> retired --
    def correction():
        spec = config["correction"]
        fixed, transfer = spec["fixedBrief"], spec["transferBrief"]
        cid = service().ideas.create_conversation(wid, OWNER, "PWI eval remembered correction")["conversationId"]
        calls = len(prompts)
        proposed = service().ideas.turn(wid, OWNER, cid, {"text": spec["instruction"], "model": model})
        proposal = proposed.get("memoryProposal")
        report["correction"] = {"instruction": spec["instruction"], "turnStatus": proposed.get("status"), "proposal": proposal, "writerCallsForProposal": len(prompts) - calls}
        check("standing instruction became a reviewed proposal without a writer call", proposed.get("status") == "memory" and bool(proposal) and len(prompts) == calls, proposal=proposal)
        if not proposal:
            return
        pre = draft("correction", "pre-accept-baseline", fixed, "personalized")
        check("a pending proposal is not applied", pre.get("status") == "completed" and pre.get("preferencesUsed") == [], used=pre.get("preferencesUsed"))
        decision = service().learning.decide(service().repository, wid, OWNER, revision(), proposal["id"], "remember")
        item_id = decision["item"]["id"]
        report["correction"].update(itemId=item_id, versionId=decision.get("versionId"), acceptedStatement=decision["item"].get("statement"), acceptedScope=decision["item"].get("scope"), acceptedAt=now())
        box["service"] = fresh_service()
        report["correction"]["voiceFileAfterAccept"] = voice_file()
        post = draft("correction", "post-accept-same-brief", fixed, "personalized")
        check("fresh session binds the accepted preference on the same brief", post.get("preferencesUsed") == [item_id], used=post.get("preferencesUsed"))
        moved = draft("correction", "post-accept-unseen-brief", transfer, "personalized")
        check("accepted preference transfers to a separate unseen brief", moved.get("preferencesUsed") == [item_id], used=moved.get("preferencesUsed"))
        limit = learning_signals.length_limit(decision["item"].get("statement"))
        counted_rule = {"emoji.use": "emoji", "hashtags.use": "hashtags"}.get(decision["item"].get("ruleKey")) if decision["item"].get("polarity") == "avoid" else None
        if counted_rule:
            # A rule only shows an effect where the draft without it had something to remove; say so when it did not.
            report["correction"]["countedRule"] = {"measure": counted_rule, "baseline": pre.get(counted_rule), "observableEffect": bool(pre.get(counted_rule))}
        for name, record in (("same brief", post), ("unseen brief", moved)):
            if counted_rule:
                # Counted, never taken from the writer's note.
                record["rememberedCount"] = {"measure": counted_rule, "count": record.get(counted_rule), "baseline": pre.get(counted_rule)}
                check(f"remembered 'no {counted_rule}' on the {name}: the draft has none", record.get("status") == "completed" and record.get(counted_rule) == 0, count=record.get(counted_rule), baseline=pre.get(counted_rule))
            if not limit:
                continue
            # Whether the writer complied is measured, never taken from its own note. Over-length is a recorded
            # outcome for the reviewer; what must hold is that the person is told the measured count.
            due = learning_signals.length_reminder(decision["item"].get("statement"), record.get("text"))
            destinations = sent(record).get("destinations") or []
            record["rememberedLength"] = {"compliant": due is None, "reminderDue": due, "reminderShown": bool(due) and due in (record.get("warnings") or []),
                                          "wordLimitSent": [d.get("wordLimit") for d in destinations]}
            check(f"remembered length on the {name}: the writer was given the number", [d.get("wordLimit") for d in destinations] == [limit["max"]], sent=[d.get("wordLimit") for d in destinations])
            check(f"remembered length on the {name}: compliant, or the draft carries the measured count", record.get("status") == "completed" and (due is None or due in (record.get("warnings") or [])),
                  words=record.get("words"), compliant=due is None, reminderShown=record["rememberedLength"]["reminderShown"])
        other = draft("correction", "unrelated-platform-control", fixed, "personalized", destination=spec["unrelated"])
        check("accepted preference stays off the unrelated destination", other.get("status") == "completed" and other.get("preferencesUsed") == [], used=other.get("preferencesUsed"))
        if counted_rule:
            report["correction"]["countedRule"]["unrelatedDestination"] = other.get(counted_rule)
        neutral = draft("correction", "neutral-control", fixed, "neutral")
        check("neutral mode excludes the accepted preference", neutral.get("status") == "completed" and neutral.get("preferencesUsed") == [], used=neutral.get("preferencesUsed"))
        service().learning.update_version(service().repository, wid, OWNER, revision(), item_id, "paused")
        paused = draft("correction", "paused", fixed, "personalized")
        check("a paused preference leaves the next writer receipt", paused.get("status") == "completed" and paused.get("preferencesUsed") == [], used=paused.get("preferencesUsed"))
        service().learning.update_version(service().repository, wid, OWNER, revision(), item_id, "retired")
        stale = None
        if post.get("status") == "completed":
            try:
                service().ideas.apply(wid, OWNER, revision(), post["runId"], post["artifactHash"])
                stale = {"applied": True}
            except AlphaError as error:
                stale = {"applied": False, "httpStatus": error.status, "message": str(error)}
        check("a candidate drafted with the withdrawn preference is refused", bool(stale) and stale.get("httpStatus") == 409, stale=stale)
        box["service"] = fresh_service()
        retired = draft("correction", "retired-fresh-session", fixed, "personalized")
        check("a withdrawn preference stays out after a fresh session", retired.get("status") == "completed" and retired.get("preferencesUsed") == [], used=retired.get("preferencesUsed"))
        report["correction"]["voiceFileAfterRetire"] = voice_file()

    stage("voice", teach)
    stage("blind", blind)
    stage("examples", with_examples)
    stage("oneoff", one_off)
    stage("correction", correction)

    with connection() as db:
        report["database"] = {"runs": [{"id": r[0], "status": r[1], "model": r[2], "reasoning": r[3]} for r in db.execute(
            "SELECT id::text, status, model, reasoning FROM public.pr_agent_runs WHERE workspace_id=%s ORDER BY created_at", (wid,)).fetchall()],
            "durable": durable()}
    report["finishedAt"] = now()
    report["summary"] = {"checks": {v: sum(1 for c in report["checks"] if c["verdict"] == v) for v in ("PASS", "FAIL")},
                         "runs": {s: sum(1 for r in report["runs"] if r.get("status") == s) for s in sorted({r.get("status") for r in report["runs"]})},
                         "errors": len(report["errors"])}
    report["status"] = "COMPLETED_NO_VOICE_VERDICT" if not report["errors"] else "COMPLETED_WITH_ERRORS"
    save()
    write_packet(report, config, out)
    print(json.dumps(report["summary"]))
    return 0 if not report["summary"]["checks"]["FAIL"] and not report["errors"] else 1


def write_packet(report, config, out):
    """The blind review packet (drafts unchanged, order randomised) and its key, kept in a separate file."""
    by_label = {r["label"]: r for r in report["runs"]}
    pairs = [(f"{key}: which sounds more like {config['voice']}?", by_label.get(f"{key}-neutral"), by_label.get(f"{key}-personalized"), "neutral", "personalized", key)
             for key in config.get("blindPairs", [])]
    for key in config.get("blindPairs", []) if config.get("examplesArm") else []:
        pairs.append((f"{key}: both are personalized. Which sounds more like {config['voice']}?", by_label.get(f"{key}-personalized"), by_label.get(f"{key}-personalized-examples"),
                      "personalized (style signals only)", "personalized + style examples", key))
    if "pre-accept-baseline" in by_label and "post-accept-same-brief" in by_label:
        pairs.append((f"Same brief, before and after one remembered correction: which do you prefer as {config['voice']}?", by_label["pre-accept-baseline"], by_label["post-accept-same-brief"],
                      "pre-correction", "post-correction", config["correction"]["fixedBrief"]))
    key_rows, lines = [], [f"# Blind review — {config['label']}", "", f"Target voice: {config['voice']}. Drafts are shown exactly as the writer returned them.",
                           "For each case choose **A / B / tie / neither**, then note factual errors, copied wording, unwanted claims, platform fit and edits needed.",
                           "An invented personal fact, attribution, event or outcome fails that case whatever the voice.", ""]
    for index, (question, first, second, first_name, second_name, brief_key) in enumerate(pairs, 1):
        if not first or not second or not first.get("text") or not second.get("text"):
            lines += [f"## Case {index} — not reviewable", "", f"One side did not complete ({(first or {}).get('status')} / {(second or {}).get('status')}). Recorded as NOT_RUN for judgement.", ""]
            key_rows.append({"case": index, "brief": brief_key, "reviewable": False})
            continue
        flip = secrets.randbelow(2) == 1
        a, b = (second, first) if flip else (first, second)
        brief = config["briefs"][brief_key]
        lines += [f"## Case {index} — {question}", "", f"Brief ({a['destination']['platform']}, {a['destination']['language']}): {brief['text']}", "", "### A", "", a["text"], "", "### B", "", b["text"], "",
                  "Choice (A / B / tie / neither): ____   Factual errors: ____   Edits needed: ____", ""]
        key_rows.append({"case": index, "brief": brief_key, "reviewable": True, "A": second_name if flip else first_name, "B": first_name if flip else second_name,
                         "runA": a["runId"], "runB": b["runId"], "textShaA": a["textSha256"], "textShaB": b["textSha256"]})
    (out / "blind-packet.md").write_text("\n".join(lines) + "\n")
    (out / "blind-key.json").write_text(json.dumps({"label": config["label"], "createdAt": now(), "note": "Keep away from the reviewer until the choices are recorded.", "cases": key_rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
