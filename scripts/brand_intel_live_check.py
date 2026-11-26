"""Live check of brand intelligence on Rafii's managed model route (Vercel AI Gateway): real, paid model calls.

Runs the real hosted services on a disposable PostgreSQL cluster (its own port) and drives, with a gateway credential
from this process's environment (AI_GATEWAY_API_KEY, else VERCEL_OIDC_TOKEN from `vercel env pull`):

1. an export upload of a synthetic studio's 30 posts (no provider is contacted);
2. one corpus analysis per model in --models: quote, owner approval, then cron ticks until it ends;
3. one-click tone edits on two synthetic drafts with each model in --edit-models.

The corpus carries nine style traits on purpose (see TRAITS), so a reader can count which ones each model's
observations find and whether any observation repeats a fact. Spend is bounded three ways: POSTRIFF_BUDGET_POLICY
(default launch-2026-09-24: US$1 a call), the quote each analysis is started with, and --max-usd for the whole run,
checked against the quotes before any call is sent. The credential is never printed or written.

    PYTHONPATH=src:tests python scripts/brand_intel_live_check.py --out <dir outside the repository>

Every text is synthetic. Keep --out outside the repository.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from pwi_real_voice_eval import OWNER, OWNER_ID, PG, cluster, now  # noqa: E402  (shared harness pieces)

MODELS = ("openai/gpt-6-sol", "openai/gpt-6-astra", "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5", "anthropic/claude-fable-5.2")
# USD per million input / output tokens on the gateway catalog (2026-11-25), used for quotes and settlement.
PRICES = {"openai/gpt-6-sol": (2.0, 10.0), "openai/gpt-6-astra": (10.0, 50.0), "anthropic/claude-sonnet-5.5": (2.0, 10.0),
          "anthropic/claude-opus-5.5": (4.0, 20.0), "anthropic/claude-fable-5.2": (8.0, 40.0),
          "anthropic/claude-haiku-5.5": (0.1, 0.5), "openai/gpt-6-luna": (0.1, 0.5), "openai/gpt-6.2-astra": (8.0, 40.0),
          "google/gemini-3.5-flash-lite": (0.3, 2.5), "google/gemini-3.8-flash": (0.75, 3.75), "google/gemini-4-neon": (3.0, 15.0),
          "deepseek/deepseek-v4-flash": (0.13, 0.26), "deepseek/deepseek-v4-pro": (1.32, 3.96),
          "alibaba/qwen3.8-flash": (0.15, 0.47), "alibaba/qwen3.8-max": (2.0, 6.0), "alibaba/qwen3.8-max-prime": (4.0, 12.0),
          "meta/llama-4-scout": (0.17, 0.66), "meta/muse-spark-1.2": (1.25, 4.25),
          "mistral/mistral-small": (0.15, 0.6), "mistral/mistral-medium-3.5": (1.5, 7.5)}
# A plain keyword rule per planted trait, so many models are scored the same way (a reader still checks the text).
TRAIT_RULES = {
    "T1 code-mixing": lambda s: "english" in s and ("cantonese" in s or "chinese" in s) and any(w in s for w in ("mix", "switch", "insert", "intersperse", "weave", "drop")),
    "T2 closing question": lambda s: "question" in s and any(w in s for w in ("end", "clos", "final")),
    "T3 piano emoji": lambda s: "emoji" in s,
    "T4 sign-off": lambda s: any(w in s for w in ("sign-off", "sign off", "signoff", "signature", "studio name", "organisation's name", "organization's name")),
    "T5 numbered tips": lambda s: "number" in s and any(w in s for w in ("list", "step", "tip")),
    "T6 event format": lambda s: ("middle dot" in s or "·" in s or "separated by" in s or ("date" in s and "time" in s)) and any(w in s for w in ("event", "detail", "announcement", "logistic")),
    "T7 no hashtags": lambda s: "hashtag" in s,
    "T8 studio we": lambda s: "'we'" in s or "“we”" in s or "we/" in s or "first-person plural" in s or "first person plural" in s or "collective" in s or "plural" in s,
    "T9 encouragement": lambda s: any(w in s for w in ("encourag", "reassur", "supportive")),
}


def traits_found(observations):
    """Which planted traits the observations name, by TRAIT_RULES over each observation's lowercased text."""
    texts = [str((item or {}).get("observation") or "").lower() for item in observations or []]
    return sorted(trait for trait, rule in TRAIT_RULES.items() if any(rule(text) for text in texts))
