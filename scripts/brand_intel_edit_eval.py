"""Real-writer evaluation of one-click tone and polish edits against today's way of asking for a rewrite.

Runs the real hosted services on a disposable PostgreSQL cluster (its own port) and drives two product paths on the
same draft text, with the same writer route and the same requested tone:

- EDIT: the one-click edit (`DraftEdits.request`, brand intelligence spec 5.4).
- BASELINE: what exists today without it: a rework turn that carries the instruction as typed text, exactly what the
  agent's `draft_rewrite` tool sends (`material` + `materialRef`, no `edit` key).

The writer is the person's own signed-in CLI (`claude-code:*` or `codex:*`); no paid route can be picked up because
the gateway keys are removed from this process. Nothing is posted or published. For every output the script records
the text, whether it changed, the deterministic fidelity check (the same checker for both conditions), the duration,
and the run receipt. It never scores voice or preference: a person judges the blind packet it writes, whose answer
order is mixed so that answering one letter throughout cannot favour one condition.

    PYTHONPATH=src:tests python scripts/brand_intel_edit_eval.py --out <dir outside the repository> [--model claude-code:sonnet]

All texts are synthetic. Keep --out outside the repository.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from pwi_real_voice_eval import OWNER, OWNER_ID, PG, cluster, now, sha  # noqa: E402  (shared harness pieces)

DESTINATIONS = {"en": {"platform": "LinkedIn", "language": "en"},
                "zh-Hant-HK": {"platform": "Instagram", "language": "zh-Hant-HK"},
                "yue-Hant-HK": {"platform": "Threads", "language": "yue-Hant-HK"}}
# What a person types today to get the same change through a rework (the baseline's instruction).
TYPED = {"warm": "Make this warmer.", "professional": "Make this more professional.", "direct": "Make this more direct.",
         "playful": "Make this more playful.", "polish": "Polish the wording."}
# Fixture cases (tests/fixtures/editorial_cases.jsonl), chosen for meaning that is easy to lose under a tone change.
FIXTURE_CASES = [("en-negation", "warm"), ("en-hedge", "direct"), ("en-conditions", "playful"), ("en-commitment", "professional"),
                 ("en-already-good", "polish"), ("zh-hk-conditions", "warm"), ("yue-hedge", "professional"), ("mixed-negation", "direct")]
# Longer posts written for this evaluation (synthetic).
LONGER = [
    {"id": "long-en-workshop", "language": "en", "tone": "warm",
     "original": "Our spring songwriting workshop is back. It runs on Saturdays from 12 April, 10am to 1pm, at the Riverside "
                 "Studio. Places are limited to 12, and we might add a second group if demand is high. The fee is $180 for "
                 "six sessions. Register by 31 March."},
    {"id": "long-yue-recital", "language": "yue-Hant-HK", "tone": "playful",
     "original": "下個月 15 號喺上環有個細型演奏會，主題係 Chopin 嘅夜曲。位唔多，大概 40 個，先到先得。門票 $150，"
                 "學生 $100。我哋暫時未決定會唔會錄影，決定咗再話大家知。"},
    {"id": "long-zh-hk-notice", "language": "zh-Hant-HK", "tone": "professional",
     "original": "本中心將於2026年4月1日起調整開放時間，平日改為上午九時至晚上八時，週末維持不變。如當日懸掛八號或以上"
                 "風球，中心將暫停開放。查詢請致電 2345 6789。"},
]
# Answer order: a fixed mix, so answering one letter throughout splits evenly between the conditions.
ORDER = "ABBABAABBAAB"


def cases():
    rows = {json.loads(line)["id"]: json.loads(line) for line in (ROOT / "tests/fixtures/editorial_cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    chosen = [{"id": case_id, "language": rows[case_id]["language"], "tone": tone, "original": rows[case_id]["original"],
               "fixture": True, "category": rows[case_id]["category"]} for case_id, tone in FIXTURE_CASES]
    return chosen + [{**item, "fixture": False, "category": "longer post"} for item in LONGER]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="claude-code:sonnet")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BRAND_INTEL_EVAL_PG_PORT", "55561")))
    parser.add_argument("--only", default="", help="comma-separated case ids (default: all)")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if str(out).startswith(str(ROOT)):
        parser.error("--out must be outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    tmp, data = cluster(args.port)
    try:
        return run(args, out)
    finally:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


def run(args, out):
    os.environ["POSTRIFF_RESEARCH"] = "0"
    os.environ["RAFII_CREATION_ALL_PLATFORMS_ENABLED"] = "1"
    os.environ["RAFII_CREATION_PROJECTION_ENABLED"] = ""
    for key in ("AI_GATEWAY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(key, None)
    import psycopg
    from postriff_alpha.domain import AlphaError
    from postriff_phase2 import creation_capabilities, draft_edits
    from postriff_phase2.coworker import flags
    from postriff_phase2.hosted import HostedWorkspaceService
    from consumer_fixtures import approve_budgets

    flags.attach(None)
    creation_capabilities._CACHE.clear()
    dsn = f"host=127.0.0.1 port={args.port} dbname=postgres"
    started = time.time()

    def connection():
        return psycopg.connect(dsn, client_encoding="utf8")

    def verify(token):
        if token != OWNER:
            raise AlphaError("Verified session required.", 401)
        return OWNER_ID

    verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
    verify.auth_time = lambda token, principal: started

    with connection() as db:
        wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (OWNER_ID,)).fetchone()[0])
        db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
        db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (OWNER_ID,))
    service = HostedWorkspaceService(connection, verify)
    service.bootstrap(OWNER, "studio")
    approve_budgets(connection, wid)
    ideas = service.ideas
    edits = draft_edits.DraftEdits(service)   # the real writer route; the dev harness's fixture writer is not used here
    service.draft_edits = edits

    def revision():
        return service.get(wid, OWNER)["revision"]

    def variant(variant_id):
        return next(v for v in service.get(wid, OWNER)["state"]["variants"] if v["id"] == variant_id)

    report = {"schema": "rafii.brand-intel-edit-eval.v1", "model": args.model, "startedAt": now(),
              "sourceSha": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
              "sourceDirty": bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "src", "skills"], capture_output=True, text=True).stdout.strip()),
              "environment": "LOCAL real hosted services + disposable PostgreSQL; writer = the person's signed-in CLI; no paid route; web research off",
              "conditions": {"EDIT": "DraftEdits.request (one-click edit)", "BASELINE": "rework turn with the typed instruction (draft_rewrite's request)"},
              "limitations": ["Small pilot: these cases, one generation per cell. It cannot establish a general improvement rate.",
                              "The fidelity check is deterministic and lexical; it can miss a paraphrased change of meaning and can flag a harmless one.",
                              "No voice profile is active (neutral voice) so the comparison isolates the editing instruction, not personalization.",
                              "This file records outputs; it contains no preference verdict. A person judges the blind packet."],
              "runs": [], "errors": []}
    catalog = {m["id"]: m for m in ideas.model_catalog()["models"]}
    if not (catalog.get(args.model) or {}).get("qualified"):
        report["status"] = "BLOCKED"
        report["errors"].append({"stage": "route", "error": f"{args.model} is not an available signed-in writer here",
                                 "available": sorted(k for k, v in catalog.items() if v.get("qualified"))})
        (out / "raw-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        print(json.dumps({"status": "BLOCKED", "reason": report["errors"][0]["error"]}))
        return 2

    def seed(case):
        """A draft written by the template writer, then reworded by its author: the case's text at revision 2."""
        destination = DESTINATIONS[case["language"]]
        quick = ideas.quick_start(wid, OWNER, revision(), {"text": "Studio news", "ownContent": True, "confirmUse": True,
                                                          "model": "deterministic-preview", "destinations": [destination]})
        # separate=True: always a new draft; without it a second case in the same platform and language would become a
        # proposed update on the first case's draft.
        ideas.apply(wid, OWNER, revision(), quick["runId"], quick["artifactHash"], separate=True)
        vid = next(v["id"] for v in service.get(wid, OWNER)["state"]["variants"] if (v.get("provenance") or {}).get("runId") == quick["runId"])
        service.mutate(wid, OWNER, revision(), "variant_edit", {"variantId": vid, "variantRevision": 1, "text": case["original"]})
        return vid, destination

    only = {item for item in args.only.split(",") if item}
    brand_terms = ()
    for case in cases():
        if only and case["id"] not in only:
            continue
        mode, tone = ("polish", None) if case["tone"] == "polish" else ("tone", case["tone"])
        row = {"case": case["id"], "language": case["language"], "category": case["category"], "fixture": case["fixture"],
               "requested": case["tone"], "original": case["original"], "originalSha256": sha(case["original"]), "outputs": {}}
        # EDIT: the one-click edit on its own draft.
        try:
            vid, destination = seed(case)
            current = variant(vid)
            payload = {"variantRevision": current["revision"], "mode": mode, "model": args.model, "voiceMode": "neutral",
                       "idempotencyKey": "eval-edit-" + uuid.uuid4().hex[:16], "expectedRevision": revision()}
            if tone:
                payload["tone"] = tone
            if mode == "polish":
                payload["depth"] = "light"
            begun = time.monotonic()
            answer = edits.request(wid, OWNER, vid, payload)
            took = round(time.monotonic() - begun, 1)
            info = answer.get("edit") or {}
            proposed = (variant(vid).get("proposedUpdate") or {}).get("text")
            text = proposed if info.get("status") == "candidate" and proposed else case["original"]
            row["outputs"]["EDIT"] = {"status": info.get("status"), "text": text, "changed": text != case["original"], "seconds": took,
                                      "fidelity": draft_edits.fidelity(case["original"], text, brand_terms, case["language"]),
                                      "reportedFidelity": info.get("fidelity"), "runId": info.get("runId"), "usage": info.get("usage")}
        except Exception as error:   # recorded, never hidden; the other condition still runs
            row["outputs"]["EDIT"] = {"status": "error", "error": f"{type(error).__name__}: {error}"}
            report["errors"].append({"case": case["id"], "condition": "EDIT", "error": f"{type(error).__name__}: {error}"})
        # BASELINE: today's rework with the typed instruction, on a separate draft with the same text.
        try:
            vid, destination = seed(case)
            conversation = ideas.create_conversation(wid, OWNER, "Baseline rework")["conversationId"]
            instruction = TYPED[case["tone"]]
            target = {**destination}
            if variant(vid).get("channelId"):
                target["channelId"] = variant(vid)["channelId"]
            begun = time.monotonic()
            result = ideas.turn(wid, OWNER, conversation, {"text": "", "intentText": instruction, "idea": instruction, "material": case["original"],
                                                           "materialRef": {"type": "draft", "id": vid, "title": f"{destination['platform']} draft"},
                                                           "destinations": [target], "model": args.model, "voiceMode": "neutral",
                                                           "idempotencyKey": "eval-base-" + uuid.uuid4().hex[:16], "expectedRevision": revision()})
            run_id = result["runId"]
            for _ in range(600):   # a CLI run may finish after the request returns
                state = ideas.events(wid, OWNER, run_id)
                if state["status"] in ("completed", "failed", "cancelled", "applied"):
                    break
                time.sleep(1)
            took = round(time.monotonic() - begun, 1)
            if state["status"] != "completed":
                raise RuntimeError(f"baseline run ended {state['status']}")
            ideas.apply(wid, OWNER, revision(), run_id, state["artifactHash"])
            after = variant(vid)
            text = (after.get("proposedUpdate") or {}).get("text") or next(
                (v.get("text") for v in service.get(wid, OWNER)["state"]["variants"] if (v.get("provenance") or {}).get("runId") == run_id), None) or case["original"]
            row["outputs"]["BASELINE"] = {"status": "candidate", "text": text, "changed": text != case["original"], "seconds": took,
                                          "fidelity": draft_edits.fidelity(case["original"], text, brand_terms, case["language"]),
                                          "runId": run_id, "usage": state.get("usage")}
        except Exception as error:
            row["outputs"]["BASELINE"] = {"status": "error", "error": f"{type(error).__name__}: {error}"}
            report["errors"].append({"case": case["id"], "condition": "BASELINE", "error": f"{type(error).__name__}: {error}"})
        report["runs"].append(row)
        (out / "raw-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
        print(json.dumps({"case": case["id"], "edit": (row["outputs"].get("EDIT") or {}).get("status"), "baseline": (row["outputs"].get("BASELINE") or {}).get("status")}), flush=True)

    report["finishedAt"] = now()
    report["status"] = "COMPLETE" if not report["errors"] else "PARTIAL"
    report["summary"] = summarise(report["runs"])
    (out / "raw-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    write_packet(report, out)
    print(json.dumps({"status": report["status"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["status"] == "COMPLETE" else 1


def violations(output):
    fidelity = (output or {}).get("fidelity") or {}
    return [item.get("code") for item in fidelity.get("violations") or []]


def summarise(runs):
    summary = {}
    for condition in ("EDIT", "BASELINE"):
        outputs = [r["outputs"].get(condition) or {} for r in runs]
        done = [o for o in outputs if o.get("status") in ("candidate", "no_change")]
        summary[condition] = {"runs": len(outputs), "completed": len(done), "errors": sum(1 for o in outputs if o.get("status") == "error"),
                              "changed": sum(1 for o in done if o.get("changed")), "unchanged": sum(1 for o in done if not o.get("changed")),
                              "withFidelityWarnings": sum(1 for o in done if violations(o)),
                              "fidelityCodes": sorted({code for o in done for code in violations(o)}),
                              "medianSeconds": sorted(o["seconds"] for o in done)[len(done) // 2] if done else None}
    control = next((r for r in runs if r["case"] == "en-already-good"), None)
    if control:
        summary["alreadyGoodControl"] = {condition: (control["outputs"].get(condition) or {}).get("changed") for condition in ("EDIT", "BASELINE")}
    return summary


def write_packet(report, out):
    """A short blind packet: original, requested tone, version A and B. The key is written separately."""
    lines = ["# Blind packet: changing a draft's tone", "",
             "For each item: the original text, the tone that was asked for, and two rewritten versions (A and B).",
             "Answer two questions per item. There is no right letter; the order was mixed in advance.", "",
             "1. Which version would you post? (A, B, or same)",
             "2. Did either version change a fact, a date, a number, a condition, or how certain or committed the text is? (A, B, both, neither)", ""]
    key = []
    shown = [r for r in report["runs"] if all((r["outputs"].get(c) or {}).get("status") in ("candidate", "no_change") for c in ("EDIT", "BASELINE"))]
    for index, row in enumerate(shown):
        first = "EDIT" if ORDER[index % len(ORDER)] == "A" else "BASELINE"
        second = "BASELINE" if first == "EDIT" else "EDIT"
        lines += [f"## Item {index + 1}", "", f"Requested: {row['requested']}", "", "Original:", "", "> " + row["original"].replace("\n", "\n> "), "",
                  "Version A:", "", "> " + row["outputs"][first]["text"].replace("\n", "\n> "), "",
                  "Version B:", "", "> " + row["outputs"][second]["text"].replace("\n", "\n> "), "",
                  "Answers: 1. ___  2. ___", ""]
        key.append({"item": index + 1, "case": row["case"], "A": first, "B": second})
    (out / "blind-packet.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "blind-key.json").write_text(json.dumps({"createdAt": now(), "order": ORDER, "note": "Keep away from the reviewer until the answers are recorded.", "items": key}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
