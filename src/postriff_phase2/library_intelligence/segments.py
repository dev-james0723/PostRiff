"""Normalized content segments with structural locators (engineering spec §4 ContentSegment, §7; T03).

Every derived passage, page, slide, sheet row, transcript line, OCR page or saved moment is one row in
`pr_library_segments`, bound to one immutable version (`version_key`) and its content hash. Writes never delete:
reprocessing supersedes the previous rows of the same extractor, and a human correction is a new `origin='user'` row
that points at the row it corrects (`correction_of`) with the same locator, so citations and time alignment survive
edits. Machine output never overwrites a human row; when a re-run produces a passage that a person already corrected,
the new guess is stored as history behind the correction instead of becoming active.

Language labels come from a script heuristic, not a model: Cantonese particles versus Standard Written Chinese,
Traditional versus Simplified characters, and Latin-script English. Mixed segments are labelled code-switched rather
than forced into one language. Speakers are anonymous ("Speaker 1"); nothing here infers who is speaking.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import uuid

from postriff_alpha.domain import AlphaError

from . import contracts as c
from . import policy, textnorm, versions

KINDS = ("text", "page", "slide", "sheet", "transcript", "ocr", "caption", "scene", "moment", "note", "metadata")
MACHINE_ORIGINS = ("extracted", "ocr", "transcript", "ai_suggested")
MAX_TEXT = 20000
MAX_SEGMENTS = 20000
INSERT_BATCH = 100
PAGE_LIMIT, MAX_PAGE_LIMIT = 200, 500
USER_EXTRACTOR, MOMENT_EXTRACTOR = "user-correction", "user-moment"
LANGUAGE = re.compile(r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")
SPEAKER_MAX = 60
COLUMNS = ("id", "workspace_id", "asset_key", "version_key", "ordinal", "kind", "text", "language", "locator", "extractor", "extractor_version",
           "text_hash", "source_sha256", "speaker_label", "origin", "uncertainty", "correction_of", "created_by", "normalizer_version", "search_terms")
SELECT = ("SELECT id,ordinal,kind,text,language,locator,speaker_label,origin,uncertainty,extractor,extractor_version,correction_of,"
          "(superseded_at IS NOT NULL),extract(epoch from created_at) FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s "
          "AND (%s OR superseded_at IS NULL) AND (ordinal>%s OR (ordinal=%s AND id>%s)) ORDER BY ordinal,id LIMIT %s")
ZERO = uuid.UUID(int=0)


def job_attr(job, name, default=None):
    """Worker A's JobContext may be an object or a mapping; processors read it through this one adapter."""
    if isinstance(job, dict):
        return job.get(name, default)
    return getattr(job, name, default)


def job_raw(job) -> bytes:
    raw = job_attr(job, "raw")
    return raw() if callable(raw) else raw


def outcome(state: str, *, segments=(), annotations=(), media=None, provider=None, error=None, detail=None, retryable=False, extractor=None,
            extractor_version=None, replace_fields=None) -> dict:
    """The processor Outcome shape from OWNER-MAP §A, plus the extractor identity `write_segments` needs and the
    (field, origin) pairs a re-run of this processor replaces in `write_annotations`."""
    if state not in c.CAPABILITY_STATES:
        c.fail("Unknown processing state.", 500, "library_internal")
    return {"state": state, "segments": list(segments), "annotations": list(annotations), "embeddings": [], "media": dict(media or {}),
            "provider": provider, "errorCode": error, "detail": (detail or None) and str(detail)[:300], "retryable": bool(retryable),
            "extractor": extractor, "extractorVersion": extractor_version, "replaceFields": [list(x) for x in (replace_fields or [])]}


def register_processors(processors: list[dict]) -> bool:
    """Register with worker A's capability registry when it exists; otherwise the coordinator wires `PROCESSORS`."""
    try:
        from . import capabilities
    except ImportError:
        return False
    register = getattr(capabilities, "register", None)
    if not callable(register):
        return False
    for processor in processors:
        register(processor)
    return True


