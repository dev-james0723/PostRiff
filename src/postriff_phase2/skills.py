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
VISUAL_FORMATS = {"carousel", "image_caption", "quote_card", "story", "short_video", "long_video"}
CHANNEL_SKILLS = {
    "LinkedIn": "postriff-channel-linkedin", "Instagram": "postriff-channel-instagram", "Threads": "postriff-channel-threads",
    "Facebook": "postriff-channel-facebook", "X": "postriff-channel-x", "TikTok": "postriff-channel-tiktok", "YouTube": "postriff-channel-youtube",
    "Xiaohongshu": "postriff-channel-xiaohongshu", "Bilibili": "postriff-channel-bilibili", "Zhihu": "postriff-channel-zhihu", "Weibo": "postriff-channel-weibo",
    "Douyin": "postriff-channel-douyin", "WeChat Channels": "postriff-channel-wechat-channels", "Pinterest": "postriff-channel-pinterest", "Reddit": "postriff-channel-reddit",
    "Bluesky": "postriff-channel-bluesky", "Telegram": "postriff-channel-telegram", "Mastodon": "postriff-channel-mastodon", "Snapchat": "postriff-channel-snapchat", "Discord": "postriff-channel-discord",
}
MAX_TEXT_CHARS = 60_000
MAX_FILE_CHARS = 20_000
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_VERSION = re.compile(r"^\s*version:\s*([\w.+-]+)\s*$", re.M)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,80}$")


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

    def bind(self, destinations, format_id=None):
        """Skills for a turn: the editorial core, a visual handoff for visual formats, one adapter per
        destination platform. Returns bindings (metadata only), composed text, and warnings."""
        if not self.available():
            return {"bindings": [], "text": "", "warnings": ["No skill library is installed on this host, so the run received the editorial policy only."]}
        wanted = [(CORE_SKILL, CORE_REFERENCES + ((VISUAL_REFERENCE,) if format_id in VISUAL_FORMATS else ()))]
        seen = set()
        for destination in destinations:
            skill_id = CHANNEL_SKILLS.get(destination.get("platform"))
            if skill_id and skill_id not in seen:
                seen.add(skill_id)
                wanted.append((skill_id, ()))
        bindings, sections, warnings = [], [], []
        for skill_id, references in wanted:
            loaded = self.load(skill_id, references)
            if loaded is None:
                warnings.append(f"Skill {skill_id} is not installed on this host; the run wrote without it.")
                continue
            bindings.append({k: loaded[k] for k in ("id", "version", "sha256", "files")})
            parts = [f"## Skill: {loaded['id']} (v{loaded['version']})", loaded["body"][:MAX_FILE_CHARS]]
            if len(loaded["body"]) > MAX_FILE_CHARS:
                warnings.append(f"Skill {loaded['id']}: SKILL.md was cut at {MAX_FILE_CHARS} characters.")
            for reference in loaded["references"]:
                parts.append(f"### {loaded['id']}/{reference['path']}\n{reference['text'][:MAX_FILE_CHARS]}")
                if len(reference["text"]) > MAX_FILE_CHARS:
                    warnings.append(f"Skill {loaded['id']}: {reference['path']} was cut at {MAX_FILE_CHARS} characters.")
            sections.append("\n\n".join(parts))
        text = "\n\n".join(sections)
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
            warnings.append(f"Skill text was cut at {MAX_TEXT_CHARS} characters; later sections were left out.")
        return {"bindings": bindings, "text": text, "warnings": warnings}


def summary(bindings):
    """Short, content-free labels for the activity strip: `content-craft`, `channel-linkedin`…"""
    return [b["id"].removeprefix("postriff-") for b in bindings]
