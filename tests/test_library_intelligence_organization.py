"""T06 — Smart Collections, version comparison and lineage (acceptance A037–A043).

Unit tests of the Python logic. `OrgDB` emulates each tagged statement (`/*lio:...*/`) of collections, relations and
comparison plus the coordinator statements they rely on (versions, policy revisions/grants, audit, receipts). It proves
logic only; real SQL (constraints, SKIP LOCKED, jsonb, the unique relation index) is covered by
tests/phase2/postgres_library_intelligence_organization.py in cloud CI. Rule evaluation and explanations are pure
functions exercised directly.
"""
import copy
import hashlib
import json
import re
import unittest
import uuid
from types import SimpleNamespace

from library_intelligence_fakes import ACTOR, WS
from postriff_alpha.domain import AlphaError
from postriff_phase2 import source_policy
from postriff_phase2.permissions import Membership
from postriff_phase2.library_intelligence import actions, collections, comparison, contracts as c, policy, relations, versions

OTHER_ACTOR = "00000000-0000-0000-0000-0000000000a2"


def k(n: int) -> str:
    return f"{n:032x}"


A, B, C, D, E, F, G, X = (k(n) for n in (0xA1, 0xB1, 0xC1, 0xD1, 0xE1, 0xF1, 0x61, 0x91))
O, N, P = k(0x701), k(0x702), k(0x703)
PACK = k(0x9A1)


def sha(key):
    return hashlib.sha256(key.encode()).hexdigest()


RULE = {"all": [{"field": "kind", "op": "in", "value": ["audio"]}, {"field": "tag", "op": "has", "value": "rehearsal"}]}
AUDIO = {"all": [{"field": "kind", "op": "in", "value": ["audio"]}]}