# --- language heuristic ----------------------------------------------------------------------------------------------
# Particles and words that are characteristic of written Cantonese and rare in Standard Written Chinese.
CANTONESE = frozenset("係嘅咗唔佢冇啲嚟喺乜嘢噉哋啱睇搵畀咩囉㗎嗰喎嘞啩吖")
# Standard Chinese words whose characters overlap the Cantonese list (關係 'relationship' is not the copula 係).
CANTONESE_FALSE_FRIENDS = ("關係", "联係", "聯係", "干係", "係數", "嘅然")
SIMPLIFIED = frozenset(textnorm.S2T)
TRADITIONAL = frozenset(textnorm.S2T.values())
HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
KANA = re.compile(r"[぀-ヿ]")
HANGUL = re.compile(r"[가-힯]")
LATIN_WORD = re.compile(r"[A-Za-zÀ-ɏ]+(?:['’][A-Za-z]+)?")
ENGLISH = frozenset("the a an and or but of to in on at for with from by is are was were be been it this that these those we you i he she they "
                    "my our your their me us them not no yes do does did have has had will would can could should shall may might "
                    "then than so if as about into over after before again all just also very there here what when where who how why".split())
OTHER_LATIN = frozenset("le la les des est et une pour avec dans du au aux el los las del que por con una para y der die das und ist nicht mit "
                        "ein eine il che non per della di nao não uma com os das".split())


def detect_language(text: str) -> dict:
    """{language, languages, codeSwitched, script}. `language` is the dominant BCP-47-style code (yue, zh-Hant, zh-Hans,
    zh, en, ja, ko) or None when the text gives no reliable signal. Never a guess about the speaker."""
    text = str(text or "")
    han = HAN.findall(text)
    words = LATIN_WORD.findall(text)
    out = {"language": None, "languages": [], "codeSwitched": False, "script": None}
    chinese = None
    if han:
        scrubbed = text
        for word in CANTONESE_FALSE_FRIENDS:
            scrubbed = scrubbed.replace(word, "")
        markers = sum(1 for ch in scrubbed if ch in CANTONESE)
        trad = sum(1 for ch in han if ch in TRADITIONAL)
        simp = sum(1 for ch in han if ch in SIMPLIFIED)
        out["script"] = "Hant" if trad > simp else "Hans" if simp > trad else None
        if markers >= 2 or (markers >= 1 and (len(han) <= 16 or markers / len(han) >= 0.04)):
            chinese = "yue"
        else:
            chinese = {"Hant": "zh-Hant", "Hans": "zh-Hans"}.get(out["script"], "zh")
    if KANA.search(text):
        chinese = "ja"
    elif HANGUL.search(text) and not han:
        chinese = "ko"
    latin = None
    if words:
        lowered = [w.lower().replace("’", "'") for w in words]
        english = sum(1 for w in lowered if w in ENGLISH)
        other = sum(1 for w in lowered if w in OTHER_LATIN)
        if chinese:
            # In Hong Kong and Cantonese creator speech, embedded Latin words are English unless clearly otherwise.
            latin = None if other > english else "en"
        elif other > english:
            latin = None
        elif english or all(re.fullmatch(r"[A-Za-z']+", w) for w in words):
            latin = "en"
    cjk_weight = len(han) + len(KANA.findall(text)) + len(HANGUL.findall(text))
    if chinese and latin and len(words) >= 2 and cjk_weight >= 2:
        first, second = (chinese, latin) if cjk_weight >= len(words) * 1.5 else (latin, chinese)
        out.update(language=first, languages=[first, second], codeSwitched=True)
    elif chinese:
        out.update(language=chinese, languages=[chinese])
    elif latin:
        out.update(language=latin, languages=[latin])
    return out


