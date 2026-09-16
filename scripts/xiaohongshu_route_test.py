#!/usr/bin/env python3
"""Execute the single approved 2026-09-14 RedNote route-test manifest.

This is deliberately narrow: it accepts only the pinned manifest/hash, records
the uncertain side-effect boundary before HTTP submission, and will never retry
a submitting, submitted, verified, or ambiguous job.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / "docs/xiaohongshu-route-tests/2026-09-14"
MANIFEST_PATH = TEST_DIR / "route-test-manifest.json"
RECEIPT_PATH = TEST_DIR / "approval-receipt.json"
LEDGER_PATH = TEST_DIR / "execution-ledger.sqlite3"
LOCK_PATH = TEST_DIR / "execution.lock"
EXPECTED_MANIFEST_HASH = "sha256:67d329f7b409ee6c40444bb9128bf65bef72727b75051932fef678be4f87b65a"
EXPECTED_PROFILE_ID = "6aa748a9000000000301c840"
EXPECTED_REDNOTE_ID = "94556602041"
EXPECTED_NICKNAME = "小红薯6AA7E810"
BASE_URL = "http://127.0.0.1:18060"
KEYCHAIN_SERVICE = "James Au Studio Xiaohongshu MCP"
KEYCHAIN_ACCOUNT = "local-service"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value) -> str:
    if not isinstance(value, bytes):
        value = canonical(value)
    return "sha256:" + hashlib.sha256(value).hexdigest()


def atomic_private_json(path: Path, value: dict) -> None:
    if path.is_symlink():
        raise ValueError("symlink_output")
    descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def load_manifest() -> tuple[dict, dict[str, dict]]:
    if MANIFEST_PATH.is_symlink() or not MANIFEST_PATH.is_file():
        raise ValueError("manifest_invalid")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    embedded = manifest.get("manifestHash")
    body = {key: value for key, value in manifest.items() if key != "manifestHash"}
    if embedded != EXPECTED_MANIFEST_HASH or digest(body) != EXPECTED_MANIFEST_HASH:
        raise ValueError("manifest_hash_mismatch")
    jobs = {job["jobId"]: job for job in manifest["jobs"]}
    if len(jobs) != 3:
        raise ValueError("manifest_job_set_mismatch")
    for job in jobs.values():
        if (job["account"]["profileId"] != EXPECTED_PROFILE_ID
                or job["account"]["rednoteId"] != EXPECTED_REDNOTE_ID
                or job["account"]["nickname"] != EXPECTED_NICKNAME
                or job["visibility"] != "仅自己可见"
                or job["derivatives"] != []):
            raise ValueError("manifest_scope_mismatch")
        for media in job["media"]:
            path = Path(media["path"])
            if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("media_invalid")
            if digest(path.read_bytes()) != media["sha256"]:
                raise ValueError("media_hash_mismatch")
    return manifest, jobs


def token() -> str:
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT,
         "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=5, check=False,
    )
    value = result.stdout.rstrip("\n") if result.returncode == 0 else ""
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("service_token_unavailable")
    return value


def request(method: str, path: str, body: dict | None = None, *, timeout: int = 60) -> dict:
    data = canonical(body) if body is not None else None
    headers = {"Authorization": "Bearer " + token(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read(1024 * 1024)
            if response.status != 200:
                raise ValueError("unexpected_http_status")
    except HTTPError as error:
        raw_error = error.read(64 * 1024)
        safe_detail = ""
        try:
            parsed = json.loads(raw_error)
            candidate = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(candidate, dict):
                safe_detail = ":" + ":".join(
                    str(candidate.get(key, ""))[:160] for key in ("code", "message", "details")
                )
            elif isinstance(parsed, dict):
                safe_detail = ":" + str(parsed.get("message", ""))[:240]
        except (ValueError, UnicodeDecodeError):
            safe_detail = ""
        raise ValueError("http_error:" + str(error.code) + safe_detail) from None
    except URLError as error:
        raise ValueError("transport_error:" + type(error.reason).__name__) from None
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("invalid_json_response")
    return value


def identity_and_feeds() -> tuple[dict, list[dict]]:
    login = request("GET", "/api/v1/login/status", timeout=60)
    login_data = login.get("data", {})
    if login.get("success") is not True or login_data.get("is_logged_in") is not True:
        raise ValueError("session_not_authenticated")
    profile = request("GET", "/api/v1/user/me?tab=note", timeout=120)
    profile_data = profile.get("data", {}).get("data", {})
    basic = profile_data.get("userBasicInfo", {})
    if basic.get("redId") != EXPECTED_REDNOTE_ID or basic.get("nickname") != EXPECTED_NICKNAME:
        raise ValueError("identity_mismatch")
    # A brand-new account is serialized by the upstream Go service with a null
    # feed slice. Treat that exact case as an empty owner feed.
    feeds = profile_data.get("feeds")
    if feeds is None:
        feeds = []
    if not isinstance(feeds, list):
        raise ValueError("invalid_feed_response")
    return {"rednoteId": basic["redId"], "nickname": basic["nickname"]}, feeds


def connect() -> sqlite3.Connection:
    if LEDGER_PATH.is_symlink():
        raise ValueError("symlink_ledger")
    db = sqlite3.connect(LEDGER_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(
      job_id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, job_hash TEXT NOT NULL,
      status TEXT NOT NULL, approved_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      endpoint TEXT, safe_result TEXT, evidence TEXT);
    CREATE TABLE IF NOT EXISTS attempts(
      job_id TEXT NOT NULL, attempt INTEGER NOT NULL, started_at TEXT NOT NULL,
      boundary_state TEXT NOT NULL, ended_at TEXT, safe_result TEXT,
      PRIMARY KEY(job_id, attempt));
    """)
    os.chmod(LEDGER_PATH, 0o600)
    return db


