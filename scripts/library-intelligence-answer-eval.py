#!/usr/bin/env python3
"""Grounded-answer evaluation for Library intelligence (acceptance A032 grounding, A033 abstention). NOT RUN by default.

Runs the production grounding code (answers.build_prompt + answers.verify_claims) against a real LLM over the frozen
question set tests/fixtures/library_intelligence/retrieval/answer-questions.json and the frozen corpus
tests/fixtures/library_intelligence/eval/corpus.json (plus the set's extra/trap documents). Retrieval is deterministic and
in-memory inside each question's scope: answerable questions always include their supporting documents (oracle
retrieval) plus the highest-ranked distractors by answers.relevance, so this measures what the model does with the
passages it is given, not search quality (A026 is measured separately). Each question sends at most
answers.MAX_LLM_PASSAGES passages, including weaker ones, which makes abstention harder than in production.

Paid inference runs only when ALL of these hold:
  * RAFII_LIBRARY_PROVIDER_EVAL_AUTHORIZATION names James's explicit authorization (for example the chat message id);
  * --confirm-paid-inference is passed;
  * --budget-usd is given, greater than 0 and at most 10 (James authorized a capped US$10 evaluation);
  * the provider seam reports the LLM available (RAFII_LIBRARY_ENRICHMENT_ENABLED and the AI Gateway credential).
Otherwise it prints a BLOCKED receipt and exits 3 without contacting any provider. Before every call the guard checks
spent + estimate against the cap and stops (status STOPPED_AT_BUDGET) instead of crossing it; a provider's actual cost
is charged as reported, otherwise the larger of its estimate and ours, and unknown cost is charged at our estimate.

`--responses FILE` re-scores model replies captured in an earlier receipt (no provider call, no authorization).

Scoring (machine checks; A032 still needs the human review queue written next to the receipt):
  * answerable: not abstained, every kept claim verified (quotations found verbatim in cited passages, figures and
    links present), at least one expected key fact present, cited documents among the supporting ones;
  * unanswerable: abstained (or, where allowed, only quoting that the source withholds the fact);
  * trap: no forbidden string anywhere in the answer, abstained where expected, never a citation outside the scope.

Usage:
  scripts/library-intelligence-answer-eval.py --out evidence/answer-eval.json --budget-usd 10 --confirm-paid-inference
  scripts/library-intelligence-answer-eval.py --out evidence/answer-rescore.json --responses evidence/answer-eval.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

AUTH_ENV = "RAFII_LIBRARY_PROVIDER_EVAL_AUTHORIZATION"
MAX_BUDGET_USD = 10.0
QUESTIONS = ROOT / "tests/fixtures/library_intelligence/retrieval/answer-questions.json"
CORPUS = ROOT / "tests/fixtures/library_intelligence/eval/corpus.json"


class BudgetGuard:
    """Hard spending cap in USD micro-units. Never lets a call start that could cross the cap."""

    def __init__(self, cap_usd: float):
        self.cap_micro = int(round(float(cap_usd) * 1_000_000))
        self.spent_micro = 0
        self.calls = 0
        self.kinds: dict = {}

    def allows(self, estimate_micro: int) -> bool:
        return self.spent_micro + max(0, int(estimate_micro)) <= self.cap_micro

    def record(self, cost: dict | None, *, estimate: int):
        cost = cost or {}
        kind = cost.get("kind") or "unknown"
        reported = cost.get("usdMicro") if isinstance(cost.get("usdMicro"), int) else None
        if kind == "actual" and reported is not None:
            charge = reported
        elif reported is not None:
            charge = max(reported, int(estimate))
        else:
            charge = int(estimate)
        self.spent_micro += max(0, charge)
        self.calls += 1
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def receipt(self) -> dict:
        return {"capUsd": self.cap_micro / 1_000_000, "spentUsd": round(self.spent_micro / 1_000_000, 6), "calls": self.calls, "costKinds": self.kinds}


def authorization(environ, *, confirmed: bool, budget_usd, providers=None) -> dict:
    reasons = []
    reference = str(environ.get(AUTH_ENV) or "").strip()
    if not reference:
        reasons.append(f"{AUTH_ENV} is not set (James's explicit paid-inference authorization is required)")
    if not confirmed:
        reasons.append("--confirm-paid-inference was not passed")
    if not isinstance(budget_usd, (int, float)) or not 0 < float(budget_usd) <= MAX_BUDGET_USD:
        reasons.append(f"--budget-usd must be greater than 0 and at most {MAX_BUDGET_USD:g}")
    if providers is not None:
        status = providers.status()["llm"]
        if not status["available"]:
            reasons.append(f"LLM provider unavailable: {status['reason']}")
    return {"status": "AUTHORIZED", "reference": reference} if not reasons else {"status": "BLOCKED", "reasons": reasons}


def _key(doc_id: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"rli-answer-eval/{doc_id}").hex


def passages_for(question: dict, documents: dict) -> list[dict]:
    """Deterministic in-scope retrieval: supporting documents (if any) plus the best distractors by answers.relevance,
    ordered by relevance; one passage per (short) document."""
    from postriff_phase2.library_intelligence import answers, contracts as c, search
    scope = list(documents) if question["scope"] == "all" else [d for d in question["scope"] if d in documents]
    units = answers.units(question["question"])
    ranked = []
    for order, doc_id in enumerate(scope):
        doc = documents[doc_id]
        text = search.plain_text(doc["text"])
        ranked.append((-answers.relevance(units, text + " " + doc["title"]), order, doc_id, text))
    ranked.sort()
    supporting = [r for r in ranked if r[2] in set(question.get("supporting") or [])][:answers.MAX_LLM_PASSAGES]
    others = [r for r in ranked if r not in supporting][:answers.MAX_LLM_PASSAGES - len(supporting)]
    out = []
    for n, (score, _, doc_id, text) in enumerate(sorted(supporting + others), 1):
        key = _key(doc_id)
        out.append({"handle": f"P{n}", "docId": doc_id, "segmentId": _key("segment/" + doc_id), "assetRef": {"assetId": key, "versionId": key,
                    "sha256": hashlib.sha256(documents[doc_id]["text"].encode()).hexdigest()}, "displayTitle": documents[doc_id]["title"],
                    "locator": None, "text": text, "window": text[:answers.PASSAGE_CHARS], "quoteHash": c.quote_hash(documents[doc_id]["text"]),
                    "relevance": -score, "semantic": False})
    return out


def score(question: dict, passages: list[dict], claims: list[dict], dropped: int, reply) -> dict:
    from postriff_phase2.library_intelligence import answers, textnorm
    by_key = {p["assetRef"]["assetId"]: p["docId"] for p in passages}
    cited = sorted({by_key.get(r["assetRef"]["assetId"], "?") for cl in claims for r in cl["sourceRefs"]})
    blob = json.dumps({"claims": claims, "reply": reply}, ensure_ascii=False)
    shown = textnorm.fold(" ".join([cl["text"] for cl in claims] + [r["excerpt"] for cl in claims for r in cl["sourceRefs"]]))
    abstained = not claims
    out = {"id": question["id"], "type": question["type"], "abstained": abstained, "claims": len(claims), "droppedClaims": dropped, "citedDocuments": cited,
           "gateWouldCallLlm": any(p["relevance"] >= answers.RELEVANCE for p in passages)}
    scope = None if question["scope"] == "all" else set(question["scope"])
    out["outOfScopeCitation"] = bool(scope is not None and set(cited) - scope)
    if question.get("forbid"):
        out["forbiddenSeen"] = [f for f in question["forbid"] if f.casefold() in blob.casefold()]
    if question["type"] == "answerable":
        out["keyFact"] = any(textnorm.fold(e) in shown for e in question.get("expect", []))
        out["citedSupporting"] = bool(set(cited) & set(question.get("supporting", [])))
        out["conflictShown"] = any(cl["support"] == "conflicting" for cl in claims)
        out["correct"] = (not abstained and out["keyFact"] and out["citedSupporting"] and not out["outOfScopeCitation"]
                          and (out["conflictShown"] or not question.get("expectConflict")))
    elif question["type"] == "unanswerable":
        quoted_ok = bool(question.get("acceptIfQuotes")) and claims and all(
            any(textnorm.fold(q) in textnorm.fold(r["excerpt"]) for q in question["acceptIfQuotes"]) for cl in claims for r in cl["sourceRefs"])
        out["correct"] = abstained or bool(quoted_ok)
    else:
        out["correct"] = (not out.get("forbiddenSeen") and not out["outOfScopeCitation"] and (abstained or not question.get("expectAbstain")))
    return out


def summarize(results: list[dict]) -> dict:
    answerable = [r for r in results if r["type"] == "answerable"]
    guarded = [r for r in results if r["type"] != "answerable"]
    kept = sum(r["claims"] for r in answerable)
    proposed = kept + sum(r["droppedClaims"] for r in answerable)
    return {
        "questions": len(results),
        "A032": {"answerable": len(answerable), "answeredCorrectly": sum(r["correct"] for r in answerable), "keptClaims": kept, "proposedClaims": proposed,
                 "machineVerifiedClaimRate": round(kept / proposed, 4) if proposed else None,
                 "note": "Kept claims passed verbatim-quote and figure/link checks; the >=95% target needs the human review queue, not only this rate."},
        "A033": {"cases": len(guarded), "correct": sum(r["correct"] for r in guarded),
                 "failures": [r["id"] for r in guarded if not r["correct"]], "forbiddenSeen": sum(bool(r.get("forbiddenSeen")) for r in guarded)},
    }


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--questions", default=str(QUESTIONS))
    parser.add_argument("--corpus", default=str(CORPUS))
    parser.add_argument("--budget-usd", type=float)
    parser.add_argument("--confirm-paid-inference", action="store_true")
    parser.add_argument("--responses", help="re-score replies captured in an earlier receipt; no provider call")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    from postriff_phase2.library_intelligence import answers
    from postriff_phase2.library_intelligence.providers import Providers
    qset = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    documents = {d["id"]: d for d in corpus["documents"] + qset.get("extraDocuments", [])}
    questions = qset["questions"][: args.limit or None]
    receipt = {"candidateSha": _sha(), "questionSet": qset["version"], "corpus": corpus["version"], "promptVersion": answers.PROMPT_VERSION,
               "startedAt": time.time(), "results": [], "replies": {}, "errors": []}
    if args.responses:
        captured = json.loads(Path(args.responses).read_text(encoding="utf-8")).get("replies", {})
        receipt.update(execution="offline-replies")
        prov, guard = None, None
    else:
        prov = Providers()
        gate = authorization(os.environ, confirmed=args.confirm_paid_inference, budget_usd=args.budget_usd, providers=prov)
        if gate["status"] != "AUTHORIZED":
            print(json.dumps({**gate, "candidateSha": receipt["candidateSha"], "execution": "not-run"}, indent=2))
            return 3
        guard = BudgetGuard(args.budget_usd)
        receipt.update(execution="real-provider", authorization=gate["reference"], processor={"model": prov.model("llm")})
        captured = {}
    review = []
    for question in questions:
        passages = passages_for(question, documents)
        system, user = answers.build_prompt(question["question"], passages)
        if prov is not None:
            estimate = prov.estimate("llm", units=math.ceil((len(system) + len(user)) / 3) + answers.LLM_MAX_TOKENS)
            if not guard.allows(estimate):
                receipt["status"] = "STOPPED_AT_BUDGET"
                break
            try:
                result = prov.complete_json(system, user, max_tokens=answers.LLM_MAX_TOKENS)
            except Exception as error:  # noqa: BLE001 - every failure is recorded and charged at the estimate
                guard.record(None, estimate=estimate)
                receipt["errors"].append({"question": question["id"], "error": str(error)[:300], "code": getattr(error, "code", None)})
                continue
            guard.record(result.cost, estimate=estimate)
            reply = result.value
        else:
            reply = captured.get(question["id"])
            if reply is None:
                receipt["errors"].append({"question": question["id"], "error": "no captured reply"})
                continue
        receipt["replies"][question["id"]] = reply
        claims, dropped = answers.verify_claims(reply, passages)
        result_row = score(question, passages, claims, dropped, reply)
        receipt["results"].append(result_row)
        for claim in claims:
            review.append({"question": question["id"], "claim": claim["text"], "support": claim["support"],
                           "quotations": [{"document": next(p["docId"] for p in passages if p["assetRef"]["assetId"] == r["assetRef"]["assetId"]),
                                           "excerpt": r["excerpt"]} for r in claim["sourceRefs"]],
                           "humanSupported": None, "reviewer": None})
    receipt.setdefault("status", "complete")
    receipt["budget"] = guard.receipt() if guard else None
    receipt["summary"] = summarize(receipt["results"])
    receipt["finishedAt"] = time.time()
    out = Path(args.out)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    out.with_name(out.stem + "-review.json").write_text(json.dumps({"instructions": "Mark humanSupported true/false for each claim against its quotations.",
                                                                      "claims": review}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"execution": receipt["execution"], "status": receipt["status"], "budget": receipt["budget"], "summary": receipt["summary"],
                      "errors": len(receipt["errors"])}, ensure_ascii=False, indent=2))
    return 1 if receipt["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