LANGUAGE_NAMES = {"yue": "Cantonese", "zh-Hant": "Traditional Chinese", "zh-Hans": "Simplified Chinese", "zh": "Chinese", "en": "English",
                  "ja": "Japanese", "ko": "Korean"}


def code_switch_note(info: dict) -> str | None:
    if not info.get("codeSwitched"):
        return None
    return "code-switched " + "/".join(LANGUAGE_NAMES.get(x, x) for x in info["languages"])


# --- speakers --------------------------------------------------------------------------------------------------------
def clean_speaker_label(value) -> str | None:
    """A person may name a speaker however they like (their own assertion); the system never infers one."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > SPEAKER_MAX or re.search(r"[\x00-\x1f\x7f]", value):
        c.fail(f"Use a speaker label of at most {SPEAKER_MAX} characters.")
    return value.strip() or None


def anonymous_speakers(items: list[dict]) -> list[dict]:
    """Replace any provider speaker field (a diarization id, or a name some providers guess) with "Speaker N" in order
    of first appearance. The original value is dropped, never stored."""
    names: dict = {}
    out = []
    for item in items:
        item = dict(item)
        raw = item.pop("speaker", None)
        if raw is not None and str(raw).strip():
            names.setdefault(str(raw).strip(), f"Speaker {len(names) + 1}")
            item["speakerLabel"] = names[str(raw).strip()]
        else:
            item.setdefault("speakerLabel", None)
        out.append(item)
    return out


# --- writing ---------------------------------------------------------------------------------------------------------
def _uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _hex(value) -> str | None:
    return None if value is None else _uuid(value).hex


def _locator_json(value):
    if value is None:
        return None
    return value if isinstance(value, dict) else json.loads(value)


def bounds(cur, workspace_id, version: dict) -> dict:
    """Locator bounds for one version: the version's media merged with the stored row (a just-written preview or
    extraction may be newer than the caller's copy)."""
    media = dict(version.get("media") or {})
    if not version.get("legacy"):
        cur.execute("SELECT media FROM public.pr_library_assets WHERE workspace_id=%s AND id=%s", (workspace_id, uuid.UUID(hex=version["versionId"])))
        row = cur.fetchone()
        if row and isinstance(row[0], dict):
            media.update(row[0])

    def number(key):
        value = media.get(key)
        return value if type(value) is int and value > 0 else None

    return {"text_length": number("textLength"), "duration_ms": number("durationMs"), "pages": number("pages"), "slides": number("slides")}


def _validate(item: dict, limits: dict, *, allow_user: bool = False) -> dict:
    if not isinstance(item, dict):
        c.fail("Each segment must be an object.")
    kind = item.get("kind")
    if kind not in KINDS:
        c.fail("Use a supported segment kind.")
    origin = item.get("origin") or "extracted"
    if origin not in MACHINE_ORIGINS and not (allow_user and origin == "user"):
        c.fail("Only a person's own edit creates a user segment.")
    text = item.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\x00" in text:
        c.fail(f"Each segment needs text of at most {MAX_TEXT} characters.")
    loc = item.get("locator")
    if loc is not None:
        loc = c.locator(loc, **limits)
    language = item.get("language", detect_language(text)["language"])
    if language is not None and (not isinstance(language, str) or not LANGUAGE.fullmatch(language)):
        c.fail("Use a language code such as yue, zh-Hant or en.")
    uncertainty = item.get("uncertainty")
    if uncertainty is not None and (not isinstance(uncertainty, str) or len(uncertainty) > 200):
        c.fail("Keep the uncertainty note short.")
    ordinal = item.get("ordinal")
    if ordinal is not None and (type(ordinal) is not int or not 0 <= ordinal <= 1_000_000):
        c.fail("Segment order is out of range.")
    return {"kind": kind, "origin": origin, "text": text, "locator": loc, "language": language, "uncertainty": uncertainty, "ordinal": ordinal,
            "speakerLabel": clean_speaker_label(item.get("speakerLabel"))}


