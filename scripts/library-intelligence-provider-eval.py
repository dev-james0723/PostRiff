#!/usr/bin/env python3
"""Real-provider transcription evaluation for Library intelligence (acceptance A017, A018). NOT RUN by default.

A017 needs at least one authorized real-provider transcription with timestamped evidence; A018 needs labelled
Cantonese / Traditional Chinese / English / code-switched clips scored per language and per segment, with errors,
processor identity and whether the expected retrieval moments are usable. Mocks never satisfy either case.

Paid inference runs only when ALL of these hold:
  * RAFII_LIBRARY_PROVIDER_EVAL_AUTHORIZATION names James's explicit authorization (for example the chat message id);
  * --confirm-paid-inference is passed;
  * the provider seam reports ASR available (RAFII_LIBRARY_ENRICHMENT_ENABLED, RAFII_LIBRARY_ASR_ENABLED, OPENAI_API_KEY).
Otherwise the script prints a BLOCKED receipt and exits 3 without contacting any provider. This is an operator
evaluation outside any workspace, so there is no workspace budget reservation; the receipt records provider cost
exactly as the adapter reports it (actual, estimated or unknown).

`--hypotheses FILE` re-scores transcripts captured earlier (no provider call, no authorization needed).

Manifest (JSON): {"clips": [{"id", "path", "mime", "segments": [{"startMs", "endMs", "language", "text"}],
                             "queries": [{"text", "startMs", "endMs"}]}]}
Clip paths are relative to the manifest. Use only clips James has permission to process; never commit them.

Usage:
  scripts/library-intelligence-provider-eval.py --manifest eval/asr/manifest.json --out evidence/asr-eval.json --confirm-paid-inference
  scripts/library-intelligence-provider-eval.py --manifest eval/asr/manifest.json --hypotheses evidence/asr-hyp.json --out evidence/asr-rescore.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

AUTH_ENV = "RAFII_LIBRARY_PROVIDER_EVAL_AUTHORIZATION"
CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]")


# --- metrics (pure) ----------------------------------------------------------------------------------------------------------
def _distance(a: list, b: list) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def _chars(text: str, *, fold: bool = False) -> list[str]:
    text = unicodedata.normalize("NFKC", text or "").casefold()
    if fold:
        from postriff_phase2.library_intelligence import textnorm
        text = textnorm.fold(text)
    return [ch for ch in text if ch.isalnum()]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:'[a-z]+)?", unicodedata.normalize("NFKC", text or "").casefold())


def _mixed(text: str, *, fold: bool = False) -> list[str]:
    """CJK characters as tokens, Latin words as tokens (mixed error rate for code-switched speech)."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    if fold:
        from postriff_phase2.library_intelligence import textnorm
        text = textnorm.fold(text)
    return re.findall(r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]|[a-z0-9]+(?:'[a-z]+)?", text)


def cer(reference: str, hypothesis: str, *, fold: bool = False) -> float:
    ref = _chars(reference, fold=fold)
    return _distance(ref, _chars(hypothesis, fold=fold)) / max(1, len(ref))


def wer(reference: str, hypothesis: str) -> float:
    ref = _words(reference)
    return _distance(ref, _words(hypothesis)) / max(1, len(ref))


def mer(reference: str, hypothesis: str, *, fold: bool = False) -> float:
    ref = _mixed(reference, fold=fold)
    return _distance(ref, _mixed(hypothesis, fold=fold)) / max(1, len(ref))


def segment_scores(reference: dict, hypothesis_segments: list[dict]) -> dict:
    """Score one labelled reference segment against the hypothesis text that overlaps its interval."""
    start, end = int(reference["startMs"]), int(reference["endMs"])
    overlapping = [h for h in hypothesis_segments if min(end, int(h["endMs"])) > max(start, int(h["startMs"]))]
    hyp = " ".join(h["text"] for h in overlapping)
    language = reference.get("language")
    out = {"startMs": start, "endMs": end, "language": language, "reference": reference["text"], "hypothesis": hyp,
           "hypothesisLanguages": sorted({h.get("language") or "unknown" for h in overlapping})}
    if language == "en":
        out["metric"], out["errorRate"] = "WER", wer(reference["text"], hyp)
    elif language in ("yue", "zh-Hant", "zh-Hans", "zh"):
        out["metric"], out["errorRate"] = "CER", cer(reference["text"], hyp)
        out["errorRateScriptFolded"] = cer(reference["text"], hyp, fold=True)
    else:
        out["metric"], out["errorRate"] = "MER", mer(reference["text"], hyp)
        out["errorRateScriptFolded"] = mer(reference["text"], hyp, fold=True)
    return out


def usable_moment(query: dict, hypothesis_segments: list[dict]) -> bool:
    """A labelled moment is usable when a hypothesis segment overlapping it contains the query (script-folded)."""
    needle = "".join(_mixed(query["text"], fold=True))
    for h in hypothesis_segments:
        if min(int(query["endMs"]), int(h["endMs"])) > max(int(query["startMs"]), int(h["startMs"])) and needle and needle in "".join(_mixed(h["text"], fold=True)):
            return True
    return False


def aggregate(scored: list[dict]) -> dict:
    by: dict = {}
    for s in scored:
        bucket = by.setdefault(s["language"] or "unknown", {"metric": s["metric"], "segments": 0, "errorRateMean": 0.0})
        bucket["segments"] += 1
        bucket["errorRateMean"] += s["errorRate"]
    for bucket in by.values():
        bucket["errorRateMean"] = round(bucket["errorRateMean"] / bucket["segments"], 4)
    return by


# --- authorization --------------------------------------------------------------------------------------------------------------
def authorization(environ, *, confirmed: bool = False, providers=None) -> dict:
    reasons = []
    reference = str(environ.get(AUTH_ENV) or "").strip()
    if not reference:
        reasons.append(f"{AUTH_ENV} is not set (James's explicit paid-inference authorization is required)")
    if not confirmed:
        reasons.append("--confirm-paid-inference was not passed")
    if providers is not None:
        status = providers.status()["asr"]
        if not status["available"]:
            reasons.append(f"ASR provider unavailable: {status['reason']}")
    return {"status": "AUTHORIZED", "reference": reference} if not reasons else {"status": "BLOCKED", "reasons": reasons}


def _sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--hypotheses", help="score previously captured transcripts; no provider call")
    parser.add_argument("--confirm-paid-inference", action="store_true")
    args = parser.parse_args(argv)
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text())
    from postriff_phase2.library_intelligence import media
    from postriff_phase2.library_intelligence.providers import Providers
    receipt = {"candidateSha": _sha(), "startedAt": time.time(), "clips": [], "errors": []}
    if args.hypotheses:
        captured = json.loads(Path(args.hypotheses).read_text())
        receipt.update(execution="offline-hypotheses", processor=captured.get("processor"))
        transcripts = {c["id"]: c for c in captured.get("clips", [])}
    else:
        providers = Providers()
        gate = authorization(os.environ, confirmed=args.confirm_paid_inference, providers=providers)
        if gate["status"] != "AUTHORIZED":
            print(json.dumps({**gate, "candidateSha": receipt["candidateSha"], "execution": "not-run"}, indent=2))
            return 3
        receipt.update(execution="real-provider", authorization=gate["reference"], processor={"provider": "openai", "model": providers.model("asr")})
        transcripts = {}
        for clip in manifest.get("clips", []):
            raw = (manifest_path.parent / clip["path"]).read_bytes()
            try:
                result = providers.transcribe(raw, Path(clip["path"]).name, clip.get("mime") or "audio/mpeg")
            except Exception as error:  # noqa: BLE001 - every failure is recorded, never hidden
                receipt["errors"].append({"clip": clip["id"], "error": str(error)[:300], "code": getattr(error, "code", None)})
                continue
            items = media.transcript_items(result.value, None)
            transcripts[clip["id"]] = {"id": clip["id"], "segments": [{"startMs": i["locator"]["startMs"], "endMs": i["locator"]["endMs"],
                                                                      "text": i["text"], "language": i["language"]} for i in items],
                                       "receipt": result.receipt()}
    all_scored = []
    for clip in manifest.get("clips", []):
        hyp = transcripts.get(clip["id"])
        if hyp is None:
            receipt["errors"].append({"clip": clip["id"], "error": "no transcript"})
            continue
        scored = [segment_scores(ref, hyp["segments"]) for ref in clip.get("segments", [])]
        all_scored += scored
        receipt["clips"].append({"id": clip["id"], "segments": scored, "byLanguage": aggregate(scored),
                                 "moments": [{"query": q["text"], "usable": usable_moment(q, hyp["segments"])} for q in clip.get("queries", [])],
                                 "provider": hyp.get("receipt")})
    receipt["byLanguage"] = aggregate(all_scored)
    receipt["finishedAt"] = time.time()
    Path(args.out).write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print(json.dumps({"execution": receipt["execution"], "clips": len(receipt["clips"]), "errors": len(receipt["errors"]),
                      "byLanguage": receipt["byLanguage"]}, ensure_ascii=False, indent=2))
    return 1 if receipt["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
