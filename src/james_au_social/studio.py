"""James Au Studio owner-local editorial data, never delivery execution.

This module owns only ``studio_*`` tables. It deliberately creates no publication
jobs, credentials, approvals or network clients. Schema 2 additionally retains
scoped editorial conversation/run records; store initialization never generates.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import warnings
import zipfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .channel_adapters import PROFILES
from .director import CHANNEL_IDS

VERSION = "0.6.0"
MAX_ASSET_BYTES = 15 * 1024 * 1024
MAX_BACKUP_BYTES = 256 * 1024 * 1024
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_BACKUP_MEMBERS = 1024
MAX_IMAGE_PIXELS = 24_000_000
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
ASSET_PATH_PATTERN = re.compile(r"^assets/[a-f0-9]{32}\.(?:png|jpg|webp)$")
DEFAULT_IDS = (
    "build-in-public-post", "calm-editorial-visual-family",
    "breaking-news-rapid-response", "article-to-xiaohongshu-note",
    "thesis-led-article", "article-to-instagram-carousel",
)
SCHEMA_V1 = (
    "CREATE TABLE IF NOT EXISTS studio_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_drafts (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_draft_versions (id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (id, revision))",
    "CREATE TABLE IF NOT EXISTS studio_templates (id TEXT NOT NULL, version INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (id, version))",
    "CREATE TABLE IF NOT EXISTS studio_assets (id TEXT PRIMARY KEY, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_activity (id TEXT PRIMARY KEY, data TEXT NOT NULL)",
)
AGENT_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS studio_agent_conversations (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_agent_conversation_versions (id TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (id, revision))",
    "CREATE TABLE IF NOT EXISTS studio_agent_runs (id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, input_json TEXT NOT NULL, apply_json TEXT, data TEXT NOT NULL)",
)
SCHEMA_V2 = SCHEMA_V1 + AGENT_SCHEMA
DELIVERY_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS studio_delivery_reviews (id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_delivery_receipts (id TEXT PRIMARY KEY, review_id TEXT NOT NULL UNIQUE, job_id TEXT NOT NULL UNIQUE, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_delivery_jobs (id TEXT PRIMARY KEY, review_id TEXT NOT NULL UNIQUE, receipt_id TEXT NOT NULL UNIQUE, data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_delivery_worker (id INTEGER PRIMARY KEY CHECK (id=1), data TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS studio_delivery_lease_owners (owner TEXT PRIMARY KEY, generation INTEGER NOT NULL UNIQUE, retired INTEGER NOT NULL CHECK (retired IN (0,1)))",
)
SCHEMA = SCHEMA_V2 + DELIVERY_SCHEMA
DRAFT_DEFAULTS = {
    "title": "", "category": "", "source": "", "angle": "", "channels": [],
    "copies": {}, "languages": {}, "formats": {}, "templateId": "",
    "templateVersion": 0, "visualRef": {"theme": "", "layouts": []},
    "plannedAt": "", "timezone": "", "assetIds": [],
}
SERVER_DRAFT_KEYS = {"id", "revision", "createdAt", "updatedAt", "archived", "status", "planningState"}
CHANNEL_NAMES = dict(zip(CHANNEL_IDS, (
    "YouTube", "Instagram", "Facebook", "LinkedIn", "X", "TikTok", "Threads",
    "Xiaohongshu · 小紅書", "Douyin · 抖音", "WeChat Channels · 視頻號", "Bilibili",
    "Reddit", "Pinterest", "Bluesky", "Telegram", "Google Business Profile",
    "Discord", "Feishu / Lark", "Weibo · 微博", "Zhihu · 知乎", "Tencent QQ",
    "Pixelfed", "Mastodon", "Snapchat", "WhatsApp Channels", "LINE Official Account",
    "note", "ShareChat", "Moj", "KakaoTalk Channel", "Naver Blog", "Kuaishou · 快手", "Dcard",
)))


class StudioError(ValueError):
    """Static, non-sensitive public error, safe for the localhost API."""

    def __init__(self, code, message=None, status=400):
        super().__init__(code)
        self.code = code
        self.message = message or code.replace("_", " ").capitalize() + "."
        self.status = status


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _text(value, field, limit=100000, required=False):
    if (not isinstance(value, str) or len(value) > limit or "\x00" in value
            or any(0xD800 <= ord(character) <= 0xDFFF for character in value)):
        raise StudioError("invalid_" + field, f"{field} must be text within its size limit.", 422)
    if required and not value.strip():
        raise StudioError("missing_" + field, f"{field} must not be empty.", 422)
    return value


def _integer(value, field):
    if type(value) is not int or value < 1 or value > 2**31 - 1:
        raise StudioError("invalid_" + field, f"{field} must be a positive integer.", 422)
    return value


def _timestamp(value, field):
    _text(value, field, 40, True)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise StudioError("invalid_" + field, status=422) from None
    if not value.endswith("Z") or parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise StudioError("invalid_" + field, "Stored timestamps must be UTC ISO timestamps.", 422)


def _known_schema(db, version):
    """Reject unknown SQL before migration can perform any application writes."""
    def normalized(sql):
        return " ".join(sql.lower().replace("if not exists ", "").split())
    schema = list(db.execute("SELECT type,name,sql FROM sqlite_master"))
    if version == 0:
        if schema:
            raise StudioError("database_version_unsupported")
        return
    if version not in (1, 2, 3):
        raise StudioError("database_version_unsupported")
    if any(kind not in ("table", "index") or kind == "index" and sql is not None for kind, _, sql in schema):
        raise StudioError("unsafe_database_schema")
    expected = {normalized(sql) for sql in {1: SCHEMA_V1, 2: SCHEMA_V2, 3: SCHEMA}[version]}
    if {normalized(sql) for kind, _, sql in schema if kind == "table"} != expected:
        raise StudioError("unsupported_database_schema", "Only the reviewed Phase A/B/C-local schemas support this migration.")
    if dict(db.execute("SELECT key,value FROM studio_meta")) != {"phase": {1: "A", 2: "B", 3: "C-local"}[version], "executionEnabled": "false"}:
        raise StudioError("database_execution_must_be_disabled")


def _no_symlinks(path):
    """Reject symlink components rather than accepting an escaped data root."""
    path = Path(os.path.abspath(path))
    # macOS itself aliases /var and /tmp into /private. Accept only those exact
    # system aliases, while rejecting application/user-controlled symlinks.
    for alias in ("/var", "/tmp"):
        if (str(path).startswith(alias + "/") and Path(alias).is_symlink()
                and str(Path(alias).resolve()) == "/private" + alias):
            path = Path("/private" + str(path))
    for component in (path, *path.parents):
        if component.is_symlink():
            raise StudioError("symlink_path", "Application paths must not use symbolic links.")
    return path


def _read_owned(path, limit):
    _no_symlinks(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise StudioError("invalid_local_file", "Local file type or size is not permitted.")
            result = stream.read(limit + 1)
            if len(result) > limit:
                raise StudioError("file_too_large", status=413)
            return result
    except FileNotFoundError:
        raise StudioError("local_file_missing", "A workspace file is missing; no external action was taken.", 404) from None


def _write_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _image_type(data):
    if not isinstance(data, bytes) or not data:
        raise StudioError("empty_image", "Choose a PNG, JPEG or WebP image.", 422)
    if len(data) > MAX_ASSET_BYTES:
        raise StudioError("image_too_large", "Images must be 15 MiB or smaller.", 413)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        expected, mime, ext = "PNG", "image/png", "png"
    elif data.startswith(b"\xff\xd8\xff"):
        expected, mime, ext = "JPEG", "image/jpeg", "jpg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        expected, mime, ext = "WEBP", "image/webp", "webp"
    else:
        raise StudioError("unsupported_image", "Only actual PNG, JPEG and WebP images are accepted.", 422)
    from PIL import Image, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != expected or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise StudioError("image_dimensions_limit", "Image dimensions exceed the 24 megapixel limit.", 422)
                if getattr(image, "n_frames", 1) != 1:
                    raise StudioError("animated_image_not_supported", "Use a still image in Phase A.", 422)
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        if isinstance(exc, StudioError):
            raise
        raise StudioError("invalid_image", "The image could not be safely decoded.", 422) from None
    return mime, ext


def channel_catalog():
    result = []
    for channel_id in CHANNEL_IDS:
        language, formats = PROFILES[channel_id]
        group = ("Mainland China" if channel_id in {
            "xiaohongshu", "douyin", "wechat-channels", "bilibili", "weibo", "zhihu", "tencent-qq", "kuaishou"
        } else "Regional" if channel_id in {
            "line-official-account", "note-jp", "sharechat", "moj", "kakaotalk-channel", "naver-blog", "dcard", "feishu-lark"
        } else "Global")
        result.append({"id": channel_id, "name": CHANNEL_NAMES[channel_id], "group": group,
                       "formats": [{"id": value, "label": value.split(".", 1)[-1].replace("_", " ").title()}
                                   for value in formats], "defaultLanguage": language,
                       "connection": "not_connected", "publishReady": False})
    return result


def visual_catalog(project_root):
    catalog = Path(project_root) / "skills/james-au-social-graphics/references/guizang-visual-catalog.md"
    content = catalog.read_text(encoding="utf-8")
    themes, layouts = [], []
    for line in content.splitlines():
        match = re.match(r"\| `(editorial\.[a-z-]+|swiss\.[a-z-]+)` \| ([^|]+) \| ([^|]+) \|", line)
        if match:
            themes.append({"id": match[1], "name": match[3].strip(), "system": match[2].strip()})
        match = re.match(r"\| `([MS]\d{2})` \| ([^|]+) \|", line)
        if match:
            layouts.append({"id": match[1], "name": match[2].strip(),
                            "system": "Editorial" if match[1].startswith("M") else "Swiss"})
    if len(themes) != 10 or len(layouts) != 28:
        raise StudioError("visual_catalog_invalid", "The reviewed visual reference catalog is incomplete.")
    return {"themes": themes, "layouts": layouts}


def _default_templates(project_root):
    kinds = {"thesis-led-article": "article", "calm-editorial-visual-family": "visual",
             "article-to-instagram-carousel": "visual"}
    for template_id in DEFAULT_IDS:
        body = (Path(project_root) / "templates/defaults" / (template_id + ".md")).read_text(encoding="utf-8")
        heading = re.search(r"^# (.+)$", body, re.MULTILINE)
        template = {"id": template_id, "version": 1, "name": heading[1] if heading else template_id,
                    "kind": kinds.get(template_id, "caption"), "body": body, "origin": "default"}
        template["hash"] = _hash(_json(template).encode())
        yield template


class StudioStore:
    def __init__(self, data_dir: Path, project_root: Path):
        self.data_dir = _no_symlinks(data_dir)
        self.project_root = Path(project_root)
        self.data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not self.data_dir.is_dir():
            raise StudioError("invalid_data_directory")
        self.data_dir.chmod(0o700)
        self.db_path = self.data_dir / "studio.sqlite3"
        self.assets_dir = self.data_dir / "assets"
        for path in (self.db_path, self.assets_dir, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            _no_symlinks(path)
        self.assets_dir.mkdir(mode=0o700, exist_ok=True)
        self.assets_dir.chmod(0o700)
        self.visuals = visual_catalog(project_root)
        with self.connection(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            _known_schema(db, version)
            for statement in SCHEMA:
                db.execute(statement)
            db.execute("PRAGMA user_version=3")
            db.execute("INSERT OR IGNORE INTO studio_meta VALUES ('phase', 'C-local')")
            db.execute("UPDATE studio_meta SET value='C-local' WHERE key='phase'")
            db.execute("INSERT OR IGNORE INTO studio_meta VALUES ('executionEnabled', 'false')")
            db.execute("INSERT OR IGNORE INTO studio_delivery_worker VALUES (1,?)", (_json({"paused": True, "heartbeatAt": None, "owner": None, "generation": 0, "leaseUntil": None}),))
            self._seed_templates(db)
        self.db_path.chmod(0o600)

    @contextmanager
    def connection(self, write=False):
        for path in (self.db_path, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            _no_symlinks(path)
        # Create the DB owner-only before sqlite can create it using a broad umask.
        if not self.db_path.exists():
            try:
                _write_new(self.db_path, b"")
            except FileExistsError:
                pass
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        for path in (self.db_path, Path(str(self.db_path) + "-wal"), Path(str(self.db_path) + "-shm")):
            if path.exists():
                path.chmod(0o600)
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _seed_templates(self, db):
        for template in _default_templates(self.project_root):
            template_id = template["id"]
            if db.execute("SELECT 1 FROM studio_templates WHERE id=?", (template_id,)).fetchone():
                continue
            db.execute("INSERT INTO studio_templates VALUES (?,?,?)", (template_id, 1, _json(template)))

    def _activity(self, db, action, subject_id, label):
        entry = {"id": uuid.uuid4().hex, "action": action, "subjectId": subject_id,
                 "label": label, "createdAt": _now(), "scope": "local"}
        db.execute("INSERT INTO studio_activity VALUES (?,?)", (entry["id"], _json(entry)))

    def activity(self):
        with self.connection() as db:
            items = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_activity")]
        return sorted(items, key=lambda row: (row["createdAt"], row["id"]), reverse=True)[:200]

    def bootstrap(self):
        return {"workspace": {"name": "James Au Studio", "phase": "D-connection", "storage": "local_sqlite", "version": VERSION},
                "channels": channel_catalog(), "templates": self.list_templates(), "visualCatalog": self.visuals,
                "drafts": self.list_drafts(), "assets": self.list_assets(), "activity": self.activity(),
                "capabilities": {"publishing": False, "scheduling": False, "agentBridge": False}}

    def _validate_draft(self, supplied, db, prior=None):
        if not isinstance(supplied, dict) or set(supplied) - set(DRAFT_DEFAULTS):
            raise StudioError("invalid_draft_fields", "Only editorial draft fields may be saved; execution state is server-controlled.", 422)
        draft = json.loads(_json(DRAFT_DEFAULTS))
        if prior:
            draft.update({key: prior[key] for key in DRAFT_DEFAULTS})
        draft.update(supplied)
        for key, limit in (("title", 500), ("category", 100), ("source", 200000), ("angle", 100000),
                           ("templateId", 100), ("plannedAt", 32), ("timezone", 100)):
            _text(draft[key], key, limit)
        for key, maximum in (("channels", 33), ("assetIds", 30)):
            value = draft[key]
            if not isinstance(value, list) or len(value) > maximum or any(not isinstance(item, str) for item in value) or len(set(value)) != len(value):
                raise StudioError("invalid_" + key, status=422)
        if any(item not in CHANNEL_IDS for item in draft["channels"]):
            raise StudioError("unknown_channel", status=422)
        for key in ("copies", "languages", "formats"):
            value = draft[key]
            if not isinstance(value, dict) or any(channel not in CHANNEL_IDS for channel in value):
                raise StudioError("invalid_" + key, status=422)
            for channel, text in value.items():
                _text(text, key, 100000 if key == "copies" else 100)
                if key == "formats" and text and text not in PROFILES[channel][1]:
                    raise StudioError("unsupported_native_format", "Select an explicit native format for this channel.", 422)
        if draft["templateId"]:
            _integer(draft["templateVersion"], "templateVersion")
            if not db.execute("SELECT 1 FROM studio_templates WHERE id=? AND version=?",
                              (draft["templateId"], draft["templateVersion"])).fetchone():
                raise StudioError("template_version_missing", "The selected immutable template version does not exist.", 422)
        else:
            if draft["templateVersion"] not in (None, "", 0):
                raise StudioError("template_id_required", status=422)
            draft["templateVersion"] = 0
        visual = draft["visualRef"]
        if not isinstance(visual, dict) or set(visual) != {"theme", "layouts"}:
            raise StudioError("invalid_visual_reference", status=422)
        themes = {row["id"]: row["system"] for row in self.visuals["themes"]}
        layouts = {row["id"]: row["system"] for row in self.visuals["layouts"]}
        if not isinstance(visual["theme"], str) or visual["theme"] and visual["theme"] not in themes:
            raise StudioError("unknown_visual_theme", status=422)
        if not isinstance(visual["layouts"], list) or len(visual["layouts"]) > 28 or any(not isinstance(item, str) or item not in layouts for item in visual["layouts"]):
            raise StudioError("unknown_visual_layout", status=422)
        if visual["theme"] and any(layouts[item] != themes[visual["theme"]] for item in visual["layouts"]):
            raise StudioError("visual_system_mismatch", "Keep Editorial and Swiss layout references in separate packages.", 422)
        for asset_id in draft["assetIds"]:
            if not ID_PATTERN.fullmatch(asset_id) or not db.execute("SELECT 1 FROM studio_assets WHERE id=?", (asset_id,)).fetchone():
                raise StudioError("asset_missing", "A selected local asset does not exist.", 422)
        if draft["timezone"]:
            try:
                zone = ZoneInfo(draft["timezone"])
            except (ZoneInfoNotFoundError, ValueError):
                raise StudioError("invalid_timezone", "Choose a valid IANA timezone.", 422) from None
        if draft["plannedAt"]:
            if not draft["timezone"]:
                raise StudioError("timezone_required", "A local calendar plan needs an IANA timezone.", 422)
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", draft["plannedAt"]):
                raise StudioError("invalid_local_time", status=422)
            try:
                local = datetime.fromisoformat(draft["plannedAt"])
            except ValueError:
                raise StudioError("invalid_local_time", status=422) from None
            possibilities = []
            for fold in (0, 1):
                candidate = local.replace(tzinfo=zone, fold=fold)
                if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == local:
                    possibilities.append(candidate.utcoffset())
            if not possibilities:
                raise StudioError("nonexistent_local_time", "That local time is skipped by daylight-saving time. Choose another time.", 422)
            if len(set(possibilities)) > 1:
                raise StudioError("ambiguous_local_time", "That local time occurs twice during daylight-saving time. Choose an unambiguous time.", 422)
        if len(_json(draft).encode("utf-8")) > 1024 * 1024:
            raise StudioError("draft_too_large", "A draft must fit within 1 MiB.", 413)
        return draft

    def _draft(self, db, draft_id):
        row = db.execute("SELECT data FROM studio_drafts WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise StudioError("draft_not_found", "This local draft was not found.", 404)
        return json.loads(row[0])

    def _save(self, db, draft):
        body = _json(draft)
        db.execute("INSERT INTO studio_draft_versions VALUES (?,?,?)", (draft["id"], draft["revision"], body))
        db.execute("INSERT INTO studio_drafts VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                   (draft["id"], draft["revision"], body))

    def create_draft(self, supplied):
        with self.connection(write=True) as db:
            draft = self._validate_draft(supplied, db)
            now = _now()
            draft.update(id=uuid.uuid4().hex, revision=1, createdAt=now, updatedAt=now, archived=False,
                         status="draft", planningState="planned" if draft["plannedAt"] else "unplanned")
            self._save(db, draft)
            self._activity(db, "draft_created", draft["id"], "Draft saved to the local database")
        return draft

    def update_draft(self, draft_id, supplied, expected_revision):
        _integer(expected_revision, "expectedRevision")
        with self.connection(write=True) as db:
            previous = self._draft(db, draft_id)
            if previous["revision"] != expected_revision:
                raise StudioError("revision_conflict", "This draft changed in another editor. Your unsaved changes have not been applied.", 409)
            draft = self._validate_draft(supplied, db, previous)
            draft.update({key: previous[key] for key in SERVER_DRAFT_KEYS})
            draft.update(revision=expected_revision + 1, updatedAt=_now(),
                         planningState="planned" if draft["plannedAt"] else "unplanned")
            self._save(db, draft)
            self._activity(db, "draft_updated", draft_id, "Draft revision saved locally")
        return draft

    def archive_draft(self, draft_id, expected_revision, archived):
        _integer(expected_revision, "expectedRevision")
        if type(archived) is not bool:
            raise StudioError("invalid_archived", status=422)
        with self.connection(write=True) as db:
            draft = self._draft(db, draft_id)
            if draft["revision"] != expected_revision:
                raise StudioError("revision_conflict", "Reload the current draft before changing its archive state.", 409)
            draft.update(archived=archived, revision=expected_revision + 1, updatedAt=_now())
            self._save(db, draft)
            self._activity(db, "draft_archived" if archived else "draft_restored", draft_id,
                           "Draft archived locally; recovery remains available" if archived else "Draft restored to the local workspace")
        return draft

    def get_draft(self, draft_id):
        with self.connection() as db:
            return self._draft(db, draft_id)

    def list_drafts(self, archived=False):
        with self.connection() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_drafts")]
        return sorted([row for row in values if row["archived"] == archived], key=lambda row: row["updatedAt"], reverse=True)

    def export_draft(self, draft_id):
        draft = self.get_draft(draft_id)
        lines = ["# " + (draft["title"] or "Untitled draft"), "", "Local draft only — not approved, scheduled or published.", "",
                 f"Revision: {draft['revision']}", f"Category: {draft['category']}",
                 f"Local calendar intention: {draft['plannedAt'] or 'Unplanned'} {draft['timezone']}",
                 f"Template: {draft['templateId'] or 'None'} {draft['templateVersion']}",
                 "", "## Source notes", "", draft["source"], "", "## Personal angle", "", draft["angle"]]
        for channel_id in draft["channels"]:
            lines.extend(["", "## " + CHANNEL_NAMES[channel_id], "",
                          f"Language: {draft['languages'].get(channel_id, '')}",
                          f"Format: {draft['formats'].get(channel_id, '')}", "", draft["copies"].get(channel_id, "")])
        lines.extend(["", "## Local assets", "", *draft["assetIds"], ""])
        return "\n".join(lines)

    def get_template(self, template_id, version=None):
        with self.connection() as db:
            if version is None:
                row = db.execute("SELECT data FROM studio_templates WHERE id=? ORDER BY version DESC LIMIT 1", (template_id,)).fetchone()
            else:
                row = db.execute("SELECT data FROM studio_templates WHERE id=? AND version=?", (template_id, version)).fetchone()
        if not row:
            raise StudioError("template_not_found", status=404)
        return json.loads(row[0])

    def list_templates(self):
        # Every immutable version remains selectable and inspectable after an edit.
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_templates ORDER BY id,version DESC")]

    def _template_input(self, supplied):
        if not isinstance(supplied, dict) or set(supplied) != {"name", "kind", "body"}:
            raise StudioError("invalid_template_fields", status=422)
        _text(supplied["name"], "name", 200, True)
        _text(supplied["body"], "body", 200000, True)
        if supplied["kind"] not in ("article", "caption", "visual", "motion"):
            raise StudioError("invalid_template_kind", status=422)
        return dict(supplied)

    def create_template(self, supplied):
        template = self._template_input(supplied)
        template.update(id=uuid.uuid4().hex, version=1, origin="personal")
        template["hash"] = _hash(_json(template).encode())
        with self.connection(write=True) as db:
            db.execute("INSERT INTO studio_templates VALUES (?,?,?)", (template["id"], 1, _json(template)))
            self._activity(db, "template_created", template["id"], "Personal Markdown template saved locally")
        return template

    def version_template(self, template_id, supplied, expected_version):
        _integer(expected_version, "expectedVersion")
        template = self._template_input(supplied)
        with self.connection(write=True) as db:
            row = db.execute("SELECT data FROM studio_templates WHERE id=? ORDER BY version DESC LIMIT 1", (template_id,)).fetchone()
            if not row:
                raise StudioError("template_not_found", status=404)
            previous = json.loads(row[0])
            if previous["origin"] != "personal":
                raise StudioError("default_template_read_only", "Save a personal copy to adapt a default template.", 403)
            if previous["version"] != expected_version:
                raise StudioError("template_version_conflict", "A newer template version exists. Earlier versions remain unchanged.", 409)
            template.update(id=template_id, version=expected_version + 1, origin="personal")
            template["hash"] = _hash(_json(template).encode())
            db.execute("INSERT INTO studio_templates VALUES (?,?,?)", (template_id, template["version"], _json(template)))
            self._activity(db, "template_version_created", template_id, "New immutable personal template version saved")
        return template

    def list_assets(self):
        with self.connection() as db:
            values = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_assets")]
        return sorted(values, key=lambda row: row["createdAt"], reverse=True)

    def add_asset(self, data, name, alt="", content_type=None):
        _text(name, "filename", 255, True)
        _text(alt, "alt", 2000)
        if name in (".", "..") or any(char in name for char in ("/", "\\")) or any(ord(char) < 32 for char in name):
            raise StudioError("unsafe_filename", "Choose a simple image filename without path components.", 422)
        mime, extension = _image_type(data)
        if content_type and content_type not in (mime, "application/octet-stream"):
            raise StudioError("image_mime_mismatch", "The declared image type does not match its contents.", 422)
        asset_id = uuid.uuid4().hex
        asset = {"id": asset_id, "name": name, "mime": mime, "size": len(data), "sha256": _hash(data),
                 "alt": alt, "createdAt": _now(), "url": f"/api/assets/{asset_id}/content"}
        path = self.assets_dir / (asset_id + "." + extension)
        _no_symlinks(self.assets_dir)
        _write_new(path, data)
        try:
            with self.connection(write=True) as db:
                db.execute("INSERT INTO studio_assets VALUES (?,?)", (asset_id, _json(asset)))
                self._activity(db, "asset_saved", asset_id, "Image stored locally; no remote upload")
        except BaseException:
            path.unlink(missing_ok=True)  # only this newly generated, unreferenced file
            raise
        return asset

    def _asset_path(self, asset):
        if not ID_PATTERN.fullmatch(asset["id"]):
            raise StudioError("invalid_asset_record")
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(asset["mime"])
        if not extension:
            raise StudioError("invalid_asset_record")
        return self.assets_dir / (asset["id"] + "." + extension)

    def asset_content(self, asset_id):
        with self.connection() as db:
            row = db.execute("SELECT data FROM studio_assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise StudioError("asset_not_found", status=404)
        asset = json.loads(row[0])
        data = _read_owned(self._asset_path(asset), MAX_ASSET_BYTES)
        if len(data) != asset["size"] or _hash(data) != asset["sha256"]:
            raise StudioError("asset_integrity_failed", "The local image changed on disk; it was not served.", 409)
        return data, asset["mime"]

    def backup(self):
        """Consistent SQLite snapshot plus exact immutable referenced image bytes."""
        with tempfile.TemporaryDirectory(prefix=".studio-backup-", dir=self.data_dir) as temporary:
            snapshot = Path(temporary) / "studio.sqlite3"
            _write_new(snapshot, b"")
            with self.connection() as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
            snapshot.chmod(0o600)
            files = {"studio.sqlite3": _read_owned(snapshot, MAX_DATABASE_BYTES)}
            with closing(sqlite3.connect(snapshot)) as db:
                assets = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_assets")]
            total_size = len(files["studio.sqlite3"])
            if len(assets) + 2 > MAX_BACKUP_MEMBERS:
                raise StudioError("backup_size_limit", status=413)
            for asset in assets:
                if total_size + asset["size"] > MAX_BACKUP_BYTES:
                    raise StudioError("backup_size_limit", "This Phase A backup exceeds the 256 MiB limit.", 413)
                path = self._asset_path(asset)
                data = _read_owned(path, MAX_ASSET_BYTES)
                if len(data) != asset["size"] or _hash(data) != asset["sha256"]:
                    raise StudioError("asset_integrity_failed", "Backup stopped because an image hash did not match.", 409)
                files["assets/" + path.name] = data
                total_size += len(data)
            if len(files) + 1 > MAX_BACKUP_MEMBERS or sum(map(len, files.values())) > MAX_BACKUP_BYTES:
                raise StudioError("backup_size_limit", "This Phase A backup exceeds the 256 MiB or 1024 member limit.", 413)
            manifest = {"app": "james-au-studio", "format": 1, "createdAt": _now(), "executionEnabled": False,
                        "files": [{"path": name, "size": len(data), "sha256": _hash(data)} for name, data in sorted(files.items())]}
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("manifest.json", _json(manifest))
                for name, data in sorted(files.items()):
                    archive.writestr(name, data)
            if output.tell() > MAX_BACKUP_BYTES:
                raise StudioError("backup_size_limit", status=413)
            return output.getvalue()


def _validated_archive(backup):
    if not isinstance(backup, bytes) or not backup or len(backup) > MAX_BACKUP_BYTES:
        raise StudioError("invalid_backup_size", status=413)
    try:
        with zipfile.ZipFile(io.BytesIO(backup)) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if not members or len(members) > MAX_BACKUP_MEMBERS or len(set(names)) != len(names):
                raise StudioError("invalid_backup_members")
            if sum(item.file_size for item in members) > MAX_BACKUP_BYTES:
                raise StudioError("backup_size_limit", status=413)
            for member in members:
                path = PurePosixPath(member.filename)
                if (str(path) != member.filename or path.is_absolute() or ".." in path.parts
                        or "\\" in member.filename or member.is_dir() or member.flag_bits & 1
                        or stat.S_ISLNK(member.external_attr >> 16)
                        or member.filename not in ("manifest.json", "studio.sqlite3")
                        and not ASSET_PATH_PATTERN.fullmatch(member.filename)):
                    raise StudioError("unsafe_backup_path")
                limit = (1024 * 1024 if member.filename == "manifest.json" else
                         MAX_DATABASE_BYTES if member.filename == "studio.sqlite3" else MAX_ASSET_BYTES)
                if member.file_size > limit:
                    raise StudioError("backup_member_size_limit", status=413)
            if "manifest.json" not in names or "studio.sqlite3" not in names:
                raise StudioError("backup_manifest_missing")
            manifest = json.loads(archive.read("manifest.json"))
            if (not isinstance(manifest, dict) or set(manifest) != {"app", "format", "createdAt", "executionEnabled", "files"}
                    or manifest["app"] != "james-au-studio" or type(manifest["format"]) is not int or manifest["format"] != 1
                    or manifest["executionEnabled"] is not False or not isinstance(manifest["files"], list)):
                raise StudioError("invalid_backup_manifest")
            _timestamp(manifest["createdAt"], "createdAt")
            expected = {}
            for entry in manifest["files"]:
                if (not isinstance(entry, dict) or set(entry) != {"path", "size", "sha256"}
                        or not isinstance(entry["path"], str) or entry["path"] in expected
                        or type(entry["size"]) is not int or entry["size"] < 0
                        or not isinstance(entry["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])):
                    raise StudioError("invalid_backup_manifest")
                expected[entry["path"]] = entry
            if set(expected) != set(names) - {"manifest.json"}:
                raise StudioError("backup_manifest_mismatch")
            files = {}
            for name, entry in expected.items():
                data = archive.read(name)
                if len(data) != entry["size"] or _hash(data) != entry["sha256"]:
                    raise StudioError("backup_hash_mismatch")
                files[name] = data
            if not files["studio.sqlite3"].startswith(b"SQLite format 3\x00"):
                raise StudioError("invalid_backup_database")
            return files
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, RuntimeError, RecursionError, NotImplementedError):
        raise StudioError("invalid_backup", "The file is not a valid bounded Studio backup.") from None


def _validate_restored_database(path):
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA query_only=ON")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (1, 2, 3):
                raise StudioError("unsupported_backup_schema")
            _known_schema(db, version)
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise StudioError("invalid_backup_database")
            templates = [json.loads(row[0]) for row in db.execute("SELECT data FROM studio_templates")]
            defaults = [row for row in templates if isinstance(row, dict) and row.get("origin") == "default"]
            if len(defaults) != 6 or {row.get("id") for row in defaults} != set(DEFAULT_IDS):
                raise StudioError("backup_default_templates_missing")
    except sqlite3.DatabaseError:
        raise StudioError("invalid_backup_database") from None


def restore_new(backup: bytes, target: Path, project_root: Path):
    """Restore verified data to a new destination; never overwrite a workspace.

    A backup is data, not trusted code: no triggers/views/virtual tables, unknown
    schemas, ZIP links, extra members or executable assets are permitted.
    """
    target = _no_symlinks(target)
    if target.exists():
        raise StudioError("restore_target_exists", "Choose a new directory; existing workspaces are never overwritten.", 409)
    if not target.parent.is_dir():
        raise StudioError("restore_parent_missing", "Create the parent directory before restoring.")
    files = _validated_archive(backup)
    staging = Path(tempfile.mkdtemp(prefix=".studio-restore-", dir=target.parent))
    try:
        (staging / "assets").mkdir(mode=0o700)
        for name, data in files.items():
            _write_new(staging / name, data)
        _validate_restored_database(staging / "studio.sqlite3")
        restored = StudioStore(staging, project_root)
        expected_defaults = {row["id"]: row for row in _default_templates(project_root)}
        with restored.connection(write=True) as db:
            assets = restored.list_assets()
            expected_paths = {"studio.sqlite3"}
            for asset in assets:
                if (set(asset) != {"id", "name", "mime", "size", "sha256", "alt", "createdAt", "url"}
                        or asset["url"] != f"/api/assets/{asset['id']}/content"):
                    raise StudioError("invalid_backup_asset")
                _text(asset["name"], "filename", 255, True)
                _text(asset["alt"], "alt", 2000)
                _timestamp(asset["createdAt"], "createdAt")
                if any(character in asset["name"] for character in ("/", "\\")):
                    raise StudioError("invalid_backup_asset")
                data, mime = restored.asset_content(asset["id"])
                if _image_type(data)[0] != mime:
                    raise StudioError("invalid_backup_asset")
                expected_paths.add("assets/" + restored._asset_path(asset).name)
            if expected_paths != set(files):
                raise StudioError("backup_asset_manifest_mismatch")
            for row in db.execute("SELECT id,version,data FROM studio_templates"):
                template = json.loads(row[2])
                if (set(template) != {"id", "version", "name", "kind", "body", "origin", "hash"}
                        or template["id"] != row[0] or template["version"] != row[1]
                        or template["origin"] not in ("default", "personal")):
                    raise StudioError("invalid_backup_template")
                if (template["origin"] == "default" and (template["id"] not in DEFAULT_IDS or template["version"] != 1)
                        or template["origin"] == "personal" and not ID_PATTERN.fullmatch(template["id"])):
                    raise StudioError("invalid_backup_template")
                if template["origin"] == "default" and template != expected_defaults.get(template["id"]):
                    raise StudioError("backup_default_template_mismatch", "This backup's default templates differ from the reviewed package; migration review is required.")
                restored._template_input({key: template[key] for key in ("name", "kind", "body")})
                _integer(template["version"], "version")
                if _hash(_json({key: value for key, value in template.items() if key != "hash"}).encode()) != template["hash"]:
                    raise StudioError("backup_template_hash_mismatch")
            for table in ("studio_drafts", "studio_draft_versions"):
                for row in db.execute(f"SELECT id,revision,data FROM {table}"):
                    draft = json.loads(row[2])
                    if (set(draft) != set(DRAFT_DEFAULTS) | SERVER_DRAFT_KEYS or draft["id"] != row[0]
                            or not ID_PATTERN.fullmatch(draft["id"]) or draft["revision"] != row[1]
                            or type(draft["archived"]) is not bool or draft["status"] != "draft"
                            or draft["planningState"] != ("planned" if draft["plannedAt"] else "unplanned")):
                        raise StudioError("invalid_backup_draft")
                    _integer(draft["revision"], "revision")
                    _timestamp(draft["createdAt"], "createdAt")
                    _timestamp(draft["updatedAt"], "updatedAt")
                    if draft["createdAt"] > draft["updatedAt"]:
                        raise StudioError("invalid_backup_timestamp_order")
                    restored._validate_draft({key: draft[key] for key in DRAFT_DEFAULTS}, db)
            for row in db.execute("SELECT id,revision,data FROM studio_drafts"):
                history = list(db.execute("SELECT revision,data FROM studio_draft_versions WHERE id=? ORDER BY revision", (row[0],)))
                if (not history or len(history) != row[1] or any(entry[0] != index for index, entry in enumerate(history, 1))
                        or history[-1][1] != row[2]):
                    raise StudioError("backup_revision_history_mismatch")
            if db.execute("SELECT 1 FROM studio_draft_versions WHERE id NOT IN (SELECT id FROM studio_drafts) LIMIT 1").fetchone():
                raise StudioError("backup_revision_history_mismatch")
            for row in db.execute("SELECT id,data FROM studio_activity"):
                entry = json.loads(row[1])
                if (not isinstance(entry, dict) or set(entry) != {"id", "action", "subjectId", "label", "createdAt", "scope"}
                        or entry["id"] != row[0] or not ID_PATTERN.fullmatch(entry["id"]) or entry["scope"] != "local"):
                    raise StudioError("invalid_backup_activity")
                for key, limit in (("action", 100), ("subjectId", 100), ("label", 1000), ("createdAt", 50)):
                    _text(entry[key], key, limit, True)
                _timestamp(entry["createdAt"], "createdAt")
            from .studio_agent import recover_agent_records, validate_agent_records
            validate_agent_records(restored, db)
            recover_agent_records(db)
            from .studio_delivery import restore_delivery_records, validate_delivery_records
            validate_delivery_records(restored, db)
            restore_delivery_records(db)
            restored._activity(db, "workspace_restored", "workspace", "Verified local backup restored; execution remains disabled")
            db.execute("UPDATE studio_meta SET value='false' WHERE key='executionEnabled'")
            draft_count = db.execute("SELECT count(*) FROM studio_drafts").fetchone()[0]
        if target.exists():
            raise StudioError("restore_target_exists", status=409)
        staging.rename(target)
        return {"status": "restored", "phase": "C-local", "executionEnabled": False,
                "drafts": draft_count, "assets": len(assets)}
    except (KeyError, TypeError, json.JSONDecodeError, sqlite3.DatabaseError, RecursionError, OverflowError):
        raise StudioError("invalid_backup_data", "The backup's data failed structural validation.") from None
    finally:
        if staging.exists():
            shutil.rmtree(staging)  # only the newly created private restore staging tree