def _row(workspace_id, version, item, *, extractor, extractor_version, created_by=None, correction_of=None, row_id=None):
    text = item["text"]
    return (row_id or uuid.uuid4(), workspace_id, version["assetId"], version["versionId"], item["ordinal"], item["kind"], text, item["language"],
            json.dumps(item["locator"]) if item["locator"] is not None else None, extractor, extractor_version,
            hashlib.sha256(text.encode()).hexdigest(), version.get("sha256") or None, item["speakerLabel"], item["origin"], item["uncertainty"],
            correction_of, created_by, textnorm.NORMALIZER_VERSION, textnorm.search_terms(text))


def _insert(cur, rows):
    placeholders = "(" + ",".join("%s::jsonb" if column == "locator" else "%s" for column in COLUMNS) + ")"
    for start in range(0, len(rows), INSERT_BATCH):
        batch = rows[start:start + INSERT_BATCH]
        cur.execute(f"INSERT INTO public.pr_library_segments({','.join(COLUMNS)}) VALUES " + ",".join([placeholders] * len(batch)),
                    tuple(v for row in batch for v in row))


def _overlap(a: dict, b: dict) -> bool:
    """True when machine locator `a` covers the same place as a human-corrected locator `b`."""
    if a is None or b is None or a.get("kind") != b.get("kind"):
        return False  # without a shared locator there is no trustworthy match, so nothing is hidden
    if a["kind"] == "time":
        shared = min(a["endMs"], b["endMs"]) - max(a["startMs"], b["startMs"])
        return shared > 0 and shared * 2 >= min(a["endMs"] - a["startMs"], b["endMs"] - b["startMs"])
    if a["kind"] == "text":
        shared = min(a["end"], b["end"]) - max(a["start"], b["start"])
        return (a == b) or (shared > 0 and shared * 2 >= min(a["end"] - a["start"], b["end"] - b["start"]))
    return a == b


def write_segments(cur, workspace_id, version: dict, items: list[dict], *, extractor: str, extractor_version: str, created_by=None) -> int:
    """Replace this extractor's active segments for one version. Returns the number of new active rows.

    Never deletes and never touches `origin='user'` rows. The whole batch is validated before any write."""
    if not isinstance(extractor, str) or not 1 <= len(extractor) <= 80 or extractor in (USER_EXTRACTOR, MOMENT_EXTRACTOR):
        c.fail("Name the extractor.")
    if not isinstance(extractor_version, str) or not 1 <= len(extractor_version) <= 80:
        c.fail("Name the extractor version.")
    if not isinstance(items, list) or len(items) > MAX_SEGMENTS:
        c.fail(f"Write at most {MAX_SEGMENTS} segments.")
    limits = bounds(cur, workspace_id, version)
    validated = []
    for n, raw in enumerate(items):
        item = _validate(raw, limits)
        if item["ordinal"] is None:
            item["ordinal"] = n
        validated.append(item)
    cur.execute("SELECT id,locator,kind FROM public.pr_library_segments WHERE workspace_id=%s AND version_key=%s AND origin='user' AND superseded_at IS NULL",
                (workspace_id, version["versionId"]))
    corrected = [(_locator_json(loc), kind) for _, loc, kind in cur.fetchall()]
    cur.execute("UPDATE public.pr_library_segments SET superseded_at=now() WHERE workspace_id=%s AND version_key=%s AND extractor=%s AND origin<>'user' "
                "AND superseded_at IS NULL", (workspace_id, version["versionId"], extractor))
    rows, shadowed = [], []
    for item in validated:
        row = _row(workspace_id, version, item, extractor=extractor, extractor_version=extractor_version, created_by=created_by)
        rows.append(row)
        if any(kind == item["kind"] and _overlap(item["locator"], loc) for loc, kind in corrected):
            shadowed.append(str(row[0]))
    if rows:
        _insert(cur, rows)
    if shadowed:
        cur.execute("UPDATE public.pr_library_segments SET superseded_at=now() WHERE workspace_id=%s AND id=ANY(%s::uuid[]) AND superseded_at IS NULL",
                    (workspace_id, shadowed))
    return len(rows) - len(shadowed)