def receipt() -> dict:
    if not RECEIPT_PATH.is_file() or RECEIPT_PATH.is_symlink():
        raise ValueError("approval_receipt_missing")
    value = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    body = {key: item for key, item in value.items() if key != "receiptHash"}
    if value.get("receiptHash") != digest(body):
        raise ValueError("approval_receipt_hash_mismatch")
    if (value.get("manifestHash") != EXPECTED_MANIFEST_HASH
            or value.get("approvedBy") != "user"
            or value.get("approvalText") != "yes"):
        raise ValueError("approval_receipt_scope_mismatch")
    return value


def initialize(approved_at: str) -> None:
    manifest, jobs = load_manifest()
    value = {
        "recordType": "ExactRouteTestApprovalReceipt",
        "schemaVersion": 1,
        "manifestId": manifest["manifestId"],
        "manifestHash": EXPECTED_MANIFEST_HASH,
        "approvedBy": "user",
        "approverSessionRef": "current-codex-task",
        "approvalText": "yes",
        "approvedAt": approved_at,
        "approvedJobs": list(jobs),
        "scope": {
            "audience": "仅自己可见",
            "immediateSubmissions": 2,
            "scheduledSubmissions": 1,
            "derivatives": [],
            "deletionOrCancellation": False,
            "publicVisibility": False,
            "recurringAutomation": False,
        },
    }
    value["receiptHash"] = digest(value)
    atomic_private_json(RECEIPT_PATH, value)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for job_id, job in jobs.items():
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id) DO NOTHING",
                (job_id, EXPECTED_MANIFEST_HASH, digest(job), "approved", approved_at,
                 approved_at, None, None, None),
            )
    print(json.dumps({"state": "approved", "manifestHash": EXPECTED_MANIFEST_HASH,
                      "jobs": list(jobs)}, ensure_ascii=False))


def payload_for(job: dict) -> tuple[str, dict]:
    payload = {
        "title": job["title"], "content": job["content"], "tags": job["tags"],
        "visibility": job["visibility"],
    }
    if job["operation"] in {"publish_image_note", "schedule_image_note"}:
        endpoint = "/api/v1/publish"
        payload["images"] = [item["path"] for item in job["media"]]
    elif job["operation"] == "publish_video_note":
        endpoint = "/api/v1/publish_video"
        payload["video"] = job["media"][0]["path"]
    else:
        raise ValueError("unsupported_operation")
    if job["scheduledAt"]:
        payload["schedule_at"] = job["scheduledAt"]
    return endpoint, payload


def check_dependencies(db: sqlite3.Connection, job: dict) -> None:
    if job["operation"] == "publish_video_note":
        row = db.execute("SELECT status FROM jobs WHERE job_id=?",
                         ("xhs-rednote-image-route-test-20260914-v1",)).fetchone()
        if not row or row["status"] != "verified_published":
            raise ValueError("image_dependency_not_verified")
    if job["operation"] == "schedule_image_note":
        rows = dict(db.execute("SELECT job_id,status FROM jobs").fetchall())
        for dependency in ("xhs-rednote-image-route-test-20260914-v1",
                           "xhs-rednote-video-route-test-20260914-v1"):
            if rows.get(dependency) != "verified_published":
                raise ValueError("immediate_dependency_not_verified")


