"""Rafii's style on the person's profile (migration 030) on disposable PostgreSQL: the default, a change saved and
read back on /api/me, refused values, another person's row untouched, what the browser role may do with the column,
the column's own checks, and this code running before 030 is applied (reading falls back to the default, saving
waits, and nothing else breaks).

Run through scripts/postriff_pg_suite.py (rls.sql loads migrations up to 030).
"""
from local_pg_target import selected_target
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from psycopg import errors
from postriff_alpha.domain import AlphaError
from postriff_phase2.agent_runtime_v2 import style
from postriff_phase2.hosted import AGENT_STYLE_NOT_READY, HostedWorkspaceService

DSN = selected_target().dsn()
ONE = "00000000-0000-0000-0000-000000000001"
SEVEN = "00000000-0000-0000-0000-000000000007"
DEFAULT = style.normalize({})
MIGRATION = ROOT / "migrations/postriff/030_agent_style.sql"
checks = []


def connection():
    return psycopg.connect(DSN, client_encoding="utf8")


def verify(token):
    who = token.split("-")[0]
    if who not in ("one", "seven"):
        raise AlphaError("Verified session required.", 401)
    return ONE if who == "one" else SEVEN


verify.session_id = lambda token, principal: f"session-{token}-0123456789abcdef"


def denied(call, status):
    try:
        call()
    except AlphaError as error:
        assert error.status == status, (error.status, str(error))
        return str(error)
    raise AssertionError("accepted")


def stored(user):
    with connection() as db:
        return db.execute("SELECT agent_style FROM public.pr_profiles WHERE user_id=%s", (user,)).fetchone()[0]


def refused(sql, params, error):
    with psycopg.connect(DSN, autocommit=True) as db:
        try:
            db.execute(sql, params)
        except error:
            return
    raise AssertionError(f"accepted: {sql}")


with connection() as db:
    db.execute("INSERT INTO auth.users VALUES(%s) ON CONFLICT DO NOTHING", (SEVEN,))
service = HostedWorkspaceService(connection, verify, clock=lambda: 1_800_000_000.0)
service.bootstrap("seven", "assist")

# 1. Nobody has chosen yet: the stored value is '{}' and /api/me reads the full default style.
assert stored(ONE) == {} and stored(SEVEN) == {}
assert service.me("one")["preferences"]["agentStyle"] == DEFAULT and DEFAULT["chosen"] is False
checks.append("the default: an empty object on the profile, read on /api/me as the complete default style")

# 2. A preset, then one field: each change merges into what is saved and reads back the same way.
first = service.update_profile("one", {"agentStyle": {"preset": "explainer", "chosen": True}})
explainer = {"tone": "friendly", "detail": "detailed", "pace": "slower", "voice": "marin", "language": "auto", "initiative": "suggest", "chosen": True}
assert first["preferences"]["agentStyle"] == explainer, first
assert service.me("one")["preferences"]["agentStyle"] == explainer and stored(ONE) == explainer
second = service.update_profile("one", {"agentStyle": {"voice": "cedar", "language": "yue"}})
assert second["preferences"]["agentStyle"] == {**explainer, "voice": "cedar", "language": "yue"}
assert stored(ONE) == {**explainer, "voice": "cedar", "language": "yue"}
# Other preferences keep it, and it keeps them.
zoned = service.update_profile("one", {"timeZone": "Asia/Hong_Kong"})
assert zoned["preferences"]["agentStyle"] == stored(ONE) and zoned["preferences"]["timeZone"] == "Asia/Hong_Kong"
both = service.update_profile("one", {"locale": "zh-Hant", "agentStyle": {"initiative": "ask"}})
assert (both["preferences"]["locale"], both["preferences"]["timeZone"], both["preferences"]["agentStyle"]["initiative"]) == ("zh-Hant", "Asia/Hong_Kong", "ask")
assert both["preferences"]["agentStyle"]["voice"] == "cedar"
checks.append("a preset and single fields merge into the saved style, read back on /api/me, beside the other preferences")

# 3. Values outside the lists are refused and change nothing.
before = stored(ONE)
for bad in ({"tone": "rude"}, {"voice": "Marin"}, {"language": "fr"}, {"preset": "chatty"}, {"volume": 11}, {"chosen": "yes"}, {}, "friendly"):
    denied(lambda bad=bad: service.update_profile("one", {"agentStyle": bad}), 400)
denied(lambda: service.update_profile("one", {"displayName": "Someone else", "agentStyle": {"pace": "fastest"}}), 400)
assert stored(ONE) == before
with connection() as db:
    assert db.execute("SELECT display_name FROM public.pr_profiles WHERE user_id=%s", (ONE,)).fetchone()[0] != "Someone else"