# --- reading ----------------------------------------------------------------------------------------------------------
def to_contract(row) -> dict:
    sid, ordinal, kind, text, language, loc, speaker, origin, uncertainty, extractor, extractor_version, correction_of, superseded, created = row
    loc = _locator_json(loc)
    info = detect_language(text)
    out = {"id": _hex(sid), "ordinal": int(ordinal), "kind": kind, "text": text, "language": language, "languages": info["languages"],
           "locator": loc, "locatorLabel": c.locator_label(loc), "speakerLabel": speaker, "origin": origin, "uncertainty": uncertainty,
           "extractor": extractor, "extractorVersion": extractor_version, "correctionOf": _hex(correction_of), "superseded": bool(superseded),
           "createdAt": float(created) if created is not None else None}
    return out


def _cursor_token(version_key, history, row) -> str:
    raw = json.dumps({"v": version_key, "h": bool(history), "o": int(row[1]), "i": _hex(row[0])}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _parse_cursor(token, version_key, history):
    if token in (None, ""):
        return -1, -1, ZERO
    try:
        if not isinstance(token, str) or len(token) > 400:
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        if data.get("v") != version_key or data.get("h") != bool(history) or type(data.get("o")) is not int or not c.KEY.fullmatch(str(data.get("i"))):
            raise ValueError
        return data["o"], data["o"], uuid.UUID(hex=data["i"])
    except (ValueError, TypeError, AttributeError, binascii.Error, UnicodeDecodeError):
        raise AlphaError("This page link is invalid. Refresh the passages.", 409, code="library_cursor_stale") from None


def list_segments(ctx, version: dict, *, history: bool = False, cursor: str | None = None, limit: int = PAGE_LIMIT) -> dict:
    after, same, after_id = _parse_cursor(cursor, version["versionId"], history)
    ctx.cur.execute(SELECT, (ctx.workspace_id, version["versionId"], bool(history), after, same, after_id, limit + 1))
    rows = ctx.cur.fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    return {"segments": [to_contract(r) for r in rows], "nextCursor": _cursor_token(version["versionId"], history, rows[-1]) if more and rows else None}


def active_segments(ctx, version: dict, limit: int = 500) -> list[dict]:
    return list_segments(ctx, version, limit=limit)["segments"]


def segments_http(ctx, request):
    """GET .../assets/{key}/segments?cursor=&history=1&limit= — active passages (or the full correction history)."""
    query = request.get("query") or {}
    version = versions.get(ctx, request["params"]["key"])
    policy.require(policy.authorize_source(ctx, version, "browse"))
    history = str(query.get("history") or "") in ("1", "true", "yes")
    try:
        limit = int(query.get("limit") or PAGE_LIMIT)
    except ValueError:
        c.fail("Use a whole-number page size.")
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        c.fail(f"Use a page size from 1 to {MAX_PAGE_LIMIT}.")
    page = list_segments(ctx, version, history=history, cursor=query.get("cursor"), limit=limit)
    return {"contractVersion": c.CONTRACT_VERSION, "assetRef": versions.ref(version), "history": history, **page}


# --- human corrections ------------------------------------------------------------------------------------------------
def writable(ctx):
    """Edits need an editor in a non-sample workspace (the same rule as the existing Library metadata routes)."""
    ctx.require("edit")
    if (ctx.state.get("workspace") or {}).get("sample"):
        raise AlphaError("Hosted sample workspaces are read-only.", 403, code="sample_read_only")


KEEP = object()


def correct(ctx, segment_id, text, speaker_label=KEEP, *, version_key: str | None = None) -> dict:
    """Create a corrected copy of one active segment (`origin='user'`, same locator and order), supersede the old row
    and keep both for history. `speaker_label=None` keeps the current label; "" clears it."""
    writable(ctx)
    key = c.asset_key(segment_id)
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\x00" in text:
        c.fail(f"Use corrected text of 1 to {MAX_TEXT} characters.")
    ctx.cur.execute("SELECT id,asset_key,version_key,ordinal,kind,text,language,locator,extractor,extractor_version,source_sha256,speaker_label,origin,"
                    "(superseded_at IS NOT NULL) FROM public.pr_library_segments WHERE workspace_id=%s AND id=%s FOR UPDATE", (ctx.workspace_id, uuid.UUID(hex=key)))
    row = ctx.cur.fetchone()
    if not row:
        raise AlphaError("This passage is unavailable.", 404, code="library_unavailable")
    sid, _asset, row_version, ordinal, kind, _old, _language, loc, _ext, _ver, _sha, old_speaker, _origin, superseded = row
    if version_key is not None and row_version != version_key:
        raise AlphaError("This passage is unavailable.", 404, code="library_unavailable")
    version = versions.get(ctx, row_version)
    policy.require(policy.authorize_source(ctx, version, "browse"))
    if superseded:
        raise AlphaError("This passage changed since you opened it. Refresh and edit the current text.", 409, code="library_segment_changed")
    if kind == "moment":
        c.fail("Rename a saved moment instead of correcting it.")
    speaker = old_speaker if speaker_label is KEEP or speaker_label is None else clean_speaker_label(speaker_label)
    info = detect_language(text)
    uncertainty = "Corrected by a person" + (f"; {code_switch_note(info)}" if info["codeSwitched"] else "")
    item = {"kind": kind, "origin": "user", "text": text, "locator": _locator_json(loc), "language": info["language"], "uncertainty": uncertainty,
            "ordinal": int(ordinal), "speakerLabel": speaker}
    limits = bounds(ctx.cur, ctx.workspace_id, version)
    item = _validate(item, limits, allow_user=True)
    item["ordinal"] = int(ordinal)
    ctx.cur.execute("UPDATE public.pr_library_segments SET superseded_at=now() WHERE workspace_id=%s AND id=ANY(%s::uuid[]) AND superseded_at IS NULL",
                    (ctx.workspace_id, [str(_uuid(sid))]))
    if not ctx.cur.rowcount:
        raise AlphaError("This passage changed since you opened it. Refresh and edit the current text.", 409, code="library_segment_changed")
    new_id = uuid.uuid4()
    _insert(ctx.cur, [_row(ctx.workspace_id, version, item, extractor=USER_EXTRACTOR, extractor_version="1", created_by=ctx.actor,
                           correction_of=_uuid(sid), row_id=new_id)])
    return to_contract((new_id, item["ordinal"], kind, text, item["language"], item["locator"], speaker, "user", uncertainty, USER_EXTRACTOR, "1",
                        _uuid(sid), False, ctx.now))


def add_user_segment(ctx, version: dict, *, kind: str, text: str, locator: dict, extractor: str = MOMENT_EXTRACTOR) -> dict:
    """A person's own segment (a saved moment or a note). Validated against the version's bounds like any other."""
    writable(ctx)
    item = _validate({"kind": kind, "origin": "user", "text": text, "locator": locator}, bounds(ctx.cur, ctx.workspace_id, version), allow_user=True)
    item["ordinal"] = 1_000_000 if kind == "moment" else 0
    new_id = uuid.uuid4()
    _insert(ctx.cur, [_row(ctx.workspace_id, version, item, extractor=extractor, extractor_version="1", created_by=ctx.actor, row_id=new_id)])
    return to_contract((new_id, item["ordinal"], kind, text, item["language"], item["locator"], None, "user", None, extractor, "1", None, False, ctx.now))