class Spy:
    """Private storage double: Smart Collections must never call it."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"storage.{name} must not be called by organization code")
        return record


class OrgDB:
    """In-memory tables for the statements organization code issues. Single-threaded; no rollback emulation."""
    TAG = re.compile(r"/\*(li[oj]):([a-z_.]+)\*/")

    def __init__(self):
        self.now = 1_790_000_000.0
        self.assets, self.collections, self.items, self.overrides, self.revisions = {}, {}, {}, {}, {}
        self.relations, self.annotations, self.usage, self.suggestions, self.audits = [], [], [], [], []
        self.languages, self.caps, self.text, self.chunks, self.segments, self.packs = {}, {}, {}, {}, {}, {}
        self.neighbors, self.receipts, self.grants = {}, {}, []
        self.workspace_members, self.prefs = [ACTOR, OTHER_ACTOR], {}
        self.vector = False
        self.policy = {"grant": 0, "index": 1, "org": 0}
        self.state = {"sources": [], "variants": [], "phase2": {"assets": [], "jobs": [], "reviews": []}}
        self.executed, self._rows, self.rowcount = [], [], 0
        self.fail_on = None

    # --- connection protocol (reconcile_due) ---------------------------------------------------------------------------
    def connect(self):
        db = self

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return db
        return Conn()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    # --- fixtures -------------------------------------------------------------------------------------------------------
    def add(self, key, *, kind="audio", tags=(), title=None, filename=None, status="ready", lineage=None, version_no=1, created=None,
            mime=None, media=None, source_id=None, source_kind="upload", duplicate_of=None):
        ext = {"audio": "m4a", "document": "md", "image": "jpg", "video": "mp4", "file": "bin"}[kind]
        self.assets[key] = {"kind": kind, "tags": list(tags), "title": title, "filename": filename or f"{key[-4:]}.{ext}", "status": status,
                            "lineage": lineage, "version_no": version_no, "created": created if created is not None else self.now - 1000 + len(self.assets),
                            "mime": mime or {"audio": "audio/mp4", "document": "text/markdown", "image": "image/jpeg", "video": "video/mp4", "file": "application/octet-stream"}[kind],
                            "media": dict(media or {}), "sha": sha(key), "source_id": source_id, "source_kind": source_kind, "duplicate_of": duplicate_of}
        return key

    def members(self, cid):
        return {key: row for (coll, key), row in self.items.items() if coll == cid}

    # --- cursor ---------------------------------------------------------------------------------------------------------
    def execute(self, sql, args=()):
        self.executed.append((sql, args))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("simulated database failure")
        match = self.TAG.search(sql)
        if match:
            rows = getattr(self, "_" + match.group(2).replace(".", "_"))(args)
        else:
            rows = self._coordinator(sql, args)
        self._rows = list(rows or [])
        self.rowcount = len(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def sql(self, pattern):
        return [s for s, _ in self.executed if re.search(pattern, s, re.S)]

    # --- coordinator statements (versions, policy, audit, receipts) ------------------------------------------------------
    def _vrow(self, key):
        a = self.assets[key]
        return (uuid.UUID(hex=key), uuid.UUID(hex=a["lineage"]) if a["lineage"] else None, a["version_no"], WS, a["filename"], a["title"],
                "user" if a["title"] else "filename", None, list(a["tags"]), a["kind"], a["mime"], a["filename"].rsplit(".", 1)[-1], 10, a["sha"],
                a["status"], "not_applicable", "ready", "not_applicable", a["source_id"], a["source_kind"], dict(a["media"]),
                uuid.UUID(hex=a["duplicate_of"]) if a["duplicate_of"] else None, {}, a["created"])

    def _coordinator(self, sql, args):
        if sql.startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")):
            return []
        if "FROM public.pr_library_assets WHERE workspace_id=%s AND id=ANY(%s::uuid[])" in sql:
            wanted = {uuid.UUID(x).hex for x in args[1]}
            return [self._vrow(key) for key in self.assets if key in wanted]
        if "FROM public.pr_library_assets WHERE workspace_id=%s AND (id=%s OR lineage_id=%s)" in sql:
            key = args[1].hex
            rows = [x for x, a in self.assets.items() if (x == key or a["lineage"] == key) and a["status"] not in ("deleting", "duplicate")]
            return [self._vrow(x) for x in sorted(rows, key=lambda x: (self.assets[x]["version_no"], self.assets[x]["created"]))]
        if sql.startswith("SELECT replace(id::text,'-',''),processing_status FROM public.pr_library_assets"):
            return [(x, a["status"]) for x, a in self.assets.items() if a["status"] not in ("deleting", "duplicate")]
        if "FROM public.pr_library_labels" in sql:
            return []
        if "SELECT grant_revision FROM public.pr_library_policy" in sql:
            return [(self.policy["grant"],)]
        if "SELECT grant_revision,index_generation,organization_revision FROM public.pr_library_policy" in sql:
            return [(self.policy["grant"], self.policy["index"], self.policy["org"])]
        if sql.startswith("INSERT INTO public.pr_library_policy"):
            grant, index, org = args[4], args[5], args[6]
            self.policy["grant"] += grant
            self.policy["index"] += index
            self.policy["org"] += org
            return [(self.policy["grant"], self.policy["index"], self.policy["org"])]
        if "FROM public.pr_library_grants WHERE workspace_id=%s AND revoked_at IS NULL" in sql:
            return [(g["id"], g["grantType"], g["scopeKind"], g["scopeKey"], g["memberKeys"], g["purpose"], g.get("location"), g.get("category"), {},
                     ACTOR, 1, 1.0) for g in self.grants]
        if sql.startswith("INSERT INTO public.pr_audit_events"):
            self.audits.append((args[2], args[3], json.loads(args[4])))
            return []
        if sql.startswith("SELECT pg_advisory_xact_lock("):
            return [(None,)]  # actions serialize identical idempotency keys
        if "FROM public.pr_library_action_receipts" in sql:
            row = self.receipts.get(args[1])
            return [row] if row else []
        if sql.startswith("INSERT INTO public.pr_library_action_receipts"):
            self.receipts.setdefault(args[1], (args[2], args[4], args[5], json.loads(args[6])))
            return []
        raise AssertionError("unexpected SQL: " + sql[:160])

    def _ws_state(self, args):
        return [(self.state,)]

    # --- collections -----------------------------------------------------------------------------------------------------
    def _crow(self, cid):
        x = self.collections[cid]
        return (str(uuid.UUID(hex=cid)), x["name"], x["kind"], copy.deepcopy(x["rule"]), x["rule_schema"], x["explanation"], x["revision"],
                x["last_eval"], ACTOR, x["created"], x["updated"])

    def _coll_get(self, args):
        cid = args[1].hex
        return [self._crow(cid)] if cid in self.collections else []

    _coll_lock = _coll_get

    def _coll_count(self, args):
        return [(len(self.collections),)]

    def _coll_name_taken(self, args):
        name, own = args[1], args[2].hex if args[2] else None
        return [(1,)] if any(x["name"] == name and cid != own for cid, x in self.collections.items()) else []

    def _coll_insert(self, args):
        cid, name = args[0].hex, args[2]
        if any(x["name"] == name for x in self.collections.values()):
            return []
        self.collections[cid] = {"name": name, "kind": "smart", "rule": json.loads(args[4]), "rule_schema": args[5], "explanation": args[6],
                                 "revision": 1, "last_eval": None, "created": self.now, "updated": self.now}
        return [(1,)]

    def add_manual(self, cid, name):
        self.collections[cid] = {"name": name, "kind": "manual", "rule": None, "rule_schema": None, "explanation": None, "revision": 1,
                                 "last_eval": None, "created": self.now, "updated": self.now}

    def _coll_update(self, args):
        name, rule, schema, explanation, _, cid, expected = args
        x = self.collections.get(cid.hex)
        if not x or x["revision"] != expected:
            return []
        x.update(name=name, rule=json.loads(rule), rule_schema=schema, explanation=explanation, revision=x["revision"] + 1, updated=self.now)
        return [(x["revision"],)]

    def _coll_bump(self, args):
        x = self.collections.get(args[1].hex)
        if not x or x["revision"] != args[2]:
            return []
        x.update(revision=x["revision"] + 1, updated=self.now)
        return [(x["revision"],)]

    def _coll_evaluated(self, args):
        self.collections[args[2].hex].update(last_eval=args[0], updated=self.now)
        return []

    def _coll_smart(self, args):
        return [(str(uuid.UUID(hex=cid)), copy.deepcopy(x["rule"]), x["revision"]) for cid, x in self.collections.items() if x["kind"] == "smart" and x["rule"]]

    def _coll_due(self, args):
        seconds, limit = args
        due = [(cid, x) for cid, x in self.collections.items() if x["kind"] == "smart" and x["rule"] and
               (x["last_eval"] != x["revision"] or x["updated"] < self.now - seconds)]
        due.sort(key=lambda item: (item[1]["last_eval"] == item[1]["revision"], item[1]["updated"]))
        return [(WS, str(uuid.UUID(hex=cid))) for cid, _ in due[:limit]]

    def _coll_try(self, args):
        x = self.collections.get(args[1].hex)
        return [(str(args[1]), copy.deepcopy(x["rule"]), x["revision"], x["kind"])] if x else []

    def _items_list(self, args):
        cid = args[1].hex
        return [(key, row) for (coll, key), row in self.items.items() if coll == cid]

    def _items_for(self, args):
        cid, keys = args[1].hex, set(args[2])
        return [(key, row) for (coll, key), row in self.items.items() if coll == cid and key in keys]

    def _items_delete(self, args):
        cid = args[1].hex
        for key in args[2]:
            self.items.pop((cid, key), None)
        return []

    def _items_upsert(self, args):
        cid = args[1].hex
        for key, origin in zip(args[2], args[3]):
            self.items[(cid, key)] = origin
        return []

    def _items_count(self, args):
        cid = args[1].hex
        counts = {}
        for (coll, _), origin in self.items.items():
            if coll == cid:
                counts[origin] = counts.get(origin, 0) + 1
        return list(counts.items())

    def _ovr_list(self, args):
        cid = args[1].hex
        return [(key, mode) for (coll, key), mode in self.overrides.items() if coll == cid]

    def _ovr_for(self, args):
        cid, keys = args[1].hex, set(args[2])
        return [(key, mode) for (coll, key), mode in self.overrides.items() if coll == cid and key in keys]

    def _ovr_put(self, args):
        cid, mode = args[1].hex, args[2]
        for key in args[4]:
            self.overrides[(cid, key)] = mode
        return []

    def _ovr_delete(self, args):
        cid = args[1].hex
        for key in args[2]:
            self.overrides.pop((cid, key), None)
        return []

    def _ovr_clear(self, args):
        cid = args[1].hex
        for key in [kk for kk in self.overrides if kk[0] == cid]:
            del self.overrides[key]
        return []

    def _rev_put(self, args):
        key = (args[1].hex, args[2])
        assert key not in self.revisions, "a revision snapshot is never overwritten"
        self.revisions[key] = {"snapshot": json.loads(args[3]), "by": args[4], "at": self.now}
        return []

    def _rev_get(self, args):
        row = self.revisions.get((args[1].hex, args[2]))
        return [(copy.deepcopy(row["snapshot"]),)] if row else []

    def _rev_list(self, args):
        cid = args[1].hex
        rows = sorted(((rev, row) for (coll, rev), row in self.revisions.items() if coll == cid), key=lambda item: -item[0])
        return [(rev, copy.deepcopy(row["snapshot"]), row["by"], row["at"]) for rev, row in rows[:args[2]]]

    def _lineage_keys(self, args):
        wanted = {uuid.UUID(x).hex for x in args[1]}
        return [(key,) for key, a in self.assets.items() if (a["lineage"] or key) in wanted]

    # --- facts ----------------------------------------------------------------------------------------------------------
    def _facts_annotations(self, args):
        fields, keys = set(args[1]), set(args[2])
        return [row for row in self.annotations if row[0] in keys and row[1] in fields]

    def _facts_languages(self, args):
        return [(key, list(langs)) for key, langs in self.languages.items() if key in set(args[1])]

    def _facts_caps(self, args):
        return [(key, cap, state) for (key, cap), state in self.caps.items() if key in set(args[1])]

    def _facts_usage(self, args):
        akeys, vkeys = set(args[1]), set(args[2])
        return [(a, v) for a, v in self.usage if a in akeys or v in vkeys]

    def _facts_used_in(self, args):
        keys = set(args[1])
        return [(r["from_version"],) for r in self.relations if r["relation"] == "used_in" and r["status"] in ("active", "stale") and r["from_version"] in keys]

    def _facts_text(self, args):
        terms, keys = [t.strip() for t in args[1].split("&")], set(args[2])
        return [(key,) for key, text in self.text.items() if key in keys and all(t in text.split() for t in terms)]

    def _facts_chunks(self, args):
        keys = {uuid.UUID(str(x)).hex for x in args[1]}
        raw, folded = ([p.strip("%").lower() for p in group] for group in (args[2], args[3]))
        return [(key,) for key, parts in self.chunks.items() if key in keys and
                (all(w in " ".join(parts).lower() for w in raw) or all(w in " ".join(parts).lower() for w in folded))]

    # --- relations ------------------------------------------------------------------------------------------------------
    def _identity(self, r):
        return (r["from_key"], r["from_version"], r["relation"], r["to_kind"], r["to_key"], r["to_version"] or "", r["from_segment"] or "")

    def _rel_insert(self, args):
        row = dict(zip(("id", "ws", "from_key", "from_version", "from_segment", "to_kind", "to_key", "to_version", "relation", "status", "origin",
                        "evidence", "created_by"), args))
        row["id"] = row["id"].hex
        row["evidence"] = json.loads(row["evidence"])
        row["created"] = self.now + len(self.relations)
        if any(self._identity(r) == self._identity(row) for r in self.relations):
            return []
        self.relations.append(row)
        return [(row["id"],)]

    def _rel_find(self, args):
        _, from_version, relation, to_kind, to_key, to_version = args
        for r in self.relations:
            if (r["from_version"], r["relation"], r["to_kind"], r["to_key"], r["to_version"] or "") == (from_version, relation, to_kind, to_key, to_version) \
                    and not r["from_segment"]:
                return [(r["id"], r["status"], copy.deepcopy(r["evidence"]))]
        return []

    def _rel_set(self, args):
        status, evidence, _, rid = args
        for r in self.relations:
            if r["id"] == rid.hex:
                r["status"] = status
                r["evidence"] = {**r["evidence"], **json.loads(evidence)}
        return []

    def _rel_stale_used(self, args):
        evidence, _, from_version = args
        out = []
        for r in self.relations:
            if r["from_version"] == from_version and r["relation"] == "used_in" and r["status"] in ("active", "stale"):
                if r["status"] == "active":
                    r["status"] = "stale"
                    r["evidence"] = {**r["evidence"], **json.loads(evidence)}
                out.append((r["id"], r["to_kind"], r["to_key"]))
        return out

    def _rel_out(self, args):
        kinds, keys = set(args[1]), set(args[2])
        return [(r["from_version"], r["to_version"]) for r in self.relations if r["to_kind"] == "asset" and r["relation"] in kinds and r["status"] == "active"
                and r["from_version"] in keys and r["to_version"]]

    def _rel_in(self, args):
        kinds, keys = set(args[1]), set(args[2])
        return [(r["from_version"], r["to_version"]) for r in self.relations if r["to_kind"] == "asset" and r["relation"] in kinds and r["status"] == "active"
                and r["to_version"] in keys]

    def _list_row(self, r):
        return (r["id"], r["from_key"], r["from_version"], r["from_segment"], r["to_kind"], r["to_key"], r["to_version"], r["relation"], r["status"],
                r["origin"], copy.deepcopy(r["evidence"]), r["created"])

    def _rel_list_out(self, args):
        keys = set(args[1])
        return [self._list_row(r) for r in self.relations if r["from_version"] in keys][:args[2]]

    def _rel_list_in(self, args):
        keys = set(args[1])
        return [self._list_row(r) for r in self.relations if r["to_kind"] == "asset" and r["to_version"] in keys][:args[2]]

    def _asset_lock(self, args):
        key = args[1].hex
        a = self.assets.get(key)
        return [(key, a["lineage"] or key, a["version_no"])] if a else []

    def _asset_children(self, args):
        key = args[1].hex
        return [(sum(1 for x, a in self.assets.items() if a["lineage"] == key and x != key),)]

    def _asset_maxver(self, args):
        key = args[1].hex
        return [(max([a["version_no"] for x, a in self.assets.items() if (a["lineage"] or x) == key] or [0]),)]

    def _asset_restack(self, args):
        lineage, version_no, _, key = args[0].hex, args[1], args[2], args[3].hex
        a = self.assets[key]
        if a["lineage"] not in (None, key):
            return []
        a.update(lineage=lineage, version_no=version_no)
        return [(version_no,)]

    def _packs_citing(self, args):
        key = args[1]
        return [(str(uuid.UUID(hex=pid)), p["revision"], p["status"], p.get("draft_id"), p["created_by"], copy.deepcopy(p["evidence_refs"]),
                 copy.deepcopy(p["style_refs"])) for pid, p in self.packs.items()
                if p["status"] in ("draft", "attached") and (key in json.dumps(p["evidence_refs"]) or key in json.dumps(p["style_refs"]))]

    def _pack_lock(self, args):
        p = self.packs.get(args[1].hex)
        return [(str(args[1]), p["revision"], p["status"], copy.deepcopy(p["evidence_refs"]), copy.deepcopy(p["style_refs"]),
                 copy.deepcopy(p["rights_warnings"]), p.get("draft_id"))] if p else []

    def _pack_replace(self, args):
        evidence, style, warnings, _, pid, expected = args
        p = self.packs.get(pid.hex)
        if not p or p["revision"] != expected:
            return []
        p.update(evidence_refs=json.loads(evidence), style_refs=json.loads(style), rights_warnings=json.loads(warnings), revision=p["revision"] + 1)
        return [(p["revision"],)]

    # --- suggestions (the statements the version-link warning path uses; the suggestions suite adds the rest) -------------
    def _sugg_lock(self, args):
        return []

    def _sugg_members(self, args):
        return [(m,) for m in self.workspace_members[:args[1]]]

    def _sugg_is_member(self, args):
        return [(u,) for u in args[1] if u in self.workspace_members]

    def _sugg_prefs(self, args):
        wanted = set(args[1])
        return [(r, cat, p["disabled"], p["snooze_days"], p["external_opt_in"]) for (r, cat), p in self.prefs.items() if r in wanted]

    def _sugg_today(self, args):  # across every workspace, like the real statement
        counts = {}
        for s in self.suggestions:
            if s["recipient"] in args[0] and not s["critical"] and s["created"] > self.now - args[1]:
                counts[s["recipient"]] = counts.get(s["recipient"], 0) + 1
        return list(counts.items())

    def _sugg_put(self, args):
        row = dict(zip(("id", "ws", "recipient", "dedup", "category", "critical", "trigger", "candidates", "affected", "reason", "consent", "expires_days"),
                       args))
        if any((s["recipient"], s["dedup"]) == (row["recipient"], row["dedup"]) for s in self.suggestions):
            return []
        for name in ("trigger", "candidates", "affected"):
            row[name] = json.loads(row[name])
        row.update(id=row["id"].hex, state="new", snooze=None, created=self.now,
                   expires=None if row["expires_days"] is None else self.now + row["expires_days"] * 86400)
        self.suggestions.append(row)
        return [(str(uuid.UUID(hex=row["id"])), row["created"])]

    def _vec_column(self, args):
        return [(1,)] if self.vector else []

    def _vec_near(self, args):
        return list(self.neighbors.get(args[1], []))

    def _dup_exact(self, args):
        key = args[1].hex
        return [(sum(1 for a in self.assets.values() if a["duplicate_of"] == key and a["status"] == "duplicate"),)]

    # --- comparison -----------------------------------------------------------------------------------------------------
    def _cmp_segments(self, args):
        return [(s["id"], s["ordinal"], s["kind"], s["text"], s.get("locator"), s.get("language")) for s in self.segments.get(args[1], [])][:args[2]]

    def _cmp_chunks(self, args):
        return list(enumerate(self.chunks.get(args[1].hex, [])))[:args[2]]

    def _cmp_usage(self, args):
        return [("post_published", None, "post-1", "instagram", False) for a, v in self.usage if v == args[1] or (v is None and a == args[2])][:args[3]]

    def _cmp_used_in(self, args):
        return [(r["to_kind"], r["to_key"], r["status"]) for r in self.relations if r["from_version"] == args[1] and r["relation"] == "used_in"][:args[2]]

    def _cmp_affected(self, args):
        keys = set(args[1])
        return [(r["from_version"], r["to_kind"], r["to_key"], r["status"], copy.deepcopy(r["evidence"])) for r in self.relations
                if r["from_version"] in keys and r["relation"] == "used_in" and r["status"] == "stale"][:args[2]]


def context(db, role="owner", actor=ACTOR):
    ctx = c.LibraryContext(workspace_id=WS, actor=actor, membership=Membership(role), state=db.state, cur=db, now=db.now,
                           service=SimpleNamespace(storage=Spy()))
    return ctx


def ref(db, key):
    a = db.assets[key]
    return {"assetId": a["lineage"] or key, "versionId": key, "sha256": a["sha"]}


def envelope(action_type, *, targets=(), revision=None, payload=None, key=None):
    return {"actionId": "act-1", "uiInstanceId": "ui-1", "actionType": action_type, "targetRefs": list(targets), "expectedRevision": revision,
            "idempotencyKey": key or ("idem-" + uuid.uuid4().hex), "payload": payload or {}}


ASSET_WRITE = r"(INSERT INTO|UPDATE|DELETE FROM) public\.pr_library_(assets|chunks)\b"


# ======================================================================================================================
class RuleLanguage(unittest.TestCase):
    def test_rule_sql_rejected(self):
        bad = [
            "SELECT * FROM public.pr_library_assets WHERE kind='audio'",
            ["kind", "audio"],
            {"sql": "SELECT 1"},
            {"where": "kind = 'audio'"},
            {"prompt": "find my best rehearsal audio"},
            {"all": [{"field": "raw_sql", "op": "eq", "value": "1=1"}]},
            {"all": [{"field": "kind", "op": "exec", "value": ["audio"]}]},
            {"all": [{"field": "kind", "op": "in", "value": ["audio"], "expression": "__import__('os')"}]},
            {"all": [{"field": "title_contains", "op": "contains", "value": "x'; DROP TABLE pr_library_assets;--"}]},
            {"all": [{"field": "title_contains", "op": "contains", "value": "select id from pr_library_assets"}]},
            {"all": [{"field": "kind", "op": "in", "value": "audio"}]},
            {"all": []},
            {"all": [{"field": "text_matches", "op": "matches", "value": "?!"}]},
            {"all": [{"field": "created_after", "op": "on_or_after", "value": "2026-02-30"}]},
            {"all": [{"field": "created_after", "op": "on_or_after", "value": "2026-10-01", "timeZone": "Mars/Olympus"}]},
        ]
        for rule in bad:
            with self.subTest(rule=rule), self.assertRaises(AlphaError) as raised:
                collections.validate_rule(rule)
            self.assertEqual((raised.exception.status, raised.exception.code), (400, "library_rule_invalid"), (rule, str(raised.exception)))
        with self.assertRaises(AlphaError) as unknown:
            collections.validate_rule({"all": [{"field": "raw_sql", "op": "eq", "value": "1"}]})
        self.assertIn("raw_sql", str(unknown.exception), "the 400 names what was rejected")

        pred = {"field": "kind", "op": "in", "value": ["audio"]}
        nested = pred
        for depth in range(4):
            nested = {"all": [nested]}
        self.assertTrue(collections.validate_rule(nested))  # four group levels are allowed
        with self.assertRaises(AlphaError) as deep:
            collections.validate_rule({"any": [nested]})
        self.assertIn("4", str(deep.exception))
        self.assertTrue(collections.validate_rule({"all": [pred] * 40}))
        with self.assertRaises(AlphaError) as big:
            collections.validate_rule({"all": [pred] * 41})
        self.assertIn("40", str(big.exception))

        # Through the HTTP and action surfaces nothing derived from the rejected text reaches SQL.
        db = OrgDB()
        ctx = context(db)
        injected = "SELECT * FROM public.pr_library_assets"
        with self.assertRaises(AlphaError) as http:
            collections.preview_http(ctx, {"params": {}, "query": {}, "body": {"rule": injected}})
        self.assertEqual(http.exception.status, 400)
        with self.assertRaises(AlphaError) as via_action:
            actions.apply(ctx, envelope("collection.save", payload={"name": "x", "rule": {"where": "1=1"}}))
        self.assertEqual(via_action.exception.status, 400)
        self.assertFalse(any(injected in json.dumps(args, default=str) or "1=1" in json.dumps(args, default=str) for _, args in db.executed))
        self.assertEqual(db.collections, {})

    def test_explanation_matches_rule(self):
        rule = {"all": [{"field": "kind", "op": "in", "value": ["audio"]},
                        {"field": "tag", "op": "has", "value": "rehearsal"},
                        {"any": [{"field": "title_contains", "op": "contains", "value": "Brahms"},
                                 {"field": "text_matches", "op": "matches", "value": "演奏會"}]},
                        {"field": "created_after", "op": "on_or_after", "value": "2026-10-01", "timeZone": "Asia/Hong_Kong"},
                        {"field": "tag", "op": "has", "value": "warmup", "origin": "ai_suggested"}]}
        normalized = collections.validate_rule(rule)
        text = collections.explain(normalized)
        self.assertEqual(text, "Current Library items that are audio and are tagged “rehearsal” and (have “Brahms” in the title or mention "
                               "“演奏會” in their text) and were added on or after 2026-10-01 (Asia/Hong_Kong time) and have the AI-suggested "
                               "tag “warmup” (a suggestion, not confirmed).")
        # Deterministic: key order and duplicate list values do not change the normalized rule or its wording.
        shuffled = {"all": [{"value": ["audio", "audio"], "op": "in", "field": "kind"}, *rule["all"][1:]]}
        self.assertEqual(collections.validate_rule(shuffled), normalized)
        self.assertEqual(collections.explain(collections.validate_rule(shuffled)), text)
        # Every predicate is represented; changing a value changes the explanation.
        changed = copy.deepcopy(rule)
        changed["all"][1]["value"] = "concert"
        self.assertNotEqual(collections.explain(collections.validate_rule(changed)), text)
        self.assertIn("“concert”", collections.explain(collections.validate_rule(changed)))
        for phrase, node in (("are not tagged “x”", {"not": {"field": "tag", "op": "has", "value": "x"}}),
                             ("have transcription ready or partial", {"field": "capability", "op": "in", "capability": "transcribe", "value": ["partial", "ready"]}),
                             ("have not been used yet", {"field": "usage", "op": "eq", "value": "unused"}),
                             ("are at least 1:30 long", {"field": "duration_ms", "op": "gte", "value": 90000}),
                             ("were added by quick note or upload", {"field": "source_kind", "op": "in", "value": ["upload", "note"]}),
                             ("have content in yue or en", {"field": "language", "op": "in", "value": ["yue", "en"]}),
                             ("are portrait", {"field": "orientation", "op": "eq", "value": "portrait"}),
                             ("have a content type starting with “audio/”", {"field": "mime_prefix", "op": "starts_with", "value": "audio/"}),
                             ("have “op118” in the file name", {"field": "filename_contains", "op": "contains", "value": "op118"}),
                             ("were added before 2026-01-01 (UTC time)", {"field": "created_before", "op": "before", "value": "2026-01-01"})):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, collections.explain(collections.validate_rule(node)))

        # The stored explanation is generated by the server from the saved rule; a client cannot supply one.
        db = OrgDB()
        ctx = context(db)
        saved = collections.save_collection(ctx, rule, None, name="Brahms rehearsals")["collection"]
        self.assertEqual(saved["explanation"], text)
        self.assertEqual(db.collections[saved["id"]]["explanation"], text)
        detail = collections.collection_http(ctx, {"params": {"key": saved["id"]}, "query": {}, "body": {}})
        self.assertEqual(detail["collection"]["explanation"], text)
        self.assertEqual(detail["history"][0]["explanation"], text)
        self.assertFalse(detail["canUndo"], "a new collection has nothing earlier to restore")
        with self.assertRaises(AlphaError) as forged:
            actions.apply(ctx, envelope("collection.save", payload={"name": "y", "rule": AUDIO, "explanation": "Everything, trust me"}))
        self.assertEqual(forged.exception.status, 400)

    def test_pure_predicates(self):
        rule = collections.validate_rule
        facts = {"key": A, "assetId": A, "versionId": A, "kind": "audio", "tags": ["rehearsal"], "aiTags": ["warmup"], "title": "Brahms Op.118",
                 "filename": "op118-take2.m4a", "createdAt": 1_790_000_000.0, "mime": "audio/mp4", "languages": ["yue", "zh-Hant"],
                 "capabilities": {"transcribe": "ready"}, "sourceKind": "upload", "durationMs": 95_000, "orientation": None, "used": False, "current": True}
        ev = collections.evaluate
        self.assertTrue(ev(rule({"field": "language", "op": "in", "value": ["zh"]}), facts))
        self.assertFalse(ev(rule({"field": "language", "op": "in", "value": ["zh-Hans"]}), facts))
        self.assertTrue(ev(rule({"field": "capability", "op": "in", "capability": "transcribe", "value": ["ready"]}), facts))
        self.assertTrue(ev(rule({"field": "capability", "op": "in", "capability": "visual", "value": ["not_requested"]}), facts))
        self.assertTrue(ev(rule({"field": "duration_ms", "op": "gte", "value": 90_000}), facts))
        self.assertFalse(ev(rule({"field": "orientation", "op": "eq", "value": "portrait"}), facts), "unknown orientation never matches")
        self.assertTrue(ev(rule({"field": "usage", "op": "eq", "value": "unused"}), facts))
        self.assertTrue(ev(rule({"field": "title_contains", "op": "contains", "value": "brahms"}), facts))
        self.assertTrue(ev(rule({"field": "filename_contains", "op": "contains", "value": "TAKE2"}), facts))
        self.assertTrue(ev(rule({"field": "mime_prefix", "op": "starts_with", "value": "audio/"}), facts))
        self.assertTrue(ev(rule({"field": "tag", "op": "has_any", "value": ["concert", "Rehearsal"]}), facts))
        # AI-suggested tags are usable only when the rule says so.
        self.assertFalse(ev(rule({"field": "tag", "op": "has", "value": "warmup"}), facts))
        self.assertTrue(ev(rule({"field": "tag", "op": "has", "value": "warmup", "origin": "ai_suggested"}), facts))
        self.assertTrue(ev(rule({"field": "tag", "op": "has", "value": "warmup", "origin": "any"}), facts))
        self.assertFalse(ev(rule({"field": "tag", "op": "has", "value": "rehearsal", "origin": "ai_suggested"}), facts))
        hits = {collections.text_key("演奏会"): {A}}
        self.assertTrue(ev(rule({"field": "text_matches", "op": "matches", "value": "演奏會"}), facts, hits), "Simplified/Traditional fold to one key")
        self.assertFalse(ev(rule({"not": {"field": "kind", "op": "in", "value": ["audio"]}}), facts))

    def test_timezone_boundary(self):
        hk = collections.validate_rule({"field": "created_after", "op": "on_or_after", "value": "2026-10-01", "timeZone": "Asia/Hong_Kong"})
        # 2026-10-01 00:00 in Hong Kong is 2026-09-30 16:00 UTC (epoch 1790784000); UTC midnight is eight hours later.
        start = 1790784000.0
        base = {"key": A, "kind": "audio", "tags": [], "aiTags": [], "current": True}
        self.assertTrue(collections.evaluate(hk, {**base, "createdAt": start}))
        self.assertFalse(collections.evaluate(hk, {**base, "createdAt": start - 1}))
        utc = collections.validate_rule({"field": "created_before", "op": "before", "value": "2026-10-01"})
        self.assertTrue(collections.evaluate(utc, {**base, "createdAt": start + 8 * 3600 - 1}))
        self.assertFalse(collections.evaluate(utc, {**base, "createdAt": start + 8 * 3600}))


# ======================================================================================================================
class SmartCollections(unittest.TestCase):
    def setUp(self):
        self.db = OrgDB()
        self.db.add(A, kind="audio", tags=["Rehearsal"])
        self.db.add(B, kind="document", tags=["rehearsal"])
        self.db.add(C, kind="audio")
        self.ctx = context(self.db)

    def save(self, rule=RULE, name="Rehearsals"):
        return collections.save_collection(self.ctx, rule, None, name=name)["collection"]

    def test_incremental_membership(self):
        db = self.db
        saved = self.save()
        cid = saved["id"]
        self.assertEqual(db.members(cid), {A: "rule"})
        self.assertEqual((saved["revision"], saved["memberCount"], db.collections[cid]["last_eval"]), (1, 1, 1))
        self.assertEqual(db.policy["org"], 1, "saving bumps the organization revision")
        self.assertEqual(db.revisions[(cid, 1)]["snapshot"]["rule"], collections.validate_rule(RULE))

        db.add(E, kind="audio", tags=["rehearsal"], status="queued")
        self.assertEqual(collections.reevaluate_for_asset(db, WS, E)["status"], "ok")
        self.assertNotIn(E, db.members(cid), "an upload still processing does not join yet")

        db.assets[E]["status"] = "ready"
        db.executed.clear()
        result = collections.reevaluate_for_asset(db, WS, E)
        self.assertEqual((result["status"], result["collections"]), ("ok", 1))
        self.assertEqual(db.members(cid)[E], "rule")
        loads = [args for sql, args in db.executed if "id=ANY(%s::uuid[])" in sql and "pr_library_assets" in sql]
        self.assertTrue(loads and all({uuid.UUID(x).hex for x in args[1]} == {E} for args in loads), "only the changed lineage is evaluated")
        self.assertFalse(db.sql(r"SELECT replace\(id::text,'-',''\),processing_status"), "no whole-workspace scan for one change")

        db.assets[E]["tags"] = []
        collections.reevaluate_for_asset(db, WS, E)
        self.assertNotIn(E, db.members(cid), "a tag change removes the item")

        # A newer processed version becomes the current one: the old head leaves, the new head joins.
        db.add(F, kind="audio", tags=["rehearsal"], lineage=A, version_no=2)
        collections.reevaluate_for_asset(db, WS, F)
        self.assertEqual(set(db.members(cid)), {F})

        # A missed event (no hook call) is repaired by bounded periodic reconciliation.
        db.add(G, kind="audio", tags=["rehearsal"])
        db.collections[cid]["updated"] = db.now - 3600
        summary = collections.reconcile_due(None, db.connect)
        self.assertEqual(summary["status"], "ok")
        self.assertGreaterEqual(summary["added"], 1)
        self.assertEqual(db.members(cid).get(G), "rule")
        fresh = collections.reconcile_due(None, db.connect)
        self.assertEqual(fresh["checked"], 0, "a just-evaluated collection is not due again")

        # Hook failures never raise into the caller (job finalize), and reconciliation reports errors instead of crashing tick.
        db.fail_on = "lio:items.for"
        self.assertEqual(collections.reevaluate_for_asset(db, WS, G)["status"], "error")
        db.fail_on = "lio:coll.due"
        self.assertEqual(collections.reconcile_due(None, db.connect)["status"], "error")
        db.fail_on = None
        self.assertEqual(collections.reevaluate_for_asset(db, WS, "not-a-key")["status"], "invalid")

    def test_exclude_override_wins(self):
        db = self.db
        cid = self.save(AUDIO, name="All audio")["id"]
        self.assertEqual(set(db.members(cid)), {A, C})
        out = collections.set_overrides(self.ctx, cid, [A], "exclude", 1)
        self.assertEqual(out["collection"]["revision"], 2)
        self.assertEqual(set(db.members(cid)), {C})
        db.assets[A]["tags"] = ["still audio"]
        collections.reevaluate_for_asset(db, WS, A)
        self.assertNotIn(A, db.members(cid), "exclusion beats automatic inclusion on incremental evaluation")
        broadened = collections.save_collection(self.ctx, {"all": [{"field": "kind", "op": "in", "value": ["audio", "document"]}]}, 2, collection_id=cid)
        self.assertEqual(set(db.members(cid)), {B, C}, "and on a full re-evaluation after a rule change")
        self.assertEqual(broadened["collection"]["overrides"], {"include": 0, "exclude": 1})
        # Manual include of a non-matching item, and a forged/unavailable include, through the action surface.
        db.add(D, kind="image")
        included = actions.apply(self.ctx, envelope("collection.override", targets=[ref(db, D)], revision=3, payload={"collectionId": cid, "mode": "include"}))
        self.assertEqual(included["status"], "applied", included)
        self.assertEqual(db.members(cid)[D], "include")
        foreign = actions.apply(self.ctx, envelope("collection.override", targets=[{"assetId": X, "versionId": X, "sha256": ""}], revision=4,
                                                   payload={"collectionId": cid, "mode": "include"}))
        self.assertEqual(foreign["status"], "denied")
        self.assertNotIn(X, db.members(cid))
        # Pure membership: exclude wins over both rule and include; includes need an accessible item.
        facts = {A: {"key": A, "kind": "audio", "current": True}, D: {"key": D, "kind": "image", "current": True}}
        rule = collections.validate_rule(AUDIO)
        self.assertEqual(collections.membership(rule, facts, {A: "exclude", D: "include", X: "include"}), {D: "include"})

    def test_no_byte_copy(self):
        db = self.db
        before = copy.deepcopy(db.assets)
        cid = self.save(AUDIO)["id"]
        preview = collections.preview_collection(self.ctx, collections.validate_rule(RULE), None, collection_id=cid)
        collections.set_overrides(self.ctx, cid, [C], "exclude", 1)
        collections.reevaluate_for_asset(db, WS, A)
        collections.undo(self.ctx, cid, 2)
        self.assertEqual(db.assets, before, "no Library row is created or changed")
        self.assertFalse(db.sql(ASSET_WRITE), "membership never writes asset rows or extracted text")
        self.assertEqual(self.ctx.service.storage.calls, [], "private storage is never touched")
        for (coll, key), origin in db.items.items():
            self.assertTrue(c.KEY.fullmatch(key) and origin in ("rule", "include", "manual"))
        for member in preview["members"]:
            self.assertEqual(set(member) - {"assetRef", "origin", "title", "kind", "provenance"}, set())
            self.assertEqual(set(member["assetRef"]), {"assetId", "versionId", "sha256"})
        self.assertNotIn("url", json.dumps(preview))

    def test_concurrent_revision_conflict(self):
        db = self.db
        cid = self.save()["id"]
        first = collections.save_collection(self.ctx, AUDIO, 1, collection_id=cid)
        self.assertEqual(first["collection"]["revision"], 2)
        with self.assertRaises(AlphaError) as stale:
            collections.save_collection(self.ctx, {"all": [{"field": "kind", "op": "in", "value": ["document"]}]}, 1, collection_id=cid)
        self.assertEqual((stale.exception.status, stale.exception.code), (409, "library_collection_conflict"))
        self.assertEqual(db.collections[cid]["rule"], collections.validate_rule(AUDIO), "the losing save changed nothing")
        self.assertEqual(sorted(rev for coll, rev in db.revisions if coll == cid), [1, 2])
        with self.assertRaises(AlphaError) as missing:
            collections.save_collection(self.ctx, AUDIO, None, collection_id=cid)
        self.assertEqual(missing.exception.status, 409)
        outcome = actions.apply(self.ctx, envelope("collection.save", revision=1, payload={"collectionId": cid, "rule": AUDIO}))
        self.assertEqual(outcome["status"], "conflict")
        for action_type, payload in (("collection.undo", {"collectionId": cid}), ("collection.override", {"collectionId": cid, "mode": "exclude"})):
            targets = [ref(db, C)] if action_type == "collection.override" else []
            self.assertEqual(actions.apply(self.ctx, envelope(action_type, targets=targets, revision=1, payload=payload))["status"], "conflict")
        viewer = context(db, role="viewer")
        self.assertEqual(actions.apply(viewer, envelope("collection.save", revision=2, payload={"collectionId": cid, "rule": RULE}))["status"], "denied")

    def test_undo_does_not_restore_revoked_access(self):
        db = self.db
        db.add(X, kind="document")
        cid = self.save(AUDIO)["id"]                                   # r1: {A, C}
        collections.set_overrides(self.ctx, cid, [X], "include", 1)  # r2: + X
        collections.set_overrides(self.ctx, cid, [A], "exclude", 2)  # r3: - A
        self.assertEqual(set(db.members(cid)), {C, X})
        db.grants.append({"id": k(0x6A), "grantType": "purpose", "scopeKind": "collection", "scopeKey": cid, "memberKeys": [C], "purpose": "answer"})
        # X is deleted (or its access revoked) after r2 was recorded.
        db.assets[X]["status"] = "deleting"
        grant_writes_before = len(db.sql(r"pr_library_grants"))
        undone = collections.undo(self.ctx, cid, 3)
        self.assertEqual(undone["collection"]["revision"], 4, "undo is a new revision, not a rewrite")
        self.assertEqual(db.revisions[(cid, 4)]["snapshot"]["restoredRevision"], 2)
        self.assertEqual(db.revisions[(cid, 2)]["snapshot"]["overrides"], [{"assetKey": X, "mode": "include"}], "history is kept")
        self.assertEqual(set(db.members(cid)), {A, C}, "A returns (r2 had no exclusion); deleted X is never restored")
        self.assertNotIn((cid, X), db.overrides)
        self.assertTrue(any("no longer available" in w for w in undone["warnings"]), undone)
        self.assertFalse([s for s in db.sql(r"pr_library_grants")[grant_writes_before:] if not s.lstrip().startswith("SELECT")],
                         "undo never writes grants")
        version_a = versions.get(self.ctx, A)
        self.assertFalse(policy.authorize_source(self.ctx, version_a, "answer").allowed,
                         "rejoining a collection never broadens a fixed collection grant")
        self.assertTrue(collections.collection_http(self.ctx, {"params": {"key": cid}, "query": {}, "body": {}})["canUndo"])
        again = collections.undo(self.ctx, cid, 4)
        self.assertEqual(db.revisions[(cid, 5)]["snapshot"]["restoredRevision"], 1)
        self.assertEqual(set(db.members(cid)), {A, C})
        self.assertEqual(again["collection"]["overrides"], {"include": 0, "exclude": 0})
        self.assertFalse(collections.collection_http(self.ctx, {"params": {"key": cid}, "query": {}, "body": {}})["canUndo"])
        with self.assertRaises(AlphaError) as nothing:
            collections.undo(self.ctx, cid, 5)
        self.assertEqual((nothing.exception.status, nothing.exception.code), (409, "library_nothing_to_undo"))
        through_action = actions.apply(self.ctx, envelope("collection.undo", revision=4, payload={"collectionId": cid}))
        self.assertEqual(through_action["status"], "conflict")

    def test_preview_changes_pages_and_provenance(self):
        db = self.db
        cid = self.save(AUDIO)["id"]
        db.annotations.append((B, "tag", "rehearsal-plan", "ai_suggested"))
        rule = {"any": [{"field": "kind", "op": "in", "value": ["audio"]}, {"field": "tag", "op": "has", "value": "rehearsal-plan", "origin": "ai_suggested"}]}
        preview = collections.preview_http(self.ctx, {"params": {}, "query": {}, "body": {
            "rule": rule, "collectionId": cid, "overrides": {"exclude": [C], "include": [X]}, "limit": 1}})
        self.assertEqual(preview["count"], 2)
        self.assertEqual(len(preview["members"]), 1)
        self.assertEqual(preview["page"]["nextOffset"], 1)
        self.assertEqual(preview["changes"]["added"]["count"], 1)
        self.assertEqual(preview["changes"]["removed"]["count"], 1)
        self.assertEqual(preview["unavailableIncludes"], 1)
        second = collections.preview_http(self.ctx, {"params": {}, "query": {}, "body": {"rule": rule, "overrides": {"exclude": [C]}, "offset": 1, "limit": 1}})
        members = {m["assetRef"]["versionId"]: m for m in preview["members"] + second["members"]}
        self.assertEqual(members[B]["provenance"], ["ai_suggested_tag"], "AI-suggested matches are labelled")
        self.assertEqual(members[A].get("provenance", []), [])
        self.assertEqual(set(db.members(cid)), {A, C}, "preview writes nothing")
        self.assertEqual(preview["explanation"], collections.explain(collections.validate_rule(rule)))
        with self.assertRaises(AlphaError):
            collections.preview_http(self.ctx, {"params": {}, "query": {}, "body": {"rule": AUDIO, "overrides": {"include": [A], "exclude": [A]}}})
        result = actions.apply(self.ctx, envelope("collection.preview", payload={"rule": AUDIO}))
        self.assertEqual((result["status"], result["result"]["count"]), ("applied", 2))

    def test_manual_collections_and_limit(self):
        db = self.db
        manual = k(0x5A)
        db.add_manual(manual, "Hand picked")
        with self.assertRaises(AlphaError) as manual_save:
            collections.save_collection(self.ctx, AUDIO, 1, collection_id=manual)
        self.assertEqual(manual_save.exception.code, "library_collection_manual")
        with self.assertRaises(AlphaError) as manual_override:
            collections.set_overrides(self.ctx, manual, [A], "exclude", 1)
        self.assertEqual(manual_override.exception.code, "library_collection_manual")
        detail = collections.collection_http(self.ctx, {"params": {"key": manual}, "query": {}, "body": {}})
        self.assertEqual((detail["collection"]["kind"], detail["collection"]["rule"]), ("manual", None))
        with self.assertRaises(AlphaError) as taken:
            collections.save_collection(self.ctx, AUDIO, None, name="Hand picked")
        self.assertEqual(taken.exception.status, 409)
        for n in range(99):
            db.add_manual(k(0x1000 + n), f"m{n}")
        with self.assertRaises(AlphaError) as limit:
            collections.save_collection(self.ctx, AUDIO, None, name="One too many")
        self.assertEqual((limit.exception.status, limit.exception.code), (409, "library_collection_limit"))
        with self.assertRaises(AlphaError) as missing:
            collections.collection_http(self.ctx, {"params": {"key": k(0xDEAD)}, "query": {}, "body": {}})
        self.assertEqual(missing.exception.status, 404)

    def test_usage_language_capability_and_text_facts(self):
        db = self.db
        db.languages[A] = ["yue"]
        db.caps[(C, "transcribe")] = "ready"
        db.usage.append((A, None))
        db.state["phase2"]["jobs"].append({"id": "job1", "manifest": {"media": [{"id": C}], "idempotencyKey": "m1"}})
        db.text[B] = "演奏 奏會 演奏會 brahms"
        db.chunks[C] = ["Warm-up scales before the Brahms intermezzo"]
        db.chunks[A] = ["週末演奏會 rehearsal plan"]
        rule = {"all": [{"field": "usage", "op": "eq", "value": "used"}]}
        self.assertEqual({m["assetRef"]["versionId"] for m in collections.preview_collection(self.ctx, collections.validate_rule(rule), None)["members"]},
                         {A, C}, "usage events and legacy post jobs both count as used")
        for rule, expected in (({"field": "language", "op": "in", "value": ["yue"]}, {A}),
                               ({"field": "capability", "op": "in", "capability": "transcribe", "value": ["ready"]}, {C}),
                               ({"field": "text_matches", "op": "matches", "value": "演奏会"}, {A, B}),
                               ({"field": "text_matches", "op": "matches", "value": "brahms intermezzo"}, {C})):
            with self.subTest(rule=rule):
                got = collections.preview_collection(self.ctx, collections.validate_rule(rule), None)["members"]
                self.assertEqual({m["assetRef"]["versionId"] for m in got}, expected)


# ======================================================================================================================
class Lineage(unittest.TestCase):
    def setUp(self):
        self.db = OrgDB()
        for key in (A, B, C, D):
            self.db.add(key, kind="document")
        self.ctx = context(self.db)

    def test_cycle_rejected(self):
        edges = {"a": ["b"], "b": ["c"]}
        neighbors = lambda nodes: {n: edges.get(n, []) for n in nodes}  # noqa: E731
        self.assertTrue(relations.creates_cycle(neighbors, "c", "a"), "c -> a closes a -> b -> c")
        self.assertFalse(relations.creates_cycle(neighbors, "a", "c"))
        self.assertTrue(relations.creates_cycle(neighbors, "a", "a"))
        chain = {f"n{i}": [f"n{i + 1}"] for i in range(60)}
        with self.assertRaises(AlphaError) as large:
            relations.creates_cycle(lambda nodes: {n: chain.get(n, []) for n in nodes}, "z", "n0")
        self.assertEqual(large.exception.code, "library_lineage_too_large", "past the bound the check fails closed")
        corrupt = {"x": ["y"], "y": ["x", "z"]}
        walked = relations.traverse(lambda nodes: {n: corrupt.get(n, []) for n in nodes}, "x")
        self.assertEqual(sorted(n["key"] for n in walked["nodes"]), ["y", "z"], "a cycle already in the data is walked once")
        wide = {"root": [f"w{i}" for i in range(600)]}
        bounded = relations.traverse(lambda nodes: {n: wide.get(n, []) for n in nodes}, "root")
        self.assertTrue(bounded["truncated"])
        self.assertLessEqual(len(bounded["nodes"]), relations.MAX_NODES)

        db = self.db
        relations.link_versions(self.ctx, {"relation": "derived_from", "from": ref(db, A), "to": ref(db, B)})
        relations.link_versions(self.ctx, {"relation": "derived_from", "from": ref(db, B), "to": ref(db, C)})
        count = len(db.relations)
        with self.assertRaises(AlphaError) as cycle:
            relations.link_versions(self.ctx, {"relation": "derived_from", "from": ref(db, C), "to": ref(db, A)})
        self.assertEqual((cycle.exception.status, cycle.exception.code), (422, "library_relation_cycle"))
        with self.assertRaises(AlphaError) as across:
            relations.link_versions(self.ctx, {"relation": "version_of", "from": ref(db, C), "to": ref(db, A)})
        self.assertEqual(across.exception.code, "library_relation_cycle", "cycles across lineage relation kinds are refused")
        with self.assertRaises(AlphaError) as self_link:
            relations.link_versions(self.ctx, {"relation": "derived_from", "from": ref(db, A), "to": ref(db, A)})
        self.assertEqual(self_link.exception.code, "library_relation_cycle")
        self.assertEqual(len(db.relations), count, "a refused link writes nothing")
        self.assertIsNone(db.assets[C]["lineage"])
        via_action = actions.apply(self.ctx, envelope("version.link", targets=[ref(db, C), ref(db, A)], payload={"relation": "derived_from"}))
        self.assertEqual(via_action["status"], "conflict", "a cycle through the action surface is a conflict, not a crash")
        related = relations.related_http(self.ctx, {"params": {"key": A}, "query": {}, "body": {}})
        self.assertEqual([n["key"] for n in related["lineage"]["ancestors"]["nodes"]], [B, C])
        self.assertFalse(related["lineage"]["ancestors"]["truncated"])

    def test_near_duplicate_not_auto_deleted(self):
        db = self.db
        for key in (E, F, G):
            db.add(key, kind="image", media={"width": 1080, "height": 1350})
        db.add(X, kind="image", status="duplicate", duplicate_of=E)
        db.vector = True
        db.neighbors[E] = [(F, F, 0.01), (G, G, 0.4)]
        before = copy.deepcopy(db.assets)
        out = relations.suggest_near_duplicates(self.ctx, versions.get(self.ctx, E))
        self.assertEqual((out["available"], out["suggested"]), (True, 1))
        similar = [r for r in db.relations if r["relation"] == "similar_to"]
        self.assertEqual(len(similar), 1)
        self.assertEqual((similar[0]["status"], similar[0]["origin"]), ("suggested", "system"))
        self.assertEqual({similar[0]["from_version"], similar[0]["to_version"]}, {E, F})
        self.assertEqual(db.assets, before, "nothing is merged, hidden or deleted")
        self.assertFalse(db.sql(ASSET_WRITE))
        self.assertFalse(db.sql(r"DELETE FROM"), "no delete of any kind")
        similar[0]["status"] = "dismissed"
        relations.suggest_near_duplicates(self.ctx, versions.get(self.ctx, E))
        self.assertEqual([r["status"] for r in db.relations if r["relation"] == "similar_to"], ["dismissed"], "a dismissal is never resurrected")
        similar[0]["status"] = "suggested"
        related = relations.related_http(self.ctx, {"params": {"key": E}, "query": {}, "body": {}})
        self.assertEqual(related["nearDuplicates"]["available"], True)
        self.assertEqual([s["other"]["assetRef"]["versionId"] for s in related["nearDuplicates"]["suggestions"]], [F])
        self.assertEqual(related["nearDuplicates"]["suggestions"][0]["status"], "suggested")
        self.assertEqual(related["exactDuplicates"]["count"], 1, "the hash duplicate stays a reference to the canonical file")
        with self.assertRaises(AlphaError) as manual_similar:
            relations.link_versions(self.ctx, {"relation": "similar_to", "from": ref(db, E), "to": ref(db, G)})
        self.assertEqual(manual_similar.exception.status, 422)
        db.vector = False  # an environment without pgvector (the column check is cached per request, so use a new one)
        plain = context(db)
        self.assertEqual(relations.suggest_near_duplicates(plain, versions.get(plain, G)), {"available": False, "suggested": 0})
        self.assertEqual(relations.related_http(plain, {"params": {"key": G}, "query": {}, "body": {}})["nearDuplicates"]["available"], False)

    def test_changed_source_impacts_draft(self):
        db = self.db
        db.add(O, kind="document", title="Programme notes", source_id="src-old")
        db.add(N, kind="document", title="Programme notes v2")
        db.packs[PACK] = {"revision": 3, "status": "draft", "evidence_refs": [{"assetRef": ref(db, O), "locator": {"kind": "text", "start": 0, "end": 20}}],
                          "style_refs": [], "rights_warnings": [], "created_by": OTHER_ACTOR, "draft_id": "draft-7"}
        db.state["sources"].append({"id": "src-old", "kind": "document", "active": True, "sourcePolicy": "rewrite_approval", "egressConsent": ["local"],
                                    "useApprovals": [], "facts": [{"id": "f1", "text": "Concert on 12 October", "approved": True}],
                                    "origin": {"kind": "library", "assetId": O, "sha256": db.assets[O]["sha"]}, "createdAt": 1789600000.0})
        db.state["variants"].append({"id": "variant-1", "platform": "instagram", "language": "en", "sourceIds": ["src-old"], "revision": 1})
        db.relations.append({"id": k(0x77), "ws": WS, "from_key": O, "from_version": O, "from_segment": None, "to_kind": "post", "to_key": "post-9",
                             "to_version": None, "relation": "used_in", "status": "active", "origin": "system", "evidence": {}, "created_by": None,
                             "created": db.now})
        state_before = copy.deepcopy(db.state)
        pack_before = copy.deepcopy(db.packs[PACK]["evidence_refs"])
        pre_link = ref(db, N)  # minted before N joins O's stack: assetId is N itself

        linked = relations.link_versions(self.ctx, {"relation": "version_of", "from": ref(db, N), "to": ref(db, O)})
        self.assertEqual((db.assets[N]["lineage"], db.assets[N]["version_no"]), (O, 2))
        kinds = {(r["relation"], r["from_version"], r["to_version"]) for r in db.relations if r["to_kind"] == "asset"}
        self.assertEqual(kinds, {("version_of", N, O), ("supersedes", N, O)})
        stale = {(r["to_kind"], r["to_key"]) for r in db.relations if r["relation"] == "used_in" and r["status"] == "stale" and r["from_version"] == O}
        self.assertEqual(stale, {("source_pack", PACK), ("idea", "src-old"), ("draft", "variant-1"), ("post", "post-9")})
        self.assertEqual(linked["flagged"]["count"], 4)
        self.assertEqual(linked["flagged"]["suggestions"], 2, "one outdated-source warning per recipient for the whole link")
        self.assertEqual({a["kind"] for s in db.suggestions for a in s["affected"]}, {"source_pack", "idea", "draft", "post"})
        self.assertEqual({s["category"] for s in db.suggestions}, {"outdated_source"})
        self.assertEqual(next(s for s in db.suggestions if any(a["kind"] == "source_pack" for a in s["affected"]))["recipient"], OTHER_ACTOR)
        self.assertEqual(len(next(s for s in db.suggestions if s["recipient"] == ACTOR)["affected"]), 3)
        self.assertEqual(db.packs[PACK]["evidence_refs"], pack_before, "the old citation is never rewritten")
        self.assertEqual(db.state, state_before, "Ideas sources and drafts are not mutated")
        # Linking again is idempotent: no duplicate flags or suggestions.
        flagged_again = relations.flag_dependents(self.ctx, [versions.get(self.ctx, O)], versions.get(self.ctx, N))
        self.assertEqual(len(db.suggestions), 2)
        self.assertEqual(flagged_again["count"], 4)

        listing = comparison.versions_http(self.ctx, {"params": {"key": O}, "query": {}, "body": {}})
        self.assertEqual(listing["current"]["versionId"], N)
        self.assertEqual([v["versionNo"] for v in listing["versions"]], [1, 2])
        self.assertEqual({(a["kind"], a["key"]) for a in listing["affected"]}, stale)
        self.assertTrue(all(a["citesVersion"]["versionId"] == O for a in listing["affected"]))
        self.assertEqual(listing["versions"][0]["approval"]["status"], "approved_for_drafts")
        self.assertEqual(listing["versions"][1]["approval"]["status"], "not_reviewed", "the new version is never presented as approved")

        new_ref, old_ref = ref(db, N), ref(db, O)
        self.assertEqual(pre_link["assetId"], N)
        self.assertEqual(versions.resolve(self.ctx, pre_link)["versionId"], N, "a pre-link reference still names the same version")
        compared = comparison.compare_versions(self.ctx, [old_ref, pre_link])
        self.assertEqual(compared["right"]["assetRef"], new_ref, "responses always carry the canonical lineage reference")
        with self.assertRaises(AlphaError) as stale_revision:
            relations.accept_replacement(self.ctx, versions.get(self.ctx, O), versions.get(self.ctx, N), {"kind": "source_pack", "key": PACK}, 2)
        self.assertEqual(stale_revision.exception.status, 409)
        viewer = context(db, role="viewer")
        self.assertEqual(actions.apply(viewer, envelope("version.accept_replacement", targets=[old_ref, new_ref], revision=3,
                                                        payload={"dependentKind": "source_pack", "dependentKey": PACK}))["status"], "denied")
        applied = actions.apply(self.ctx, envelope("version.accept_replacement", targets=[old_ref, pre_link], revision=3,
                                                   payload={"dependentKind": "source_pack", "dependentKey": PACK}))
        self.assertEqual((applied["status"], applied["revision"]), ("applied", 4), applied)
        self.assertEqual(db.packs[PACK]["evidence_refs"], [{"assetRef": new_ref}], "only the explicitly accepted item changes")
        self.assertTrue(any(w["code"] == "replacement_needs_review" for w in db.packs[PACK]["rights_warnings"]))
        self.assertTrue(applied["warnings"], "the new version's approval is not implied")
        history = next(r for r in db.relations if r["from_version"] == O and r["to_kind"] == "source_pack")
        self.assertEqual(history["status"], "dismissed")
        self.assertEqual(history["evidence"]["previousRefs"], pack_before, "the old citation stays retrievable")
        current = next(r for r in db.relations if r["from_version"] == N and r["to_kind"] == "source_pack")
        self.assertEqual((current["relation"], current["status"]), ("used_in", "active"))
        self.assertEqual(versions.resolve(self.ctx, old_ref)["versionId"], O, "the old version itself stays resolvable")
        # A draft is acknowledged, never rewritten.
        draft = actions.apply(self.ctx, envelope("version.accept_replacement", targets=[old_ref, new_ref], revision=db.policy["org"],
                                                 payload={"dependentKind": "draft", "dependentKey": "variant-1"}))
        self.assertEqual(draft["status"], "applied", draft)
        self.assertEqual(db.state, state_before)
        self.assertTrue(any("not changed" in w for w in draft["warnings"]))
        unrelated = actions.apply(self.ctx, envelope("version.accept_replacement", targets=[ref(db, A), new_ref], revision=db.policy["org"],
                                                     payload={"dependentKind": "draft", "dependentKey": "variant-1"}))
        self.assertEqual(unrelated["status"], "conflict", "only a version the new one supersedes can be replaced")

    def test_version_link_guards(self):
        db = self.db
        db.add(E, kind="document", lineage=None)
        db.add(F, kind="document", lineage=E, version_no=2)
        with self.assertRaises(AlphaError) as has_versions:
            relations.link_versions(self.ctx, {"relation": "version_of", "from": ref(db, E), "to": ref(db, A)})
        self.assertEqual(has_versions.exception.status, 409)
        db.state["phase2"]["assets"].append({"id": X, "mime": "image/jpeg", "hash": sha(X), "createdAt": 1.0})
        with self.assertRaises(AlphaError) as legacy:
            relations.link_versions(context(db), {"relation": "version_of", "from": {"assetId": X, "versionId": X, "sha256": sha(X)}, "to": ref(db, A)})
        self.assertEqual(legacy.exception.status, 422)
        used = relations.link_versions(self.ctx, {"relation": "used_in", "from": ref(db, A), "toKind": "post", "toKey": "post-1"})
        self.assertEqual(used["relation"]["status"], "active")
        relations.link_versions(self.ctx, {"relation": "used_in", "from": ref(db, A), "toKind": "post", "toKey": "post-1"})
        self.assertEqual(sum(1 for r in db.relations if r["relation"] == "used_in"), 1, "used_in is recorded once")
        with self.assertRaises(AlphaError):
            relations.link_versions(self.ctx, {"relation": "used_in", "from": ref(db, A), "toKind": "workspace", "toKey": "x"})
        foreign = actions.apply(self.ctx, envelope("version.link", targets=[ref(db, A), {"assetId": k(0xFEED), "versionId": k(0xFEED), "sha256": ""}],
                                                   payload={"relation": "derived_from"}))
        self.assertEqual(foreign["status"], "denied")


# ======================================================================================================================
class Comparison(unittest.TestCase):
    def setUp(self):
        self.db = OrgDB()
        self.ctx = context(self.db)

    def test_compare_versions_by_format(self):
        db = self.db
        db.add(O, kind="document", title="Programme", source_id="src-old")
        db.add(N, kind="document", title="Programme", lineage=O, version_no=2)
        db.segments[O] = [{"id": "s1", "ordinal": 0, "kind": "page", "text": "Concert on 12 October\nVenue: City Hall", "locator": {"kind": "page", "page": 1}}]
        db.segments[N] = [{"id": "s2", "ordinal": 0, "kind": "page", "text": "Concert on 13 October\nVenue: City Hall\nTickets from HKD 200",
                           "locator": {"kind": "page", "page": 1}}]
        source = {"id": "src-old", "kind": "document", "active": True, "sourcePolicy": "rewrite_approval", "egressConsent": ["local"],
                  "facts": [{"id": "f1", "text": "Concert on 12 October", "approved": True}], "useApprovals": [],
                  "origin": {"kind": "library", "assetId": O, "sha256": db.assets[O]["sha"]}, "createdAt": 1789600000.0}
        source["useApprovals"].append({"actor": ACTOR, "at": 1.0, "factsDigest": source_policy.facts_digest(source)})
        db.state["sources"].append(source)
        db.usage.append((O, O))
        result = comparison.compare_versions(self.ctx, [ref(db, O), ref(db, N)])
        self.assertEqual((result["mode"], result["supported"]), ("text", True))
        self.assertEqual(result["left"]["assetRef"], ref(db, O))
        self.assertEqual(result["right"]["assetRef"], ref(db, N))
        self.assertEqual((result["left"]["versionNo"], result["right"]["versionNo"]), (1, 2))
        self.assertEqual(result["left"]["approval"]["status"], "approved_for_public_use")
        self.assertEqual(result["right"]["approval"]["status"], "not_reviewed")
        self.assertEqual(result["left"]["usage"]["count"], 1)
        self.assertEqual(result["right"]["usage"]["count"], 0)
        self.assertEqual(result["text"]["summary"], {"added": 1, "removed": 0, "changed": 1, "unchanged": 1})
        changed = next(h for h in result["text"]["hunks"] if h["op"] == "replace")
        self.assertEqual(changed["left"][0]["text"], "Concert on 12 October")
        self.assertEqual(changed["right"][0]["locator"], {"kind": "page", "page": 1})
        self.assertEqual(result["relationship"]["sameAsset"], True)

        db.add(E, kind="image", media={"width": 1080, "height": 1350})
        db.add(F, kind="image", media={"width": 1920, "height": 1080})
        image = comparison.compare_http(self.ctx, {"params": {}, "query": {}, "body": {"refs": [ref(db, E), ref(db, F)]}})
        self.assertEqual(image["mode"], "image")
        self.assertEqual((image["image"]["left"]["width"], image["image"]["right"]["orientation"]), (1080, "landscape"))
        self.assertFalse(image["image"]["sameDimensions"])

        db.add(A, kind="audio", media={"durationMs": 60_000})
        db.add(B, kind="video", media={"durationMs": 75_000})
        db.segments[A] = [{"id": "t1", "ordinal": 0, "kind": "transcript", "text": "Welcome to the recital", "locator": {"kind": "time", "startMs": 0, "endMs": 3000}}]
        media = comparison.compare_versions(self.ctx, [ref(db, A), ref(db, B)])
        self.assertEqual((media["mode"], media["media"]["durationDeltaMs"]), ("media", 15_000))
        self.assertEqual(media["media"]["left"]["segments"][0]["locator"], {"kind": "time", "startMs": 0, "endMs": 3000})

        unsupported = comparison.compare_versions(self.ctx, [ref(db, E), ref(db, O)])
        self.assertEqual((unsupported["mode"], unsupported["supported"]), ("unsupported", False))
        self.assertIn("Comparison of these two formats is not supported", unsupported["message"])
        self.assertTrue(unsupported["metadata"], "details are still compared honestly")

        db.chunks[C] = ["Line one\nLine two"]
        db.add(C, kind="document")
        db.add(D, kind="document")
        no_text = comparison.compare_versions(self.ctx, [ref(db, D), ref(db, O)])
        self.assertEqual(no_text["text"]["left"]["source"], "none")
        fallback = comparison.compare_versions(self.ctx, [ref(db, C), ref(db, O)])
        self.assertEqual(fallback["text"]["left"]["source"], "extracted_text")
        self.assertEqual(fallback["text"]["hunks"][0]["left"][0]["locator"]["kind"], "text")

        for body in ({"refs": [ref(db, O)]}, {"refs": [ref(db, O), ref(db, O)]}, {"refs": [ref(db, O), ref(db, N)], "extra": 1}):
            with self.subTest(body=body), self.assertRaises(AlphaError) as bad:
                comparison.compare_http(self.ctx, {"params": {}, "query": {}, "body": body})
            self.assertEqual(bad.exception.status, 400)
        with self.assertRaises(AlphaError) as foreign:
            comparison.compare_versions(self.ctx, [ref(db, O), {"assetId": k(0xFEED), "versionId": k(0xFEED), "sha256": ""}])
        self.assertEqual(foreign.exception.status, 404)

    def test_text_diff_bounds(self):
        left = [{"text": f"line {i}"} for i in range(1000)]
        right = [{"text": f"line {i}" if i % 2 else f"changed {i}"} for i in range(1000)]
        diff = comparison.text_diff(left, right, max_hunks=50)
        self.assertTrue(diff["truncated"])
        self.assertLessEqual(len(diff["hunks"]), 50)
        self.assertEqual(diff["summary"]["changed"], 500, "the summary counts everything even when hunks are truncated")


if __name__ == "__main__":
    unittest.main()