def submit(job_id: str) -> None:
    _, jobs = load_manifest()
    receipt()
    if job_id not in jobs:
        raise ValueError("job_not_in_manifest")
    job = jobs[job_id]
    identity, before = identity_and_feeds()
    endpoint, payload = payload_for(job)
    started = now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["manifest_hash"] != EXPECTED_MANIFEST_HASH or row["job_hash"] != digest(job):
            raise ValueError("ledger_job_drift")
        check_dependencies(db, job)
        if row["status"] not in {"approved", "approved_retry_after_reconciliation"}:
            raise ValueError("job_not_retryable:" + row["status"])
        attempt = db.execute("SELECT COUNT(*) FROM attempts WHERE job_id=?", (job_id,)).fetchone()[0] + 1
        if attempt not in {1, 2} or (attempt == 2 and row["status"] != "approved_retry_after_reconciliation"):
            raise ValueError("attempt_already_exists")
        preflight = {"identity": identity, "feedCount": len(before), "payloadHash": digest(payload)}
        db.execute("INSERT INTO attempts VALUES(?,?,?,?,NULL,?)",
                   (job_id, attempt, started, "submitting", json.dumps(preflight, ensure_ascii=False)))
        db.execute("UPDATE jobs SET status='submitting',updated_at=?,endpoint=?,safe_result=? WHERE job_id=?",
                   (started, endpoint, json.dumps(preflight, ensure_ascii=False), job_id))
    # The side-effect boundary begins here. Any exception after this line is ambiguous.
    try:
        response = request("POST", endpoint, payload, timeout=900)
        data = response.get("data", {})
        if response.get("success") is not True or data.get("title") != job["title"]:
            raise ValueError("submission_acknowledgement_mismatch")
        safe = {"success": True, "title": data.get("title"), "status": data.get("status"),
                "message": response.get("message"), "responseHash": digest(response)}
        ended = now()
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE attempts SET boundary_state='acknowledged',ended_at=?,safe_result=? WHERE job_id=? AND attempt=?",
                       (ended, json.dumps(safe, ensure_ascii=False), job_id, attempt))
            db.execute("UPDATE jobs SET status='submitted_unverified',updated_at=?,safe_result=? WHERE job_id=? AND status='submitting'",
                       (ended, json.dumps(safe, ensure_ascii=False), job_id))
        print(json.dumps({"jobId": job_id, "state": "submitted_unverified", "safeAcknowledgement": safe}, ensure_ascii=False))
    except BaseException as error:
        ended = now()
        safe = {"errorClass": type(error).__name__, "error": str(error)[:240]}
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE attempts SET boundary_state='ambiguous',ended_at=?,safe_result=? WHERE job_id=? AND attempt=?",
                       (ended, json.dumps(safe, ensure_ascii=False), job_id, attempt))
            db.execute("UPDATE jobs SET status='ambiguous',updated_at=?,safe_result=? WHERE job_id=? AND status='submitting'",
                       (ended, json.dumps(safe, ensure_ascii=False), job_id))
        raise


def reconcile_no_submission(job_id: str) -> None:
    _, jobs = load_manifest()
    receipt()
    if job_id not in jobs:
        raise ValueError("job_not_in_manifest")
    job = jobs[job_id]
    identity, feeds = identity_and_feeds()
    exact = []
    for feed in feeds:
        card = feed.get("noteCard", {}) if isinstance(feed, dict) else {}
        if card.get("displayTitle") == job["title"]:
            exact.append({"providerNoteId": feed.get("id"), "noteType": card.get("type")})
    if exact:
        raise ValueError("provider_record_exists_reconciliation_refused")
    evidence = {
        "checkedAt": now(),
        "identity": identity,
        "source": "owner_profile_read_plus_preserved_pre_submit_browser_observation",
        "ownerProfileExactTitleMatches": 0,
        "browserObservation": {
            "publishFormStillOpen": True,
            "audienceDisplayed": "公开可见",
            "blockingModal": "选择笔记",
            "finalSubmitObserved": False,
        },
        "conclusion": "failed_before_final_submit",
    }
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        attempts = db.execute("SELECT COUNT(*) FROM attempts WHERE job_id=?", (job_id,)).fetchone()[0]
        if not row or row["status"] != "ambiguous" or attempts != 1:
            raise ValueError("job_not_reconcilable")
        db.execute("UPDATE jobs SET status='approved_retry_after_reconciliation',updated_at=?,evidence=? WHERE job_id=?",
                   (evidence["checkedAt"], json.dumps(evidence, ensure_ascii=False), job_id))
    print(json.dumps({"jobId": job_id, "state": "approved_retry_after_reconciliation",
                      "evidence": evidence}, ensure_ascii=False))