CONSENT = {"ownership": "mine", "voiceScope": "brand", "confirmed": True}
TRAITS = {
    "T1 code-mixing": "Cantonese posts carry English music words (scale, recital, pedal, slot, workshop)",
    "T2 closing question": "12 of 30 posts end by asking readers a question",
    "T3 piano emoji": "🎹 in 12 of 30 posts, the only emoji",
    "T4 sign-off": "announcements end with a dash sign-off line (8 of 30)",
    "T5 numbered tips": "practice tips as a numbered 1-2-3 list (4 posts)",
    "T6 event format": "events as one line: date · time · place · price (4 posts)",
    "T7 no hashtags": "no post uses a hashtag",
    "T8 studio we": "speaks as 'we / 我哋', never 'I'",
    "T9 encouragement": "warm, effort-over-talent encouragement (slow practice, small wins, never too late)",
}
POSTS = [
    "🎹 Slow practice is still practice. Ten focused minutes beat an hour of rushing.\n\nWhat's one bar you'll play slowly today?",
    "Three things to try before your next lesson:\n1. Clap the rhythm first\n2. Hands separately, then together\n3. Stop at the mistake, not the end\n\nWhich one helps you most?",
    "Spring recital sign-ups are open 🎹\nSat 12 Apr · 3pm · Harbour Keys Studio · free for students\nFamilies welcome!\n— Harbour Keys",
    "We love hearing about the small wins. A steady left hand, a cleaner pedal, a first full page. Keep going.\n\nWhat was your small win this week?",
    "Our practice room is open late on Thursdays this term. Bring your book, we'll bring the tea.\n— Harbour Keys",
    "🎹 Mistakes are information, not failure. Mark the spot, play it three times slowly, then move on.",
    "Adult beginners: it is never too late. We have evening slots for grown-ups who always wanted to play.\n\nWhat made you want to start?",
    "Theory corner: a scale is just a pattern of steps. Once you hear the pattern, you can play it from any note 🎹",
    "Exam season tip:\n1. Run the piece once, no stopping\n2. Fix only the two worst spots\n3. Run it again\n\nSmall circles, not big ones.",
    "Workshop: Playing for joy, not perfection\nSun 27 Apr · 10am · Studio B · $120 for three sessions\n— Harbour Keys",
    "Parents often ask how much practice is enough. Our answer: a little, most days. Consistency beats marathons 🎹",
    "Thank you to every family who came to Saturday's open house. The room was full of music and biscuits.\n\nSee you at the next one?",
    "🎹 今個星期試吓慢慢練個 scale，唔使急，手指自然會記得。\n\n你哋最近練緊邊首曲？",
    "練琴三個小貼士：\n1. 先拍節奏\n2. 左右手分開練\n3. 錯咗就停喺嗰度，唔好由頭再嚟\n\n邊個最幫到你？",
    "學生 recital 報名開始喇 🎹\n4月12日（六）· 下午3點 · Harbour Keys Studio · 學生免費\n歡迎屋企人一齊嚟！\n— Harbour Keys",
    "我哋最鍾意聽大家嘅小進步：左手穩咗、pedal 清楚咗、第一次彈晒成頁。繼續加油。\n\n你今個禮拜有咩小進步？",
    "今個學期星期四練琴室開到夜啲，帶埋琴譜嚟，我哋準備咗茶。\n— Harbour Keys",
    "彈錯唔係失敗，係提示你邊度要再練。圈住嗰度，慢慢彈三次，就可以繼續 🎹",
    "成年人學琴一啲都唔遲。我哋有夜晚嘅 slot，專登俾一直想學琴嘅大人。\n\n你當初點解想學琴？",
    "考試前小提醒：\n1. 由頭到尾彈一次，唔好停\n2. 淨係執最差嘅兩個位\n3. 再彈一次\n\n細圈練習，唔好兜大圈。",
    "家長成日問練幾耐先夠。我哋嘅答案：每日少少，好過一次過練好耐 🎹",
    "多謝每一個嚟咗星期六 open house 嘅家庭，成間房都係音樂同餅乾。\n\n下次見？",
    "Workshop：為開心而彈，唔係為完美\n4月27日（日）· 上午10點 · Studio B · 三堂 $120\n— Harbour Keys",
    "Theory 小知識：scale 其實係一組固定嘅步距，聽得出個 pattern，就可以由任何一粒音開始彈 🎹",
    "今日有個學生終於彈到 Für Elise 中段，好開心！Effort always shows 🎹\n\n你哋有冇一首一直想彈嘅曲？",
    "Practice 唔使長，但要專心。Ten minutes, phone away, 慢慢嚟。",
    "新學期 timetable 出咗，weekday afternoon 仲有少量位。\n— Harbour Keys",
    "We tried a new warm-up today: 五指慢慢爬上爬落，再加 staccato。學生話好好玩！\n\nWhat's your favourite warm-up?",
    "Recital 前一晚最緊要瞓得好。Sleep is part of practice 🎹",
    "多謝大家支持我哋嘅 charity concert，一共籌到 $8,000 俾社區音樂班。\n— Harbour Keys",
]
EDITS = [
    {"id": "edit-en-warm", "language": "en", "platform": "LinkedIn", "tone": "warm",
     "text": "The studio will be closed on 24 December. Lessons resume on 2 January. Fees for January are due by 31 December."},
    {"id": "edit-yue-professional", "language": "yue-Hant-HK", "platform": "Threads", "tone": "professional",
     "text": "下個月 recital 嘅位已經滿晒，唔好意思！想排 waiting list 就 DM 我哋，有位會即刻通知你。"},
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--models", default=",".join(MODELS))
    parser.add_argument("--edit-models", default="anthropic/claude-sonnet-5.5", help="comma list; every edit case runs on each ('' for none)")
    parser.add_argument("--writing-batches", type=int, default=100, help="the plan allowance the disposable workspace gets")
    parser.add_argument("--providers", default="", help='JSON {model: [gateway hosts]} for models their maker does not serve (POSTRIFF_MODEL_PROVIDERS); '
                                                         'only hosts the gateway lists with zero data retention and no training')
    parser.add_argument("--max-usd", type=float, default=3.0, help="refuse to start when the quotes add up to more")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BRAND_INTEL_LIVE_PG_PORT", "55571")))
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if str(out).startswith(str(ROOT)):
        parser.error("--out must be outside the repository")
    key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN")
    if not key:
        print(json.dumps({"status": "BLOCKED", "reason": "no gateway credential in the environment"}))
        return 2
    out.mkdir(parents=True, exist_ok=True)
    tmp, data = cluster(args.port)
    try:
        return run(args, out, key)
    finally:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)


