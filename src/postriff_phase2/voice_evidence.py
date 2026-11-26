"""Deterministic evidence rules for imported posts (voice import, spec 5.2): language, originality, authorship,
lineage, duplicates and the coverage receipt.

Everything here is pure except `eligible_posts`, `groups` and `coverage`, which read through a cursor they are handed
(tables from migration 140; callers use them only where voice import is mounted, see `available`).

Nothing here guesses who wrote a post or whether a model wrote it. Authorship comes from the consent given for the
account (`mine` → self, `my_organisation` → team, `mixed_authors` → unknown) and from the person's own corrections;
"published by Rafii" comes only from Rafii's own publish journal. Unknown stays unknown.

Language tags are a script-and-marker heuristic, not language identification: `en` is English or Latin-script text with
no sign of another language, `yue` needs a written-Cantonese marker, `zh-Hant` / `zh-Hans` are decided by characters
that differ between the scripts (Chinese with no such character is reported as `zh-Hant`), `mixed` is real
Chinese-English code-switching, and everything else (Japanese, Korean, other scripts, recognisably non-English Latin
text, no letters at all) is `und`.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache

MIN_CHARS = 20                 # normalised text shorter than this is no evidence of a voice
LANGUAGES = ("en", "zh-Hant", "zh-Hans", "yue", "mixed", "und")
ORIGINALITY = ("original", "reply", "quote", "repost", "unknown")
AUTHORSHIP = {"mine": "self", "my_organisation": "team", "mixed_authors": "unknown"}
# One reason per excluded post, in this order of precedence (resolve_status). The spec's coverage shape names the first
# six; `manual` is the person's own "do not use this post".
EXCLUSIONS = ("repost", "rafii_published", "manual", "other_author", "outdated", "too_short", "duplicate")
COVERAGE_EXCLUSIONS = ("repost", "duplicate", "rafii_published", "too_short", "other_author", "outdated", "manual")
ACTIVE_RUNS = ("pending", "receiving", "running")
BRAND = "brand"
PROVIDER_BY_PLATFORM = {"Threads": "threads", "Instagram": "instagram", "LinkedIn": "linkedin", "X": "x", "Facebook": "facebook",
                        "Bluesky": "bluesky", "Mastodon": "mastodon"}
# Providers whose post ids are unique across accounts, so an export row (which has no connection) can be matched to
# the publish journal by id. Mastodon ids repeat across servers and Bluesky record keys across accounts: those are
# matched by connection or by text only.
GLOBAL_ID_PROVIDERS = frozenset({"threads", "instagram", "linkedin", "x", "facebook"})
# Rafii stores a Bluesky post as its full at:// address; the importer knows it by its record key.
_AT_RECORD_KEY = re.compile(r"at://[^/\s]{1,260}/app\.bsky\.feed\.post/([A-Za-z0-9._~:-]{1,64})")

_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_MENTION = re.compile(r"(?<![\w@.])@\w[\w.\-]*(?:@\w[\w.\-]*)?")
_HASHTAG = re.compile(r"(?<!\w)#(\w+)")
_TRAILING_TAGS = re.compile(r"(?:\s*(?<!\w)#\w+)+\s*$")
_SPACE = re.compile(r"\s+")
_HAN = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ebef]")
_KANA = re.compile("[ぁ-ゖァ-ヺㇰ-ㇿｦ-ﾝ]")
_HANGUL = re.compile("[ᄀ-ᇿ㄰-㆏가-힯]")
_LATIN_LETTER = re.compile("[A-Za-zÀ-ɏ]")
_LATIN_WORD = re.compile("[A-Za-zÀ-ɏ]+(?:'[A-Za-z]+)*")
_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

_ENGLISH = frozenset("""
a about above after again against all am an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers him his how i if in into is
it its just me more most my new no nor not now of off on once only or other our out over own same she should so some such than
that the their them then there these they this those through to today tomorrow tonight too under until up us very was we were
what when where which while who why will with would yes you your thank thanks get got let lets
don't isn't it's i'm we're you're that's what's let's can't won't i've we've i'll we'll doesn't didn't aren't wasn't
""".split())
_FOREIGN = frozenset("""
el la los las le les des du que qui quoi et est une der das und ist nicht il gli por para pour avec dans sur mais donc
yang dan itu ini je nous vous ich wir ein eine mit auf von es un una uno del al se su sus pero como muy son hay hoy
esta este esto ese eso nos sommes sont tous toutes aussi alors oui non tout cette ces mon ma mes ton ta tes notre votre leur
och att det som inte jag vi har een het niet van voor zijn dat wij zij ook wel maar
untuk dengan pada adalah tidak akan saya kami kita mereka ada juga atau sudah belum bisa karena jadi lagi
""".split())
# Markers that are weak on their own (they also occur inside ordinary written Chinese, e.g. 好正常, 鋼琴日記, 聽日本歌):
# every multi-character marker, and these single characters. One weak hit never makes a text Cantonese.
_WEAK_CANTONESE = frozenset("係咁睇畀俾囉嘞啫吖咪")


@lru_cache(maxsize=1)
def _markers():
    """(strong Cantonese characters, every colloquial marker, compounds to ignore, Simplified-only, Traditional-only)
    from the shared humanizer pattern data, so one list serves both. Empty when that data file is missing."""
    try:
        from .coworker.humanizer import patterns
        data = patterns()
    except Exception:  # noqa: BLE001 - classification must still work without the optional pattern data
        data = {}
    cantonese = data.get("yue") or {}
    markers = tuple(m for m in cantonese.get("colloquial_markers") or [] if isinstance(m, str) and m)
    strong = frozenset(m for m in markers if len(m) == 1 and m not in _WEAK_CANTONESE) | ({"哋"} if markers else set())
    scripts = (data.get("zh") or {}).get("script_markers") or {}
    return (strong, markers, tuple(c for c in cantonese.get("exclude_compounds") or [] if isinstance(c, str) and c),
            frozenset(scripts.get("hans_only") or ""), frozenset(scripts.get("hant_only") or ""))


@lru_cache(maxsize=8192)
def _script(character):
    """'hans' or 'hant' for a character only one script uses, else None. The shared pattern data names the most common
    ones; for the rest, a character GB 2312 can encode and Big5 cannot is Simplified-only, and the reverse."""
    _, _, _, hans_only, hant_only = _markers()
    if character in hans_only:
        return "hans"
    if character in hant_only:
        return "hant"

    def encodes(codec):
        try:
            character.encode(codec)
            return True
        except UnicodeEncodeError:
            return False
    simplified, traditional = encodes("gb2312"), encodes("big5")
    return "hans" if simplified and not traditional else "hant" if traditional and not simplified else None


def _chinese(text):
    strong, markers, compounds, _, _ = _markers()
    plain = text
    for compound in compounds:
        plain = plain.replace(compound, " ")
    if any(character in strong for character in plain) or sum(1 for marker in markers if marker in plain) >= 2:
        return "yue"
    votes = [_script(character) for character in _HAN.findall(text)]
    return "zh-Hans" if votes.count("hans") > votes.count("hant") else "zh-Hant"


def _latin(words):
    english = sum(1 for word in words if word in _ENGLISH)
    foreign = sum(1 for word in words if word in _FOREIGN or not word.isascii())
    if foreign > english or (len(words) >= 4 and not english):
        return "und"
    return "en"


def detect_language(text: str) -> str:
    """One of `LANGUAGES` for a post's text. Links, handles and hashtags are ignored (an English hashtag under a
    Chinese caption is not code-switching)."""
    if not isinstance(text, str):
        return "und"
    value = unicodedata.normalize("NFKC", text).replace("’", "'")
    value = _HASHTAG.sub(" ", _MENTION.sub(" ", _URL.sub(" ", value)))
    han, kana, hangul = len(_HAN.findall(value)), len(_KANA.findall(value)), len(_HANGUL.findall(value))
    words = [word.casefold() for word in _LATIN_WORD.findall(value)]
    letters = sum(1 for character in value if character.isalpha())
    other = max(0, letters - han - kana - hangul - len(_LATIN_LETTER.findall(value)))
    latin = 2 * len(words)       # one Latin word weighs about as much as two Han characters
    total = han + kana + hangul + other + latin
    if not total:
        return "und"
    if (kana + hangul + other) * 100 >= 15 * total:
        return "und"             # Japanese, Korean or another script: never labelled Chinese or English
    if han >= 2 and len(words) >= 2 and min(han, latin) * 10 >= 3 * (han + latin):
        return "mixed"
    return _chinese(value) if han >= latin else _latin(words)


def normalise(text: str) -> str:
    """The text two copies of one post share: Unicode-folded, links and handles removed, layout lines dropped (a line
    with no letter or digit: spacer dots, a rule, emoji), a trailing block of hashtags removed (an inline hashtag keeps
    its word), whitespace collapsed, case folded."""
    if not isinstance(text, str):
        return ""
    value = unicodedata.normalize("NFKC", text)
    value = _MENTION.sub(" ", _URL.sub(" ", value))
    value = "\n".join(line for line in value.splitlines() if any(character.isalnum() for character in line))
    value = _HASHTAG.sub(r"\1", _TRAILING_TAGS.sub("", value))
    return _SPACE.sub(" ", value).strip().casefold()


def norm_hash(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def body_hash(text: str) -> str:
    """Hash of the exact stored text: a changed hash is a new revision of the post."""
    return hashlib.sha256((text if isinstance(text, str) else "").encode("utf-8")).hexdigest()


def too_short(text: str) -> bool:
    return len(normalise(text)) < MIN_CHARS


def resolve_status(*, originality, generation_origin, authorship, label, manual, too_short, duplicate):
    """(status, exclusion reason) from a post's facts; one reason per post, in the order of `EXCLUSIONS`. A post is
    `eligible` only when nothing excludes it and its author is known; with an unknown author it waits as `retrieved`."""
    for applies, reason in ((originality == "repost", "repost"), (generation_origin == "rafii_published", "rafii_published"),
                            (bool(manual), "manual"), (authorship == "guest", "other_author"), (label == "outdated", "outdated"),
                            (bool(too_short), "too_short"), (bool(duplicate), "duplicate")):
        if applies:
            return "excluded", reason
    return ("retrieved", None) if authorship not in ("self", "team") else ("eligible", None)


def journal(state) -> set:
    """Keys of the posts Rafii itself published, from the workspace's publish journal (`state.phase2.jobs`):
    (connection id, provider post id) for every job a provider acknowledged; ("provider:<id>", post id) where post ids
    are unique across accounts, so an export row can match; and ("#text", norm_hash) of the approved text, for exports
    that carry no provider id at all. A job without a provider reference published nothing and matches nothing."""
    keys = set()
    jobs = ((state or {}).get("phase2") or {}).get("jobs") if isinstance(state, dict) and isinstance((state or {}).get("phase2"), dict) else None
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or not job.get("providerReference"):
            continue
        reference = str(job["providerReference"])
        manifest = job.get("manifest") if isinstance(job.get("manifest"), dict) else {}
        if isinstance(manifest.get("channelId"), str) and manifest["channelId"]:
            keys.add((manifest["channelId"], reference))
            record = _AT_RECORD_KEY.fullmatch(reference)
            if record:
                keys.add((manifest["channelId"], record.group(1)))
        provider = PROVIDER_BY_PLATFORM.get(manifest.get("platform"))
        if provider in GLOBAL_ID_PROVIDERS:
            keys.add(("provider:" + provider, reference))
        payload = manifest.get("payload") if isinstance(manifest.get("payload"), dict) else {}
        if isinstance(payload.get("text"), str) and not too_short(payload["text"]):
            keys.add(("#text", norm_hash(payload["text"])))
    return keys


def classify(item: dict, *, consent: dict, journal: set) -> dict:
    """Facts for one incoming post: `{language, originality, authorship, generation_origin, status, exclusion_reason,
    body_hash, norm_hash, content_type}`. `item` carries `text`, `kind`, `externalId` and, where known, `connectionId`,
    `provider` and `contentType`. `journal` is `journal(state)`."""
    text = item.get("text") if isinstance(item.get("text"), str) else ""
    kind = item.get("kind")
    originality = kind if isinstance(kind, str) and kind in ORIGINALITY[:4] else "unknown"
    authorship = AUTHORSHIP.get((consent or {}).get("ownership") if isinstance(consent, dict) else None, "unknown")
    hashed, short = norm_hash(text), too_short(text)
    keys = set() if short else {("#text", hashed)}
    post_id = item.get("externalId")
    if isinstance(post_id, str) and post_id:
        if isinstance(item.get("connectionId"), str) and item["connectionId"]:
            keys.add((item["connectionId"], post_id))
        if item.get("provider") in GLOBAL_ID_PROVIDERS:
            keys.add(("provider:" + item["provider"], post_id))
    origin = "rafii_published" if keys & set(journal or ()) else "unknown"
    status, reason = resolve_status(originality=originality, generation_origin=origin, authorship=authorship, label=None,
                                    manual=False, too_short=short, duplicate=False)
    content_type = item.get("contentType").lower() if isinstance(item.get("contentType"), str) else ""
    return {"language": detect_language(text), "originality": originality, "authorship": authorship, "generation_origin": origin,
            "status": status, "exclusion_reason": reason, "body_hash": body_hash(text), "norm_hash": hashed,
            "content_type": content_type if _SLUG.match(content_type) else "post"}


# --- voice groups ---------------------------------------------------------------------------------------------------
def group_key(voice_scope, provider, account_key) -> str:
    """`brand` for every account blended into the workspace's one brand voice; an account kept separate is its own group."""
    return BRAND if voice_scope != "separate" else f"separate:{provider}:{account_key}"


