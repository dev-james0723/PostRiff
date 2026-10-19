"""Explicit server-held X application access evidence; no provider probing."""
import hashlib
import json
import math
import re


def load_evidence(values, client_id, now):
    try:
        raw = values.get("POSTRIFF_OAUTH_X_ACCESS_EVIDENCE_JSON", "")
        if not isinstance(raw, str) or len(raw) > 8000:
            return {}
        record = json.loads(raw)
        if not isinstance(record, dict) or record.get("version") != 1:
            return {}
        if record.get("clientBinding") != hashlib.sha256(client_id.encode()).hexdigest():
            return {}
        expires = record.get("expiresAt")
        reviewed = record.get("reviewedAt")
        if (type(expires) not in (int, float) or not math.isfinite(expires)
                or type(reviewed) not in (int, float) or not math.isfinite(reviewed)
                or not reviewed <= now < expires):
            return {}
        reference = record.get("evidenceRef")
        if not isinstance(reference, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,239}", reference):
            return {}
        entitlements = record.get("entitlements")
        if not isinstance(entitlements, list) or not all(v in ("x_api_v2", "enterprise") for v in entitlements):
            return {}
        receipt = record.get("ordinaryCustomerOauthReceipt")
        public = isinstance(receipt, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,239}", receipt))
        return {"entitlements": frozenset(entitlements), "expiresAt": expires,
                "evidenceRef": reference, "publicCustomerVerified": public,
                "ordinaryCustomerOauthReceipt": receipt if public else None}
    except (ValueError, TypeError):
        return {}


def current_access(adapter, now):
    record = getattr(adapter, "x_access_evidence", {})
    if not isinstance(record, dict) or record.get("expiresAt", 0) <= now:
        return {"entitlements": frozenset(), "publicCustomerVerified": False}
    return record
