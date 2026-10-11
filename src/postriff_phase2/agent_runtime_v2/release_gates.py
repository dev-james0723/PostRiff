"""Persisted live GenUI release gates for CF2 enforcement.

There is deliberately no HTTP write endpoint or environment "verified" switch. A trusted release coordinator must verify
browser evidence and deployment/policy provenance, then call record() with a trusted verifier. record() independently
checks the physical attempt rows and ready revisions. Runtime reads service-only immutable receipts, pinned to its exact
SHA, catalogue, renderer assets, provider and model. Missing storage, unknown provenance and stale evidence fail closed.
A fixture verifier in a test proves the verifier contract only, never a live gate.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid

CONTRACT = "rafii-live-permission-gate/1"
CORPUS_ID = "g03-live-60/v2"
CORPUS_SHA = "ef9e061b3705f7617b5467f6b1e8e9b904aa5fd5d0538d1a5a9299e937dbe4e3"
CASE_IDS = tuple(f"J{j:02d}-{c}" for cset in ("abc", "def") for j in range(1, 10) for c in cset)
# The frozen corpus puts three composites after each group of 27 journey cases.
CASE_IDS = CASE_IDS[:27] + tuple(f"CMP-{c}" for c in "abc") + CASE_IDS[27:] + tuple(f"CMP-{c}" for c in "def")
MAX_AGE = 7 * 86400
PROFILES = {"full": {"preset": "full"},
            "recommended_narrowed": {"preset": "recommended", "create_edit": "ask", "analytics": "off"}}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def pins(config):
    """Trusted server code/config only. A model/provider or generated prompt change invalidates an earlier receipt."""
    from . import capability_registry, ui_presenter
    route = config.route("fast_language", reason="permission release gate")
    if not route.available or route.provider not in ("openai", "gateway") or not route.model:
        raise ValueError("release gate requires a configured presenter route")
    assets = ui_presenter.load_assets().data
    return {"registryDigest": capability_registry.catalogue_digest(), "assetsDigest": digest(assets),
            "provider": route.provider, "model": route.model,
            "libraryHashes": {k: v["libraryHash"] for k, v in assets["libraries"].items()}}


def validate(receipt, workspace_id, release_sha, expected, *, now):
    """Pure strict validator. Boolean summaries never replace the complete, ordered fixed corpus."""
    try:
        if not isinstance(receipt, dict) or not _uuid(workspace_id) or not SHA.fullmatch(release_sha):
            return False
        if (receipt.get("contract") != CONTRACT or receipt.get("execution") != "live-browser+database"
                or receipt.get("workspaceId") != workspace_id or receipt.get("releaseSha") != release_sha
                or receipt.get("pins") != expected or receipt.get("corpus") != {"id": CORPUS_ID, "sha256": CORPUS_SHA}):
            return False
        if set(receipt) != {"contract", "execution", "workspaceId", "releaseSha", "pins", "corpus", "profile", "policy",
                            "startedAt", "finishedAt", "runId", "browserEvidenceSha256", "deploymentEvidenceSha256", "cases"}:
            return False
        profile = receipt.get("profile")
        if profile not in PROFILES or receipt.get("policy") != PROFILES[profile]:
            return False
        start, end = receipt.get("startedAt"), receipt.get("finishedAt")
        if type(start) not in (int, float) or type(end) not in (int, float) or not now-MAX_AGE <= start <= end <= now:
            return False
        if not _uuid(receipt.get("runId")) or not HEX64.fullmatch(str(receipt.get("browserEvidenceSha256", ""))):
            return False
        if not HEX64.fullmatch(str(receipt.get("deploymentEvidenceSha256", ""))):
            return False
        cases = receipt.get("cases")
        if not isinstance(cases, list) or [c.get("caseId") for c in cases] != list(CASE_IDS):
            return False
        artifacts, attempts = set(), set()
        first_pass = 0
        for case in cases:
            if set(case) != {"caseId", "artifactId", "rendered", "functional", "firstPass", "attemptIds", "sourceHash",
                             "manifestHash", "promptHash", "browserCaseSha256"}:
                return False
            if not _uuid(case.get("artifactId")) or case["artifactId"] in artifacts:
                return False
            artifacts.add(case["artifactId"])
            if case.get("rendered") is not True or case.get("functional") is not True or type(case.get("firstPass")) is not bool:
                return False
            ids = case.get("attemptIds")
            if not isinstance(ids, list) or len(ids) != (1 if case["firstPass"] else 2):
                return False
            if any(not _uuid(i) or i in attempts for i in ids) or len(ids) != len(set(ids)):
                return False
            attempts.update(ids)
            if not HEX64.fullmatch(str(case.get("sourceHash", ""))) or not HEX64.fullmatch(str(case.get("manifestHash", ""))):
                return False
            if not HEX64.fullmatch(str(case.get("promptHash", ""))) or not HEX64.fullmatch(str(case.get("browserCaseSha256", ""))):
                return False
            first_pass += case["firstPass"]
        return first_pass >= 59
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


ATTEMPTS_SQL = """SELECT t.id::text,t.artifact_id::text,t.kind,t.state,t.retry_of::text,t.provider_attempts,
 t.cost_state,t.cost_usd_micro,t.usage,a.scope,a.library_hash,a.prompt_hash,a.manifest,
 r.source_hash,r.validation,extract(epoch from t.admitted_at),extract(epoch from t.finished_at)
 FROM public.pr_ui_attempts t JOIN public.pr_ui_artifacts a ON a.id=t.artifact_id AND a.workspace_id=t.workspace_id
 LEFT JOIN public.pr_ui_revisions r ON r.attempt_id=t.id AND r.artifact_id=t.artifact_id AND r.workspace_id=t.workspace_id
 WHERE t.workspace_id=%s::uuid AND t.artifact_id=ANY(%s::uuid[])
 AND t.target_revision=1 AND t.kind IN ('generate','repair','retry')"""


def _physical(cur, receipt):
    ids = [i for c in receipt["cases"] for i in c["attemptIds"]]
    cur.execute(ATTEMPTS_SQL, (receipt["workspaceId"], [c["artifactId"] for c in receipt["cases"]]))
    rows = cur.fetchall()
    by_id = {row[0]: row for row in rows}
    if len(rows) != len(ids) or set(by_id) != set(ids):
        return False
    expected = receipt["pins"]
    for case in receipt["cases"]:
        for index, attempt_id in enumerate(case["attemptIds"]):
            row = by_id[attempt_id]
            _, artifact, kind, state, retry, count, cost_state, cost, usage, scope, library, prompt, manifest, source, validation, start, end = row
            final = index == len(case["attemptIds"])-1
            if (artifact != case["artifactId"] or kind != ("generate" if index == 0 else "repair")
                    or state != ("ready" if final else "failed") or count != 1 or cost_state != "known" or cost is None):
                return False
            if retry != (None if index == 0 else case["attemptIds"][0]):
                return False
            if not isinstance(usage, dict) or usage.get("model") != expected["model"] or usage.get("provider") != expected["provider"]:
                return False
            wanted_scope = "founder" if case["caseId"].startswith("J09-") else "workspace"
            library_key = "founder" if wanted_scope == "founder" else "consumer"
            if scope != wanted_scope or library != expected["libraryHashes"].get(library_key):
                return False
            if prompt != case["promptHash"] or digest(manifest) != case["manifestHash"]:
                return False
            if start is None or end is None or not receipt["startedAt"] <= float(start) <= float(end) <= receipt["finishedAt"]:
                return False
            if final and (source != case["sourceHash"] or not isinstance(validation, dict) or validation.get("accepted") is not True):
                return False
    return True


def record(cur, receipt, expected, *, verifier, now=None):
    """Privileged coordinator only. verifier must independently bind browser render + actual deployment/policy evidence.

    Never pass a verifier constructed from an uploaded boolean. Caller owns the transaction; no cross-project writes.
    This does not enable anything. Any changed receipt needs a fresh immutable run ID and complete verification.
    """
    now = time.time() if now is None else now
    if not validate(receipt, receipt.get("workspaceId"), receipt.get("releaseSha"), expected, now=now):
        raise ValueError("invalid or incomplete live release receipt")
    if not callable(verifier) or verifier(receipt) is not True or not _physical(cur, receipt):
        raise ValueError("live browser, deployment, policy and physical provider evidence required")
    body = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    cur.execute("""INSERT INTO public.pr_agent_release_gates(run_id,workspace_id,release_sha,profile,receipt_hash,receipt,verified_at)
 VALUES(%s::uuid,%s::uuid,%s,%s,%s,%s::jsonb,to_timestamp(%s)) ON CONFLICT (run_id) DO NOTHING""",
                (receipt["runId"], receipt["workspaceId"], receipt["releaseSha"], receipt["profile"], digest(receipt), body, now))
    cur.execute("SELECT receipt_hash FROM public.pr_agent_release_gates WHERE run_id=%s::uuid", (receipt["runId"],))
    row = cur.fetchone()
    if not row or row[0] != digest(receipt):
        raise ValueError("release receipt id already refers to different evidence")


def reader(connection_factory, config, *, clock=time.time):
    """RuntimeConfig.permissions_gate_reader, fail closed on storage/schema/provenance errors. No provider calls."""
    def ready(workspace_id, release_sha):
        try:
            expected = pins(config)
            now = clock()
            with connection_factory() as db, db.cursor() as cur:
                cur.execute("""SELECT receipt,receipt_hash FROM public.pr_agent_release_gates
 WHERE workspace_id=%s::uuid AND release_sha=%s AND revoked_at IS NULL
 AND verified_at >= to_timestamp(%s) ORDER BY verified_at DESC LIMIT 20""", (workspace_id, release_sha, now-MAX_AGE))
                rows = cur.fetchall()
            found = {}
            for receipt, sha in rows:
                if not isinstance(receipt, dict) or digest(receipt) != sha:
                    continue
                if validate(receipt, workspace_id, release_sha, expected, now=now):
                    found.setdefault(receipt["profile"], receipt)
            if set(found) != set(PROFILES):
                return False
            first, second = found.values()
            # Two independent runs, never one copied fixture or the same artifacts relabelled as another profile.
            return (first["runId"] != second["runId"] and
                    not {c["artifactId"] for c in first["cases"]} & {c["artifactId"] for c in second["cases"]} and
                    not {i for c in first["cases"] for i in c["attemptIds"]} & {i for c in second["cases"] for i in c["attemptIds"]})
        except Exception:  # Missing migration/reader/pins is never permission to enforce.
            return False
    return ready
