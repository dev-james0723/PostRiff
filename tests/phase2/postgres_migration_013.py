"""Migration 013 on a disposable PostgreSQL of its own: learned-preference scope keys and bodies move from
English / 繁體中文 to en / zh-Hant, other scopes stay as they are, a legacy current version that would
collide with a current version under the new key is retired instead, and a second run changes nothing.

    LC_ALL=C .venv/bin/python tests/phase2/postgres_migration_013.py
"""
import json
import subprocess
import tempfile
from pathlib import Path

import psycopg

PG = Path("/opt/homebrew/opt/postgresql@17/bin")
PORT = 55463
ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (ROOT / "migrations/postriff/013_locale_tags.sql").read_text(encoding="utf-8")
WORKSPACE = "00000000-0000-0000-0000-0000000000aa"
SCHEMA = """
create table public.pr_memory_proposals (id uuid primary key default gen_random_uuid(), workspace_id uuid not null, scope_key text not null, body jsonb not null, status text not null);
create table public.pr_memory_versions (id uuid primary key default gen_random_uuid(), workspace_id uuid not null, scope_key text not null, body jsonb not null, status text not null, valid_from timestamptz not null default now(), valid_to timestamptz);
create unique index pr_memory_versions_one_current on public.pr_memory_versions (workspace_id, scope_key) where valid_to is null;
"""


def body(language, key):
    return json.dumps({"scope": {"platform": "Instagram", "language": language, "contentTypeId": None}, "scopeKey": key, "statement": "No hashtags."}, ensure_ascii=False)


checks = []
with tempfile.TemporaryDirectory() as tmp:
    data = Path(tmp) / "data"
    subprocess.run([str(PG / "initdb"), "-D", str(data), "-A", "trust", "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-l", str(Path(tmp) / "log"), "-o", f"-h 127.0.0.1 -p {PORT}", "-w", "start"], check=True, stdout=subprocess.DEVNULL)
    try:
        with psycopg.connect(f"host=127.0.0.1 port={PORT} dbname=postgres", autocommit=True, client_encoding="utf8") as db:
            db.execute(SCHEMA)
            zh, en, ja = ("writing_preference|hashtags.use|avoid|Instagram|繁體中文|*", "writing_preference|closing.cta|do|*|English|*", "writing_preference|emoji.use|avoid|Threads|ja-JP|*")
            for key, language in ((zh, "繁體中文"), (en, "English"), (ja, "ja-JP")):
                db.execute("INSERT INTO public.pr_memory_proposals(workspace_id,scope_key,body,status) VALUES(%s,%s,%s::jsonb,'dismissed')", (WORKSPACE, key, body(language, key)))
            db.execute("INSERT INTO public.pr_memory_versions(workspace_id,scope_key,body,status) VALUES(%s,%s,%s::jsonb,'active')", (WORKSPACE, zh, body("繁體中文", zh)))
            # A current English version and, already, a current `en` version for the same rule: the legacy one must retire.
            db.execute("INSERT INTO public.pr_memory_versions(workspace_id,scope_key,body,status) VALUES(%s,%s,%s::jsonb,'active')", (WORKSPACE, en, body("English", en)))
            db.execute("INSERT INTO public.pr_memory_versions(workspace_id,scope_key,body,status) VALUES(%s,%s,%s::jsonb,'active')", (WORKSPACE, en.replace("English", "en"), body("en", en.replace("English", "en"))))

            db.execute(MIGRATION)
            proposals = dict(db.execute("SELECT scope_key, body FROM public.pr_memory_proposals").fetchall())
            assert set(proposals) == {"writing_preference|hashtags.use|avoid|Instagram|zh-Hant|*", "writing_preference|closing.cta|do|*|en|*", ja}, proposals
            zh_body = proposals["writing_preference|hashtags.use|avoid|Instagram|zh-Hant|*"]
            assert zh_body["scope"]["language"] == "zh-Hant" and zh_body["scopeKey"].endswith("|zh-Hant|*"), zh_body
            assert proposals[ja]["scope"]["language"] == "ja-JP", proposals[ja]
            checks.append("proposal keys and bodies read en / zh-Hant; tags already in use are untouched")

            current = dict(db.execute("SELECT scope_key, body FROM public.pr_memory_versions WHERE valid_to IS NULL").fetchall())
            assert set(current) == {"writing_preference|hashtags.use|avoid|Instagram|zh-Hant|*", "writing_preference|closing.cta|do|*|en|*"}, current
            retired = db.execute("SELECT scope_key, status FROM public.pr_memory_versions WHERE valid_to IS NOT NULL").fetchall()
            assert retired == [("writing_preference|closing.cta|do|*|en|*", "retired")], retired  # history keeps the new key too
            checks.append("a legacy current version that would collide is retired; the others move to the new key")

            db.execute(MIGRATION)
            assert dict(db.execute("SELECT scope_key, body FROM public.pr_memory_proposals").fetchall()) == proposals
            checks.append("running it again changes nothing")
    finally:
        subprocess.run([str(PG / "pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL)

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2, ensure_ascii=False))