def run(args, out, key):
    os.environ["POSTRIFF_RESEARCH"] = "0"
    os.environ.setdefault("POSTRIFF_BUDGET_POLICY", "launch-2026-09-24")
    import psycopg
    from postriff_alpha.domain import AlphaError
    from postriff_phase2 import draft_edits, voice_import as V
    from postriff_phase2.coworker import flags
    from postriff_phase2.hosted import HostedWorkspaceService
    from postriff_phase2.model_runtime import ServerModelRuntime
    from postriff_phase2.oauth import CredentialVault
    from postriff_phase2.voice_corpus import VoiceCorpusAnalysis

    flags.attach(None)
    dsn = f"host=127.0.0.1 port={args.port} dbname=postgres"
    models = [m for m in args.models.split(",") if m]
    edit_models = [m for m in args.edit_models.split(",") if m]
    selectable = sorted(set(models) | set(edit_models))
    unknown = [m for m in selectable if m not in PRICES]
    if unknown:
        raise SystemExit(f"no price configured for {unknown}")

    def redact(text):
        return str(text).replace(key, "<credential>")

    hosts = json.loads(args.providers) if args.providers else None

    def runtime(model):
        return ServerModelRuntime(key, model=model, models=selectable, prices=PRICES, allowed_providers=hosts)

    def connection():
        return psycopg.connect(dsn, client_encoding="utf8")

    started = time.time()

    def verify(token):
        if token != OWNER:
            raise AlphaError("Verified session required.", 401)
        return OWNER_ID

    verify.session_id = lambda token, principal: f"session-{principal}-0123456789abcdef"
    verify.auth_time = lambda token, principal: started

    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute((ROOT / "migrations/postriff/140_voice_import.sql").read_text(encoding="utf-8"))
    with connection() as db:
        wid = str(db.execute("SELECT workspace_id FROM public.pr_memberships WHERE user_id=%s", (OWNER_ID,)).fetchone()[0])
        db.execute("UPDATE public.pr_workspaces SET state='{}'::jsonb WHERE id=%s", (wid,))
        db.execute("UPDATE public.pr_memberships SET status='active', role='owner' WHERE user_id=%s", (OWNER_ID,))
    service = HostedWorkspaceService(connection, verify, vault=CredentialVault(CredentialVault.generate_key()), ideas_runtime=runtime((edit_models or models)[0]))
    service.bootstrap(OWNER, "studio")
    # No budget is approved by hand: under POSTRIFF_BUDGET_POLICY the ledger creates and approves each budget with the
    # policy's caps when the first call is reserved, exactly as a deployment does. Every managed call also spends one
    # writing batch of the plan; the trial's 10 run out after two analyses, so the workspace gets a paid plan's 100.
    with connection() as db, db.cursor() as cur:
        service.ledger.ensure_entitlement(cur, wid, None)
        cur.execute("UPDATE public.pr_entitlements SET writing_batches_remaining=%s WHERE workspace_id=%s", (args.writing_batches, wid))

    report = {"schema": "rafii.brand-intel-live-check.v1", "startedAt": now(), "budgetPolicy": os.environ["POSTRIFF_BUDGET_POLICY"],
              "sourceSha": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
              "sourceDirty": bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "src", "skills", "migrations"],
                                                 capture_output=True, text=True).stdout.strip()),
              "environment": "LOCAL real hosted services + disposable PostgreSQL; managed route = Vercel AI Gateway (paid); all texts synthetic",
              "traits": TRAITS, "analyses": [], "edits": [], "errors": []}

    def save():
        (out / "raw-run.json").write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    # 1. The export upload.
    importer = V.mount(service, connection, {V.FLAG: "1", V.PROVIDERS_FLAG: "x"}, transport=None)
    upload = importer.request(wid, OWNER, {"route": "platform_export", "provider": "x", "accountKey": "export:harbour_keys_synthetic",
                                           "accountLabel": "Harbour Keys (synthetic)", "consent": CONSENT})["import"]
    first = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    items = [{"externalId": str(1800000000000000000 + n), "text": text, "kind": "original",
              "publishedAt": (first + timedelta(days=5 * n)).isoformat()} for n, text in enumerate(POSTS)]
    received = importer.items(wid, OWNER, upload["id"], {"items": items, "final": True, "seq": 1})["import"]
    report["import"] = {"status": received["status"], "counts": received["counts"]}
    save()
    print(json.dumps({"import": report["import"]}, ensure_ascii=False), flush=True)

    # 2. Quotes first: nothing is sent unless every quote together fits --max-usd.
    planned = []
    for model in models:
        analysis = VoiceCorpusAnalysis(service.repository, runtime(model), service.ledger, worker_id=f"live-{uuid.uuid4().hex[:8]}")
        quote = analysis.quote(wid, OWNER)
        planned.append((model, analysis, quote))
    quoted = sum(q["estimatedMicroUsd"] for _, _, q in planned) / 1e6
    report["quotedUsd"] = round(quoted, 4)
    report["quotes"] = [{"model": m, "eligible": q.get("eligible"), "batches": q.get("batches"), "calls": q.get("calls"),
                         "estimatedUsd": q["estimatedMicroUsd"] / 1e6} for m, _, q in planned]
    save()
    print(json.dumps({"quotes": report["quotes"], "totalUsd": report["quotedUsd"]}), flush=True)
    if quoted > args.max_usd:
        report["status"] = "REFUSED"
        report["errors"].append({"stage": "quote", "error": f"quotes add up to US${quoted:.2f}, over --max-usd {args.max_usd}"})
        save()
        return 3

    for model, analysis, quote in planned:
        row = {"model": model, "quotedUsd": quote["estimatedMicroUsd"] / 1e6}
        begun = time.monotonic()
        try:
            # Quotes hold for one five-minute window and the next; a long run asks again just before each start.
            fresh = analysis.quote(wid, OWNER)
            if fresh["estimatedMicroUsd"] > quote["estimatedMicroUsd"] * 1.05:
                raise RuntimeError(f"the price rose since the run was approved ({quote['estimatedMicroUsd']} → {fresh['estimatedMicroUsd']} micro-USD)")
            started_view = analysis.start(wid, OWNER, None, fresh["id"])["analysis"]
            analysis_id = started_view["id"]
            ticks = []
            for _ in range(60):
                ticks.append(analysis.tick(max_calls=2))
                with connection() as db:
                    status = db.execute("SELECT status FROM public.pr_voice_analyses WHERE id=%s", (analysis_id,)).fetchone()[0]
                if status not in ("queued", "running"):
                    break
            with connection() as db:
                status, observations, receipt, failure = db.execute(
                    "SELECT status, observations, receipt, failure_class FROM public.pr_voice_analyses WHERE id=%s", (analysis_id,)).fetchone()
                if status in ("queued", "running"):
                    # Held for a later retry (the product waits before trying again): recorded as such, then closed here so
                    # the next model's analysis of the same voice can start. Only this disposable database is touched.
                    row["heldForRetry"] = True
                    db.execute("UPDATE public.pr_voice_analyses SET status='cancelled' WHERE id=%s", (analysis_id,))
            usage = (receipt or {}).get("usage") or {}
            row.update({"status": status, "failureClass": failure, "seconds": round(time.monotonic() - begun, 1), "ticks": len(ticks),
                        "actualUsd": (usage.get("actualMicroUsd") or 0) / 1e6, "unknownUsd": (usage.get("unknownMicroUsd") or 0) / 1e6,
                        "dropped": (receipt or {}).get("dropped"), "calls": [{k: c.get(k) for k in ("stage", "status", "inputTokens", "outputTokens", "actualMicroUsd", "seconds")}
                                                                         for c in (receipt or {}).get("calls") or []],
                        "observations": observations, "traitsFound": traits_found(observations)})
        except Exception as error:   # recorded, never hidden; the next model still runs
            row.update({"status": "error", "error": redact(f"{type(error).__name__}: {error}"), "seconds": round(time.monotonic() - begun, 1)})
            report["errors"].append({"model": model, "stage": "analysis", "error": row["error"]})
        report["analyses"].append(row)
        save()
        print(json.dumps({k: row.get(k) for k in ("model", "status", "seconds", "actualUsd", "dropped", "failureClass", "heldForRetry")}
                         | {"observations": len(row.get("observations") or []), "traits": len(row.get("traitsFound") or [])}, ensure_ascii=False), flush=True)

    # 3. One-click tone edits on the managed route.
    edits = draft_edits.DraftEdits(service)
    service.draft_edits = edits
    ideas = service.ideas

    def revision():
        return service.get(wid, OWNER)["revision"]

    for case, edit_model in [(case, model) for model in edit_models for case in EDITS]:
        row = {"case": case["id"], "model": edit_model, "tone": case["tone"], "original": case["text"]}
        begun = time.monotonic()
        try:
            quick = ideas.quick_start(wid, OWNER, revision(), {"text": "Studio news", "ownContent": True, "confirmUse": True, "model": "deterministic-preview",
                                                              "destinations": [{"platform": case["platform"], "language": case["language"]}]})
            ideas.apply(wid, OWNER, revision(), quick["runId"], quick["artifactHash"], separate=True)
            vid = next(v["id"] for v in service.get(wid, OWNER)["state"]["variants"] if (v.get("provenance") or {}).get("runId") == quick["runId"])
            service.mutate(wid, OWNER, revision(), "variant_edit", {"variantId": vid, "variantRevision": 1, "text": case["text"]})
            current = next(v for v in service.get(wid, OWNER)["state"]["variants"] if v["id"] == vid)
            answer = edits.request(wid, OWNER, vid, {"variantRevision": current["revision"], "mode": "tone", "tone": case["tone"], "model": edit_model,
                                                     "voiceMode": "neutral", "idempotencyKey": "live-edit-" + uuid.uuid4().hex[:16], "expectedRevision": revision()})
            info = answer.get("edit") or {}
            proposed = (next(v for v in service.get(wid, OWNER)["state"]["variants"] if v["id"] == vid).get("proposedUpdate") or {}).get("text")
            text = proposed if info.get("status") == "candidate" and proposed else case["text"]
            row.update({"status": info.get("status"), "text": text, "changed": text != case["text"], "seconds": round(time.monotonic() - begun, 1),
                        "fidelity": draft_edits.fidelity(case["text"], text, (), case["language"]), "usage": info.get("usage")})
        except Exception as error:
            row.update({"status": "error", "error": redact(f"{type(error).__name__}: {error}"), "seconds": round(time.monotonic() - begun, 1)})
            report["errors"].append({"case": case["id"], "stage": "edit", "error": row["error"]})
        report["edits"].append(row)
        save()
        print(json.dumps({k: row.get(k) for k in ("case", "model", "status", "changed", "seconds")}, ensure_ascii=False), flush=True)

    report["editActualUsd"] = round(sum(((e.get("usage") or {}).get("actualMicroUsd") or 0) for e in report["edits"]) / 1e6, 6)
    report["finishedAt"] = now()
    report["status"] = "COMPLETE" if not report["errors"] else "PARTIAL"
    save()
    print(json.dumps({"status": report["status"], "quotedUsd": report["quotedUsd"], "analysisActualUsd": round(sum(a.get("actualUsd") or 0 for a in report["analyses"]), 4),
                      "errors": len(report["errors"])}), flush=True)
    return 0 if report["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    sys.exit(main())
