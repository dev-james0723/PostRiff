"""Deterministic JSON hashing for immutable Phase 0 records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical_hash(value: Mapping[str, object]) -> str:
    """Return a stable SHA-256 digest for a JSON-compatible mapping."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