def parse_group_key(key):
    """(scope, provider, account key) for a group key; None for anything else. No key means the brand group."""
    if key is None or key == BRAND:
        return BRAND, None, None
    if not isinstance(key, str) or not key.startswith("separate:"):
        return None
    provider, _, account = key[len("separate:"):].partition(":")
    return ("separate", provider, account) if provider and account else None


def fold_groups(rows, labels) -> list:
    """rows: (provider, account_key, voice_scope, eligible count); labels: {(provider, account_key): label}."""
    brand = {"key": BRAND, "label": "Brand voice", "accounts": [], "eligible": 0}
    separate = {}
    for provider, account_key, scope, eligible in sorted(rows, key=lambda row: (row[0], row[1])):
        account = {"provider": provider, "accountKey": account_key, "label": labels.get((provider, account_key)) or account_key}
        if scope == "separate":
            group = separate.setdefault(group_key(scope, provider, account_key),
                                        {"key": group_key(scope, provider, account_key), "label": account["label"], "accounts": [], "eligible": 0})
        else:
            group = brand
        group["accounts"].append(account)
        group["eligible"] += int(eligible or 0)
    return [brand] + [separate[key] for key in sorted(separate)]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def available(cur) -> bool:
    """True once migration 140 is applied. The three readers below assume it."""
    cur.execute("SELECT to_regclass('public.pr_voice_posts') IS NOT NULL")
    return bool(cur.fetchone()[0])


