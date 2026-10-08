"""Evidence redaction (public repository: evidence must carry no secret, session, signed URL or private record content).

`scan(value)` walks any JSON-able value and returns findings (path, kind); `assert_clean(value)` raises before anything is
written. `scrub_text` replaces the matched spans for log excerpts. The live runner, the API corpus and the browser scenes all
pass their evidence through this before writing a file. It is deliberately conservative: a false positive blocks a write and
is fixed by recording less, never by weakening the pattern.
"""
from __future__ import annotations

import re

PATTERNS = (
    ("bearer", re.compile(r"(?i)\bbearer\s+(?!dev:[0-9a-f-]{36}\b)[A-Za-z0-9._~+/=-]{16,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}")),
    ("api_token", re.compile(r"\bprt_[A-Za-z0-9_-]{16,}")),
    ("vercel_token", re.compile(r"(?i)\b(?:vercel_|x-vercel-protection-bypass[\"']?\s*[:=]\s*[\"']?)[A-Za-z0-9]{16,}")),
    ("signed_url", re.compile(r"(?i)[?&](?:token|signature|sig|x-amz-signature|x-goog-signature|expires)=[^&\s\"']{8,}")),
    ("supabase_storage", re.compile(r"(?i)/storage/v1/object/(?:sign|authenticated)/")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("cookie", re.compile(r"(?i)(?:__Host-rafii-control|sb-[a-z0-9]+-auth-token|_vercel_jwt)=[^;\s\"']{8,}")),
    ("dsn_password", re.compile(r"(?i)postgres(?:ql)?://[^:\s/]+:[^@\s]{4,}@")),
)
# OpenUI-lang statements (`name = Component(...)`): canonical source is private conversation content and stays out of
# metadata evidence; hashes and counts are recorded instead.
DSL_LINE = re.compile(r"(?m)^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:[A-Z][A-Za-z0-9_]*\(|Query\(|Mutation\(|@)")
SENSITIVE_KEYS = {"authorization", "cookie", "setcookie", "token", "bearer", "password", "secret", "apikey", "openaiapikey", "canonicalsource",
                  "candidatesource", "basesource", "patchsource", "checkpointsource", "fallbacktext", "body", "answertext", "draft", "transcript",
                  "samples", "instruction"}


def scan(value, path="$", *, allow_dsl=False) -> list[dict]:
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            low = str(key).lower().replace("-", "").replace("_", "")
            if low in SENSITIVE_KEYS and isinstance(item, str) and item:
                found.append({"path": f"{path}.{key}", "kind": "sensitive_key"})
                continue
            found.extend(scan(item, f"{path}.{key}", allow_dsl=allow_dsl))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(scan(item, f"{path}[{index}]", allow_dsl=allow_dsl))
    elif isinstance(value, str):
        for kind, pattern in PATTERNS:
            if pattern.search(value):
                found.append({"path": path, "kind": kind})
        if not allow_dsl and DSL_LINE.search(value):
            found.append({"path": path, "kind": "dsl_source"})
    return found


def assert_clean(value, *, allow_dsl=False) -> None:
    findings = scan(value, allow_dsl=allow_dsl)
    if findings:
        raise ValueError("evidence would leak private material: " + ", ".join(f"{f['kind']}@{f['path']}" for f in findings[:10]))


def scrub_text(text: str) -> str:
    out = str(text)
    for kind, pattern in PATTERNS:
        out = pattern.sub(f"[{kind}]", out)
    return DSL_LINE.sub("[dsl]", out)
