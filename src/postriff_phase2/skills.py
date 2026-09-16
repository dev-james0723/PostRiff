"""Skill binding for writing routes (agent chat design §7).

Which reviewed skill documents a run receives, chosen from the destinations and format of the
turn, and recorded by id, version and sha256 so every candidate is traceable to the exact
instructions it was written with. Skills carry the method; memory files carry the person: a
skill body never names a customer. The library is the generic `skills/postriff-*` set (or
`POSTRIFF_SKILLS_DIR`); a host without it (a hosted function) simply binds nothing and says so.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

SKILLS_DIR_ENV = "POSTRIFF_SKILLS_DIR"
CORE_SKILL = "postriff-content-craft"
CORE_REFERENCES = ("references/editorial-workflow.md", "references/human-voice-pass.md", "references/platform-playbooks.md")
VISUAL_REFERENCE = "references/visual-handoff.md"
# Write-time discovery: titles, hooks, hashtags, link placement, retention. The `postriff-discoverability`
# package plans a DiscoverabilityBrief instead, which a copy run's output schema cannot carry.
DISCOVERY_REFERENCE = "references/algorithm-practice.md"
VISUAL_FORMATS = {"carousel", "image_caption", "quote_card", "story", "short_video", "long_video"}
# Claim-level evidence discipline for turns that cite sources. Asset production
# (`postriff-social-graphics`) is not bound to a copy run: its half that shapes copy is VISUAL_REFERENCE.
RESEARCH_SKILL = "postriff-research-and-source-log"
RESEARCH_REFERENCES = ("references/provenance-ledger.md",)
# The voice contract. Its SKILL.md is what every draft needs; the rest is split into references
# so a turn carries the part it uses instead of a truncated whole. `references/operations.md` is
# operator documentation (queue routine, publishing chain, analytics) and is never bound here.
ENGINE_SKILL = "postriff-content-engine"
ENGINE_WORKFLOWS = "references/content-pillars-and-workflows.md"
ENGINE_LOCALIZATION = "references/localization.md"
ENGINE_RESEARCH = "references/research-and-sensitivity.md"
ENGINE_TEMPLATES = "references/platform-and-templates.md"
# What every channel adapter shares (asset rules, setup, browser fallback, approval, payload
# mapping, verification) lives once here instead of once per destination. An adapter overrides a
# section by repeating its heading.
ADAPTER_CONTRACT = "postriff-adapter-contract"
# When a turn would exceed its budget, these optional references are left out whole, in this
# order, until it fits. The omission is recorded on the binding (`omitted`) and in the run's usage,
# not raised as a run warning: nothing the draft depends on is lost, and a warning on every
# multi-channel turn would only teach people to ignore warnings. Leaving a whole file out keeps
# every recorded hash true to what the model actually received.
DROP_ORDER = (
    (ENGINE_SKILL, ENGINE_WORKFLOWS),
    (ENGINE_SKILL, ENGINE_TEMPLATES),
    (CORE_SKILL, DISCOVERY_REFERENCE),
    (CORE_SKILL, VISUAL_REFERENCE),
    (CORE_SKILL, "references/platform-playbooks.md"),
)
# Still over budget: rules the turn selected for a reason go next, each one a run warning, whole
# skills last. What never drops: the editorial core, the human-voice pass, the adapter contract
# and the channel adapters. Only when those alone exceed the budget is the text hard-cut, and
# that warning says a channel adapter may be incomplete.
FALLBACK_ORDER = (
    (CORE_SKILL, "references/editorial-workflow.md"),
    (ENGINE_SKILL, ENGINE_LOCALIZATION),
    (ENGINE_SKILL, ENGINE_RESEARCH),
    (RESEARCH_SKILL, "references/provenance-ledger.md"),
    (RESEARCH_SKILL, None),
    (ENGINE_SKILL, None),
)
RESEARCH_INTENTS = {"research"}
# Local names of content types whose preflight asks for evidence or citation. Catalog ids are namespaced
# (pack.creator:article_news_commentary, postriff:promote, workspace_x:...), so matching uses the part after ":".
CITED_CONTENT_TYPES = {"article_news_commentary", "deep_point_of_view", "product_feature_launch", "promote"}
DEFAULT_LANGUAGE = "English"
CHANNEL_SKILLS = {
    "LinkedIn": "postriff-channel-linkedin", "Instagram": "postriff-channel-instagram", "Threads": "postriff-channel-threads",
    "Facebook": "postriff-channel-facebook", "X": "postriff-channel-x", "TikTok": "postriff-channel-tiktok", "YouTube": "postriff-channel-youtube",
    "Xiaohongshu": "postriff-channel-xiaohongshu", "Bilibili": "postriff-channel-bilibili", "Zhihu": "postriff-channel-zhihu", "Weibo": "postriff-channel-weibo",
    "Douyin": "postriff-channel-douyin", "WeChat Channels": "postriff-channel-wechat-channels", "Pinterest": "postriff-channel-pinterest", "Reddit": "postriff-channel-reddit",
    "Bluesky": "postriff-channel-bluesky", "Telegram": "postriff-channel-telegram", "Mastodon": "postriff-channel-mastodon", "Snapchat": "postriff-channel-snapchat", "Discord": "postriff-channel-discord",
    # Adapters ship for these too. They are ahead of the drafting vocabulary in `intent.py`, so
    # that adding a platform there binds its adapter instead of silently writing without one.
    "Dcard": "postriff-channel-dcard", "Feishu / Lark": "postriff-channel-feishu-lark",
    "Google Business Profile": "postriff-channel-google-business-profile", "KakaoTalk Channel": "postriff-channel-kakaotalk-channel",
    "Kuaishou": "postriff-channel-kuaishou", "LINE Official Account": "postriff-channel-line-official-account",
    "Moj": "postriff-channel-moj", "Naver Blog": "postriff-channel-naver-blog", "note": "postriff-channel-note-jp",
    "Pixelfed": "postriff-channel-pixelfed", "ShareChat": "postriff-channel-sharechat",
    "Tencent QQ": "postriff-channel-tencent-qq", "WhatsApp Channels": "postriff-channel-whatsapp-channels",
}
# Budget per route. The paid cloud route keeps 60k characters (about 15k prompt tokens a draft);
# the routes a person's own subscription pays for get room for every file a turn selects.
MAX_TEXT_CHARS = 60_000
SUBSCRIPTION_TEXT_CHARS = 120_000
MAX_FILE_CHARS = 20_000
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_VERSION = re.compile(r"^\s*version:\s*([\w.+-]+)\s*$", re.M)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


def budget_for(cost_class):
    """Characters of skill text a route may carry: `subscription` routes (Claude Code, Codex on the
    person's own plan) get the larger budget; paid and fixture routes keep MAX_TEXT_CHARS."""
    return SUBSCRIPTION_TEXT_CHARS if cost_class == "subscription" else MAX_TEXT_CHARS


def cites_sources(intent, content_type):
    """A turn that researches, or whose content type requires citation, carries the claim rules."""
    local_name = content_type.rsplit(":", 1)[-1] if isinstance(content_type, str) else None
    return intent in RESEARCH_INTENTS or local_name in CITED_CONTENT_TYPES


def default_root():
    override = os.environ.get(SKILLS_DIR_ENV)
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    repo = Path(__file__).resolve().parents[2] / "skills"
    return repo if (repo / CORE_SKILL / "SKILL.md").is_file() else None


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


class SkillLibrary:
    """Reads skill packages from one root. Every file is hashed; nothing is executed."""

    def __init__(self, root=None):
        self.root = Path(root) if root else default_root()

    def available(self):
        return self.root is not None and (self.root / CORE_SKILL / "SKILL.md").is_file()

    def _read(self, skill_id, relative):
        base = (self.root / skill_id).resolve()
        path = (base / relative).resolve()
        if base not in path.parents or not path.is_file():
            return None
        raw = path.read_bytes()
        text = raw.decode("utf-8", "replace")
        return {"path": relative, "sha256": _sha256(raw), "chars": len(text), "text": text}

    def load(self, skill_id, references=()):
        """One skill: SKILL.md plus the named reference files. None when the package is absent."""
        if not self.available() or not _SAFE_ID.match(skill_id):
            return None
        main = self._read(skill_id, "SKILL.md")
        if main is None:
            return None
        match = _FRONTMATTER.match(main["text"])
        frontmatter = match.group(1) if match else ""
        version_match = _VERSION.search(frontmatter)
        body = main["text"][match.end():] if match else main["text"]
        files = [main]
        for relative in references:
            item = self._read(skill_id, relative)
            if item:
                files.append(item)
        return {
            "id": skill_id,
            "version": version_match.group(1) if version_match else "unversioned",
            "sha256": _sha256("".join(f["sha256"] for f in files).encode()),
            "files": [{"path": f["path"], "sha256": f["sha256"], "chars": f["chars"]} for f in files],
            "body": body.strip(),
            "references": [{"path": f["path"], "text": f["text"]} for f in files[1:]],
        }

    @staticmethod
    def _engine_references(destinations, format_id, intent, content_type):
        """The parts of the voice contract this turn actually uses."""
        references = []
        if format_id or content_type:
            references.append(ENGINE_WORKFLOWS)
        languages = {d.get("language") for d in destinations if d.get("language")}
        if len(languages) > 1 or (languages and languages != {DEFAULT_LANGUAGE}):
            references.append(ENGINE_LOCALIZATION)
        if cites_sources(intent, content_type):
            references.append(ENGINE_RESEARCH)
        if format_id in VISUAL_FORMATS:
            references.append(ENGINE_TEMPLATES)
        return tuple(references)

    def bind(self, destinations, format_id=None, intent=None, content_type=None, max_chars=None):
        """Skills for a turn: the voice contract, the editorial core with write-time discovery, a visual
        handoff for visual formats, the claim rules when the turn cites sources, and the adapter
        contract plus one adapter per destination platform. `max_chars` is the route's budget
        (see `budget_for`). Returns bindings (metadata only), composed text, warnings, the files
        left out to fit (`omitted`) and the budget applied."""
        budget = int(max_chars) if max_chars else MAX_TEXT_CHARS
        if not self.available():
            return {"bindings": [], "text": "", "warnings": ["No skill library is installed on this host, so the run received the editorial policy only."], "omitted": [], "budget": budget}
        wanted = [(ENGINE_SKILL, self._engine_references(destinations, format_id, intent, content_type)),
                  (CORE_SKILL, CORE_REFERENCES + ((VISUAL_REFERENCE,) if format_id in VISUAL_FORMATS else ()) + (DISCOVERY_REFERENCE,))]
        if cites_sources(intent, content_type):
            wanted.append((RESEARCH_SKILL, RESEARCH_REFERENCES))
        adapters, unmapped = [], []
        for destination in destinations:
            platform = destination.get("platform")
            skill_id = CHANNEL_SKILLS.get(platform)
            if skill_id is None:
                if platform and platform not in unmapped:
                    unmapped.append(platform)
            elif skill_id not in adapters:
                adapters.append(skill_id)
        # The shared contract rides with the adapters, once, and only when at least one is installed.
        if any((self.root / skill_id / "SKILL.md").is_file() for skill_id in adapters):
            wanted.append((ADAPTER_CONTRACT, ()))
        wanted.extend((skill_id, ()) for skill_id in adapters)
        warnings = [f"No channel adapter is mapped for {platform}; the run wrote for it without one." for platform in unmapped]
        selected = []  # [skill_id, [references], loaded]
        for skill_id, references in wanted:
            loaded = self.load(skill_id, references)
            if loaded is None:
                warnings.append(f"Skill {skill_id} is not installed on this host; the run wrote without it.")
                continue
            selected.append([skill_id, [r["path"] for r in loaded["references"]], loaded])

        def composed():
            return "\n\n".join(self._section(entry[2]) for entry in selected)

        omitted = []

        def drop(skill_id, reference):
            """Leave one reference (or, with None, the whole skill) out and record it. True when something was removed."""
            for entry in selected:
                if entry[0] != skill_id:
                    continue
                if reference is None:
                    selected.remove(entry)
                    omitted.append({"skill": skill_id, "path": "SKILL.md", "chars": len(self._section(entry[2]))})
                    return True
                if reference in entry[1]:
                    chars = next((r["chars"] for r in entry[2]["files"] if r["path"] == reference), 0)
                    entry[1].remove(reference)
                    entry[2] = self.load(skill_id, tuple(entry[1]))
                    omitted.append({"skill": skill_id, "path": reference, "chars": chars})
                    return True
            return False

        for skill_id, reference in DROP_ORDER:
            if len(composed()) <= budget:
                break
            drop(skill_id, reference)
        for skill_id, reference in FALLBACK_ORDER:
            if len(composed()) <= budget:
                break
            if drop(skill_id, reference):
                what = f"{skill_id}/{reference}" if reference else f"the whole {skill_id} skill"
                warnings.append(f"Left out {what}: the skills this turn selected exceed {budget} characters on this route. Review the draft against those rules.")

        bindings = []
        for _, _, loaded in selected:
            bindings.append({k: loaded[k] for k in ("id", "version", "sha256", "files")})
            if len(loaded["body"]) > MAX_FILE_CHARS:
                warnings.append(f"Skill {loaded['id']}: SKILL.md was cut at {MAX_FILE_CHARS} characters.")
            for reference in loaded["references"]:
                if len(reference["text"]) > MAX_FILE_CHARS:
                    warnings.append(f"Skill {loaded['id']}: {reference['path']} was cut at {MAX_FILE_CHARS} characters.")
        text = composed()
        if len(text) > budget:
            # The editorial core, voice pass, adapter contract and adapters alone exceed the budget:
            # the last resort, never reached by a normal turn. The cut lands on the last adapters.
            text = text[:budget]
            warnings.append(f"Skill text was cut at {budget} characters, so a channel adapter may be incomplete. Review the draft against the platform rules before scheduling.")
        return {"bindings": bindings, "text": text, "warnings": warnings, "omitted": omitted, "budget": budget}

    @staticmethod
    def _section(loaded):
        parts = [f"## Skill: {loaded['id']} (v{loaded['version']})", loaded["body"][:MAX_FILE_CHARS]]
        parts += [f"### {loaded['id']}/{r['path']}\n{r['text'][:MAX_FILE_CHARS]}" for r in loaded["references"]]
        return "\n\n".join(parts)


def summary(bindings):
    """Short, content-free labels for the activity strip: `content-craft`, `channel-linkedin`…"""
    return [b["id"].removeprefix("postriff-") for b in bindings]