def _labels(cur, workspace_id):
    cur.execute("""SELECT DISTINCT ON (provider, account_key) provider, account_key, account_label FROM public.pr_voice_imports
                   WHERE workspace_id=%s ORDER BY provider, account_key, created_at DESC""", (workspace_id,))
    return {(provider, account_key): label for provider, account_key, label in cur.fetchall() if label}


def groups(cur, workspace_id) -> list:
    """One `brand` group plus one group per account kept separate: `{key, label, accounts[], eligible}`."""
    cur.execute("""SELECT provider, account_key, voice_scope, count(*) FILTER (WHERE status='eligible') FROM public.pr_voice_posts
                   WHERE workspace_id=%s AND status<>'gone' GROUP BY provider, account_key, voice_scope""", (workspace_id,))
    rows = cur.fetchall()
    return fold_groups(rows, _labels(cur, workspace_id))


def eligible_posts(cur, workspace_id, *, group_key=None, limit=None) -> list:
    """The posts that count as evidence for one voice group, newest first. Each row is a dict with `id, provider,
    account_key, published_at, body, language, content_type, voice_scope, permalink` (`published_at` an ISO 8601 string
    or None). No `group_key` means the brand group: an account kept separate is only ever read by its own key, so two
    voices are never blended by default. An unknown key reads nothing."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    parsed = parse_group_key(group_key)
    if parsed is None:
        return []
    scope, provider, account = parsed
    where, params = "voice_scope='brand'", [workspace_id]
    if scope == "separate":
        where, params = "voice_scope='separate' AND provider=%s AND account_key=%s", [workspace_id, provider, account]
    sql = f"""SELECT id::text, provider, account_key, published_at, body, language, content_type, voice_scope, permalink
              FROM public.pr_voice_posts WHERE workspace_id=%s AND status='eligible' AND {where}
              ORDER BY published_at DESC NULLS LAST, id"""
    if limit is not None:
        sql, params = sql + " LIMIT %s", params + [limit]
    cur.execute(sql, tuple(params))
    keys = ("id", "provider", "account_key", "published_at", "body", "language", "content_type", "voice_scope", "permalink")
    return [dict(zip(keys, (row[0], row[1], row[2], _iso(row[3]), *row[4:]))) for row in cur.fetchall()]


# --- coverage receipt -------------------------------------------------------------------------------------------------
def _proposal_states(state):
    speaker = state.get("speaker") if isinstance(state, dict) else None
    speaker = speaker if isinstance(speaker, dict) else {}
    proposed, approved = "none", "none"
    provisional = speaker.get("provisional")
    if isinstance(provisional, dict) and provisional.get("analysisMethod") == "voice_import":
        proposed = "partial" if provisional.get("status") == "stale" else "done"
    revisions = speaker.get("revisions") if isinstance(speaker.get("revisions"), list) else []
    active = next((r for r in revisions if isinstance(r, dict) and r.get("revision") == speaker.get("activeRevision")), None)
    if active and isinstance(active.get("profile"), dict) and active["profile"].get("analysisMethod") == "voice_import":
        approved = "partial" if active.get("stale") else "done"
    return proposed, approved


def fold_coverage(post_rows, import_rows, state) -> dict:
    """The coverage receipt (spec 5.1) from two aggregates.

    post_rows: (provider, account_key, voice_scope, status, exclusion_reason, language, count, oldest, newest) for every
    stored post that is not `gone`; import_rows: each account's latest run as (provider, account_key, label, route,
    status, more_remaining, total_known, voice_scope). Dates are ISO 8601 strings in UTC.

    `states` are `none | pending | partial | done`. `excluded` adds `manual` (the person's own exclusion) to the six
    reasons, so retrieved − eligible − sum(excluded) is the number of posts still waiting for an author. `languages`
    counts the writing still in play (eligible or waiting), not reposts or other exclusions. An unknown remainder
    (`moreRemaining: null`) is never reported as "no more"."""
    accounts = {}

    def account(provider, account_key):
        return accounts.setdefault((provider, account_key), {
            "provider": provider, "accountKey": account_key, "label": account_key, "route": None, "voiceScope": None, "retrieved": 0,
            "eligible": 0, "excluded": {reason: 0 for reason in COVERAGE_EXCLUSIONS}, "languages": {},
            "observed": {"oldest": None, "newest": None}, "moreRemaining": None, "totalKnown": False})

    active = incomplete = False
    for provider, account_key, label, route, status, more_remaining, total_known, scope in import_rows:
        entry = account(provider, account_key)
        entry.update(label=label or account_key, route=route, voiceScope=scope, moreRemaining=more_remaining, totalKnown=bool(total_known))
        active = active or status in ACTIVE_RUNS
        incomplete = incomplete or status in ("failed", "cancelled") or more_remaining is True
    total = 0
    for provider, account_key, scope, status, reason, language, count, oldest, newest in post_rows:
        entry, count = account(provider, account_key), int(count or 0)
        entry["voiceScope"] = scope or entry["voiceScope"]
        entry["retrieved"] += count
        total += count
        if status == "eligible":
            entry["eligible"] += count
        elif status == "excluded":
            entry["excluded"][reason if reason in entry["excluded"] else "manual"] += count
        if status in ("eligible", "retrieved"):
            entry["languages"][language] = entry["languages"].get(language, 0) + count
        observed = entry["observed"]
        if oldest and (observed["oldest"] is None or oldest < observed["oldest"]):
            observed["oldest"] = oldest
        if newest and (observed["newest"] is None or newest > observed["newest"]):
            observed["newest"] = newest
    proposed, approved = _proposal_states(state)
    states = {"connected": "done" if import_rows else "none",
              "retrieved": ("pending" if active else "none") if not total else "partial" if active or incomplete else "done",
              "processed": "none" if not total else "partial" if active else "done",
              "proposed": proposed, "approved": approved}
    return {"states": states, "accounts": [accounts[key] for key in sorted(accounts)],
            "modality": {"text": "analysed", "images": "not_analysed", "video": "not_analysed"}}


def coverage(cur, workspace_id, state) -> dict:
    """What was connected, retrieved, processed, proposed and approved, per account, with truthful unknowns."""
    cur.execute("""SELECT provider, account_key, voice_scope, status, exclusion_reason, language, count(*), min(published_at), max(published_at)
                   FROM public.pr_voice_posts WHERE workspace_id=%s AND status<>'gone'
                   GROUP BY provider, account_key, voice_scope, status, exclusion_reason, language""", (workspace_id,))
    posts = [(*row[:7], _iso(row[7]), _iso(row[8])) for row in cur.fetchall()]
    cur.execute("""SELECT DISTINCT ON (provider, account_key) provider, account_key, account_label, route, status, more_remaining, total_known,
                          consent->>'voiceScope'
                   FROM public.pr_voice_imports WHERE workspace_id=%s ORDER BY provider, account_key, created_at DESC""", (workspace_id,))
    return fold_coverage(posts, cur.fetchall(), state)