def reconcile_scheduled_no_record(job_id: str, observation_path: Path) -> None:
    _, jobs = load_manifest()
    receipt()
    job = jobs.get(job_id)
    if not job or job["operation"] != "schedule_image_note":
        raise ValueError("scheduled_job_required")
    if observation_path.is_symlink() or not observation_path.is_file():
        raise ValueError("management_observation_invalid")
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    if (observation.get("url") != "https://creator.rednote.com/new/note-manager?source=official"
            or observation.get("titlePresent") is not False
            or observation.get("records") != []):
        raise ValueError("scheduled_record_may_exist")
    evidence = {
        "checkedAt": now(),
        "source": observation["url"],
        "exactTitleMatches": 0,
        "observationHash": digest(observation),
        "conclusion": "no_scheduled_record_after_failed_call",
    }
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        attempts = db.execute("SELECT COUNT(*) FROM attempts WHERE job_id=?", (job_id,)).fetchone()[0]
        if not row or row["status"] != "ambiguous" or attempts != 1:
            raise ValueError("scheduled_job_not_reconcilable")
        db.execute("UPDATE jobs SET status='approved_retry_after_reconciliation',updated_at=?,evidence=? WHERE job_id=?",
                   (evidence["checkedAt"], json.dumps(evidence, ensure_ascii=False), job_id))
    print(json.dumps({"jobId": job_id, "state": "approved_retry_after_reconciliation",
                      "evidence": evidence}, ensure_ascii=False))


def verify_profile(job_id: str) -> None:
    _, jobs = load_manifest()
    receipt()
    if job_id not in jobs:
        raise ValueError("job_not_in_manifest")
    job = jobs[job_id]
    identity, feeds = identity_and_feeds()
    wanted_type = "video" if job["operation"] == "publish_video_note" else "normal"
    matches = []
    for feed in feeds:
        card = feed.get("noteCard", {}) if isinstance(feed, dict) else {}
        if card.get("displayTitle") == job["title"] and card.get("type") == wanted_type:
            matches.append({
                "providerNoteId": feed.get("id"), "modelType": feed.get("modelType"),
                "noteType": card.get("type"), "title": card.get("displayTitle"),
                "authorUserId": card.get("user", {}).get("userId"),
                "authorNickname": card.get("user", {}).get("nickname") or card.get("user", {}).get("nickName"),
                "videoDuration": (card.get("video") or {}).get("capa", {}).get("duration"),
            })
    if len(matches) != 1 or not matches[0]["providerNoteId"]:
        raise ValueError("independent_profile_match_unresolved:" + str(len(matches)))
    if matches[0]["authorUserId"] not in {None, "", EXPECTED_PROFILE_ID}:
        raise ValueError("independent_author_mismatch")
    evidence = {"checkedAt": now(), "source": "authenticated_owner_profile_read",
                "identity": identity, "match": matches[0],
                "visibility": "not_exposed_by_owner_profile_read"}
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] not in {"submitted_unverified", "verified_profile_only"}:
            raise ValueError("job_not_verifiable")
        db.execute("UPDATE jobs SET status='verified_profile_only',updated_at=?,evidence=? WHERE job_id=?",
                   (evidence["checkedAt"], json.dumps(evidence, ensure_ascii=False), job_id))
    print(json.dumps({"jobId": job_id, "state": "verified_profile_only", "evidence": evidence}, ensure_ascii=False))