checks.append("unknown fields, values and presets are refused with 400 and nothing is written")

# 4. The other person's row is untouched and reads the default.
assert stored(SEVEN) == {} and service.me("seven")["preferences"]["agentStyle"] == DEFAULT
service.update_profile("seven", {"agentStyle": {"preset": "concise", "chosen": True}})
assert stored(ONE) == before and stored(SEVEN)["detail"] == "concise"
checks.append("each person's style is their own: saving one never touches another profile")

# 5. The browser role reads its own row only and cannot write the column (no grant beyond migration 001's select).
with psycopg.connect(DSN, autocommit=True) as db:
    privileges = db.execute("SELECT has_column_privilege('authenticated','public.pr_profiles','agent_style','UPDATE'), has_column_privilege('authenticated','public.pr_profiles','agent_style','INSERT'), has_table_privilege('authenticated','public.pr_profiles','UPDATE'), has_table_privilege('anon','public.pr_profiles','SELECT')").fetchone()
    assert privileges == (False, False, False, False), privileges
    db.execute("SET ROLE authenticated")
    db.execute("SELECT set_config('request.jwt.claim.sub',%s,false)", (ONE,))
    assert db.execute("SELECT user_id::text, agent_style FROM public.pr_profiles").fetchall() == [(ONE, before)]
    try:
        db.execute("UPDATE public.pr_profiles SET agent_style='{}'::jsonb WHERE user_id=%s", (ONE,))
        raise AssertionError("browser update accepted")
    except errors.InsufficientPrivilege:
        pass
    db.execute("RESET ROLE")
assert stored(ONE) == before
checks.append("the browser role sees only its own style and cannot write it; anon cannot read it")

# 6. The column's own checks: an object, at most 512 bytes.
refused("UPDATE public.pr_profiles SET agent_style='[]'::jsonb WHERE user_id=%s", (ONE,), errors.CheckViolation)
refused("UPDATE public.pr_profiles SET agent_style=jsonb_build_object('tone',(SELECT string_agg(md5(i::text),'') FROM generate_series(1,20) i)) WHERE user_id=%s", (ONE,), errors.CheckViolation)
refused("UPDATE public.pr_profiles SET agent_style=NULL WHERE user_id=%s", (ONE,), errors.NotNullViolation)
assert stored(ONE) == before
checks.append("the database refuses a non-object, an oversized value and NULL")

# 7. Before migration 030: /api/me answers with the default, other preferences save, a style change waits (503).
with connection() as db:
    db.execute("ALTER TABLE public.pr_profiles DROP COLUMN agent_style")
early = service.me("one-early")
assert early["preferences"]["agentStyle"] == DEFAULT and early["preferences"]["timeZone"] == "Asia/Hong_Kong"
with connection() as db:  # the session recorded in the same transaction still committed
    assert db.execute("SELECT count(*) FROM public.pr_sessions WHERE user_id=%s AND session_id=%s", (ONE, "session-one-early-0123456789abcdef")).fetchone()[0] == 1
assert denied(lambda: service.update_profile("one", {"agentStyle": {"preset": "concise", "chosen": True}}), 503) == AGENT_STYLE_NOT_READY
denied(lambda: service.update_profile("one", {"displayName": "Not yet", "agentStyle": {"tone": "direct"}}), 503)
waiting = service.update_profile("one", {"timeZone": "Europe/London"})
assert waiting["preferences"]["timeZone"] == "Europe/London" and waiting["preferences"]["agentStyle"] == DEFAULT
with connection() as db:
    assert db.execute("SELECT display_name FROM public.pr_profiles WHERE user_id=%s", (ONE,)).fetchone()[0] != "Not yet"
    db.execute(MIGRATION.read_text())
    db.execute(MIGRATION.read_text())  # applying it twice is harmless
assert stored(ONE) == {} and service.me("one")["preferences"]["agentStyle"] == DEFAULT
applied = service.update_profile("one", {"agentStyle": {"preset": "concise", "chosen": True}})
assert applied["preferences"]["agentStyle"] == {**DEFAULT, **style.PRESETS["concise"], "chosen": True}
with connection() as db:
    assert db.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='public.pr_profiles'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%agent_style%'").fetchone()[0] == 1
checks.append("before 030 /api/me reads the default and keeps its session, other preferences save, style changes return 503 and write nothing; applying 030 (twice) restores saving")

print(json.dumps({"status": "pass", "execution": "disposable-local-postgres", "checks": checks}, indent=2))