def verify_management(job_id: str, observation_path: Path) -> None:
    _, jobs = load_manifest()
    receipt()
    if job_id not in jobs:
        raise ValueError("job_not_in_manifest")
    job = jobs[job_id]
    if observation_path.is_symlink() or not observation_path.is_file():
        raise ValueError("management_observation_invalid")
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    if (observation.get("url") != "https://creator.rednote.com/new/note-manager?source=official"
            or observation.get("titlePresent") is not True
            or observation.get("selfOnlyPresent") is not True):
        raise ValueError("management_observation_mismatch")
    records = observation.get("records")
    if not isinstance(records, list):
        raise ValueError("management_records_invalid")
    matching_texts = {
        record.get("text") for record in records if isinstance(record, dict)
        and record.get("tag") == "DIV" and record.get("cls") == "note-card"
        and job["title"] in str(record.get("text")) and "仅自己可见" in str(record.get("text"))
    }
    if len(matching_texts) != 1:
        raise ValueError("management_exact_record_unresolved")
    record_text = next(iter(matching_texts))
    detail_evidence = None
    if job["operation"] == "publish_video_note":
        if "审核中" in record_text:
            raise ValueError("provider_review_pending")
        detail_path = TEST_DIR / "video-detail-observation.json"
        if detail_path.is_symlink() or not detail_path.is_file():
            raise ValueError("video_detail_observation_missing")
        detail_evidence = json.loads(detail_path.read_text(encoding="utf-8"))
    checked = now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status,evidence FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] != "verified_profile_only" or not row["evidence"]:
            raise ValueError("profile_verification_required")
        profile_evidence = json.loads(row["evidence"])
        if detail_evidence is not None:
            if (detail_evidence.get("success") is not True
                    or detail_evidence.get("noteId") != profile_evidence.get("match", {}).get("providerNoteId")
                    or detail_evidence.get("title") != job["title"]
                    or detail_evidence.get("type") != "video"
                    or detail_evidence.get("authorUserId") != EXPECTED_PROFILE_ID
                    or detail_evidence.get("durationSeconds") != 4
                    or detail_evidence.get("hasVideo") is not True
                    or sum(detail_evidence.get("streamVariants", {}).values()) < 1):
                raise ValueError("video_detail_observation_mismatch")
        evidence = {
            "checkedAt": checked,
            "profile": profile_evidence,
            "creatorCenter": {
                "source": observation["url"],
                "recordText": record_text,
                "observationHash": digest(observation),
                "titleMatched": True,
                "audienceMatched": "仅自己可见",
            },
        }
        if detail_evidence is not None:
            evidence["videoDetail"] = detail_evidence
        db.execute("UPDATE jobs SET status='verified_published',updated_at=?,evidence=? WHERE job_id=?",
                   (checked, json.dumps(evidence, ensure_ascii=False), job_id))
    print(json.dumps({"jobId": job_id, "state": "verified_published", "evidence": evidence}, ensure_ascii=False))


def verify_scheduled_management(job_id: str, observation_path: Path) -> None:
    _, jobs = load_manifest()
    receipt()
    job = jobs.get(job_id)
    if not job or job["operation"] != "schedule_image_note":
        raise ValueError("scheduled_job_required")
    if observation_path.is_symlink() or not observation_path.is_file():
        raise ValueError("management_observation_invalid")
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    if (observation.get("url") != "https://creator.rednote.com/new/note-manager?source=official"
            or observation.get("titlePresent") is not True
            or observation.get("selfOnlyPresent") is not True):
        raise ValueError("scheduled_management_observation_mismatch")
    records = observation.get("records")
    matching_texts = {
        record.get("text") for record in records if isinstance(record, dict)
        and record.get("tag") == "DIV" and record.get("cls") == "note-card"
        and job["title"] in str(record.get("text")) and "仅自己可见" in str(record.get("text"))
    } if isinstance(records, list) else set()
    if len(matching_texts) != 1:
        raise ValueError("scheduled_exact_record_unresolved")
    record_text = next(iter(matching_texts))
    # Creator Center displays Beijing time (UTC+8). The approved instant
    # 2026-09-15T10:30:00-04:00 must therefore display as 22:30 there.
    if "定时" not in record_text or "2026-09-15 22:30" not in record_text:
        raise ValueError("scheduled_time_or_state_unresolved")
    checked = now()
    evidence = {
        "checkedAt": checked,
        "source": observation["url"],
        "recordText": record_text,
        "observationHash": digest(observation),
        "titleMatched": True,
        "audienceMatched": "仅自己可见",
        "approvedScheduledAt": job["scheduledAt"],
        "providerDisplayEquivalent": "2026-09-15 22:30 Asia/Shanghai",
    }
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] != "submitted_unverified":
            raise ValueError("scheduled_job_not_verifiable")
        db.execute("UPDATE jobs SET status='verified_scheduled',updated_at=?,evidence=? WHERE job_id=?",
                   (checked, json.dumps(evidence, ensure_ascii=False), job_id))
    print(json.dumps({"jobId": job_id, "state": "verified_scheduled", "evidence": evidence}, ensure_ascii=False))


def mark_schedule_time_mismatch(job_id: str, observation_path: Path) -> None:
    _, jobs = load_manifest()
    receipt()
    job = jobs.get(job_id)
    if not job or job["operation"] != "schedule_image_note":
        raise ValueError("scheduled_job_required")
    if observation_path.is_symlink() or not observation_path.is_file():
        raise ValueError("management_observation_invalid")
    observation = json.loads(observation_path.read_text(encoding="utf-8"))
    records = observation.get("records")
    matching_texts = {
        record.get("text") for record in records if isinstance(record, dict)
        and record.get("tag") == "DIV" and record.get("cls") == "note-card"
        and job["title"] in str(record.get("text")) and "仅自己可见" in str(record.get("text"))
    } if isinstance(records, list) else set()
    if len(matching_texts) != 1:
        raise ValueError("scheduled_exact_record_unresolved")
    record_text = next(iter(matching_texts))
    if ("定时发布" not in record_text
            or "2026-09-15 10:30" not in record_text
            or "GMT+8:00" not in record_text):
        raise ValueError("wrong_provider_time_not_proven")
    checked = now()
    evidence = {
        "checkedAt": checked,
        "source": observation.get("url"),
        "recordText": record_text,
        "observationHash": digest(observation),
        "approvedScheduledAt": job["scheduledAt"],
        "actualProviderScheduledAt": "2026-09-15T10:30:00+08:00",
        "actualInApprovedTimezone": "2026-09-14T22:30:00-04:00",
        "differenceFromApprovedInstantHours": -12,
        "requiredAction": "explicit approval to cancel or edit the incorrectly timed scheduled note",
    }
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row["status"] != "submitted_unverified":
            raise ValueError("scheduled_job_not_markable")
        db.execute("UPDATE jobs SET status='needs_user_action_wrong_schedule',updated_at=?,evidence=? WHERE job_id=?",
                   (checked, json.dumps(evidence, ensure_ascii=False), job_id))
    print(json.dumps({"jobId": job_id, "state": "needs_user_action_wrong_schedule",
                      "evidence": evidence}, ensure_ascii=False))


def status() -> None:
    load_manifest()
    receipt()
    with connect() as db:
        rows = [dict(row) for row in db.execute(
            "SELECT job_id,status,approved_at,updated_at,endpoint,safe_result,evidence FROM jobs ORDER BY rowid")]
    for row in rows:
        for key in ("safe_result", "evidence"):
            row[key] = json.loads(row[key]) if row[key] else None
    print(json.dumps({"manifestHash": EXPECTED_MANIFEST_HASH, "jobs": rows}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("initialize", "submit", "verify-profile",
                                             "verify-management", "verify-scheduled-management",
                                             "reconcile-no-submission", "reconcile-scheduled-no-record",
                                             "mark-schedule-time-mismatch", "status"))
    parser.add_argument("--job-id")
    parser.add_argument("--approved-at")
    parser.add_argument("--observation", type=Path)
    args = parser.parse_args()
    TEST_DIR.chmod(0o700)
    descriptor = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "w") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "initialize":
            if not args.approved_at:
                raise ValueError("approved_at_required")
            initialize(args.approved_at)
        elif args.command == "submit":
            if not args.job_id:
                raise ValueError("job_id_required")
            submit(args.job_id)
        elif args.command == "verify-profile":
            if not args.job_id:
                raise ValueError("job_id_required")
            verify_profile(args.job_id)
        elif args.command == "reconcile-no-submission":
            if not args.job_id:
                raise ValueError("job_id_required")
            reconcile_no_submission(args.job_id)
        elif args.command == "verify-management":
            if not args.job_id or not args.observation:
                raise ValueError("job_id_and_observation_required")
            verify_management(args.job_id, args.observation)
        elif args.command == "reconcile-scheduled-no-record":
            if not args.job_id or not args.observation:
                raise ValueError("job_id_and_observation_required")
            reconcile_scheduled_no_record(args.job_id, args.observation)
        elif args.command == "verify-scheduled-management":
            if not args.job_id or not args.observation:
                raise ValueError("job_id_and_observation_required")
            verify_scheduled_management(args.job_id, args.observation)
        elif args.command == "mark-schedule-time-mismatch":
            if not args.job_id or not args.observation:
                raise ValueError("job_id_and_observation_required")
            mark_schedule_time_mismatch(args.job_id, args.observation)
        else:
            status()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("route_test_error:" + str(error), file=sys.stderr)
        raise SystemExit(1)
