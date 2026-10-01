"""Catalog v2 on real disposable PostgreSQL; no provider or payment calls.

Run through scripts/postriff_pg_suite.py postgres_pricing_catalog_v2. The shared
RLS fixture intentionally stays legacy: credit suites apply 020--022 themselves.
This group uses independent databases for a full fresh install and populated
legacy upgrade, so its RED cannot be masked by adding 048 to that fixture.
"""
import json
import os
from pathlib import Path
import sys
import unittest

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from postriff_migrate import apply, body, migrations, plan

MIGRATION = ROOT / "migrations/postriff/048_pricing_credit_catalog_v2.sql"
BASE_DSN = os.environ.get("POSTRIFF_TEST_DSN", "host=127.0.0.1 port=55438 dbname=postgres")
POLICY = "credits-v2-2026-09-28"
USER = "00000000-0000-0000-0000-000000000047"
OTHER = "00000000-0000-0000-0000-000000000048"
LEGACY_IDS = ("trial-v1", "studio-v1", "assist-v1", "assist-bounded-v1")
V2 = {
    "free-v1": ("free", 1, 0, "active", "public", 0, 1, 1, 1, 200),
    "starter-v1": ("starter", 1, 2900, "proposed", "hidden", 1000, 1, 3, 1, 1000),
    "creator-v1": ("creator", 1, 5900, "proposed", "public", 3500, 1, 6, 2, 1000),
    "studio-v2": ("studio", 2, 14900, "proposed", "hidden", 8000, 3, 10, 3, 1000),
}
PACKS = {
    "credits-1000-v2": (1500, 1000000),
    "credits-2000-v2": (2900, 2000000),
}
LEGACY_FILTERS = {"pr_plan_terms": "id IN ('trial-v1','studio-v1','assist-v1','assist-bounded-v1')",
                  "pr_credit_packs": "id='existing-pack'"}
NEW_TABLES = ("pr_plan_price_variants", "pr_price_experiment_assignments")


def connect(dsn):
    return psycopg.connect(dsn, autocommit=True, client_encoding="utf8")


def snapshot(db, table, where="true"):
    return db.execute(
        sql.SQL("SELECT to_jsonb(t) - 'catalog_state' - 'new_checkout_enabled' - 'price_variant_id' "
                "FROM public.{} t WHERE " + where + " ORDER BY to_jsonb(t)::text").format(sql.Identifier(table))
    ).fetchall()


def rejects(db, statement, args, error):
    try:
        with db.transaction(force_rollback=True):
            db.execute(statement, args)
    except error:
        return True
    return False


class PricingCatalogV2(unittest.TestCase):
    databases = []
    dsns = {}

    @classmethod
    def setUpClass(cls):
        params = conninfo_to_dict(BASE_DSN)
        if params.get("host") not in ("127.0.0.1", "localhost", "::1") or params.get("port") != "55438":
            raise ValueError("Only the suite's loopback disposable PostgreSQL on port 55438 is allowed")
        cls.addClassCleanup(cls.cleanup)
        setup = (ROOT / "tests/phase2/rls.sql").read_text().split("\\ir ")[0]
        setup = "\n".join(line for line in setup.splitlines()
                          if not line.startswith(("create role ", "\\")))
        paths = migrations()
        old = [p for p in paths if int(p.name[:3]) < 48]
        cls.setup = setup
        cls.old = old
        cls.paths = paths
        cls.legacy_before = {}
        with connect(BASE_DSN) as admin:
            for kind in ("fresh", "upgraded"):
                name = "pricing_catalog_v2_" + kind
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                cls.databases.append(name)
                cls.dsns[kind] = make_conninfo(BASE_DSN, dbname=name)
        # Full old chain, not just the shared harness's subset, proves pre-v2 RED.
        with connect(cls.dsns["upgraded"]) as db:
            db.execute(setup, prepare=False)
            apply(db, old)
            for identity in ("free", "starter", "creator"):
                assert rejects(db, "INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) "
                               "VALUES(%s,%s,999,'pre-v2 probe',0,'proposed','{}')",
                               ("pre-v2-" + identity, identity), psycopg.errors.CheckViolation)
            assert db.execute("SELECT count(*) FROM pr_plan_terms WHERE id = ANY(%s)", (list(V2),)).fetchone()[0] == 0
            assert all(db.execute("SELECT to_regclass(%s)", ("public." + t,)).fetchone()[0] is None for t in NEW_TABLES)
            print(f"BASELINE: {len(old)} hosted migrations; free/starter/creator rejected; v2 rows/tables absent", flush=True)
            db.execute("INSERT INTO auth.users(id) VALUES(%s),(%s)", (USER, OTHER))
            wid = db.execute("SELECT pr_bootstrap(%s,'studio')", (USER,)).fetchone()[0]
            cls.wid = wid
            db.execute("SELECT pr_bootstrap(%s,'assist')", (OTHER,))
            db.execute("UPDATE pr_workspaces SET state=%s::jsonb WHERE id=%s",
                       (json.dumps({"preserve": "繁中 legacy", "approved": True}), wid))
            db.execute("UPDATE pr_plan_terms SET status='active',provider_price_id='price_synthetic_'||id "
                       "WHERE id IN ('studio-v1','assist-v1')")
            db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,provider,provider_customer_id,"
                       "provider_subscription_id,status,current_period_end,cancel_at_period_end) "
                       "VALUES(%s,'studio-v1','stripe','cus_synthetic','sub_synthetic','active','2027-01-01',true)", (wid,))
            db.execute("INSERT INTO pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,"
                       "media_credits_remaining,connected_accounts,members,storage_mb,source) "
                       "VALUES(%s,'studio-v1',17,2,3,1,1000,'subscription')", (wid,))
            db.execute("INSERT INTO pr_credit_packs VALUES('existing-pack','Existing synthetic pack',"
                       "'credits-candidate-2026-09-23-v1','price_synthetic_pack',500,'usd',100000,false,true)")
            db.execute("INSERT INTO pr_credit_orders(workspace_id,actor,pack_id,request_id,policy_id,price_id,"
                       "amount_cents,currency,millicredits,livemode) VALUES(%s,%s,'existing-pack','old-order',"
                       "'credits-candidate-2026-09-23-v1','price_synthetic_pack',500,'usd',100000,false)", (wid, USER))
            db.execute("INSERT INTO pr_usage_ledger(workspace_id,member_id,kind,dimension,cost_state,idempotency_key,meta) "
                       "VALUES(%s,%s,'adjust','text_model','actual','old-grant',"
                       "'{\"credits\":{\"op\":\"grant\",\"milli\":100000,\"expiresAt\":null}}')", (wid, USER))
            for table in ("pr_plan_terms", "pr_workspaces", "pr_trials", "pr_subscriptions", "pr_entitlements",
                          "pr_usage_ledger", "pr_credit_packs", "pr_credit_orders"):
                where = LEGACY_FILTERS.get(table, "true")
                cls.legacy_before[table] = snapshot(db, table, where)
            apply(db, paths)
        with connect(cls.dsns["fresh"]) as db:
            db.execute(setup, prepare=False)
            apply(db, paths)

    @classmethod
    def cleanup(cls):
        with connect(BASE_DSN) as admin:
            for name in cls.databases:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))

    def each(self):
        return self.dsns.items()

    def test_01_plan_identities_and_safe_defaults(self):
        for kind, dsn in self.each():
            with self.subTest(install=kind), connect(dsn) as db:
                for identity in ("trial", "free", "starter", "creator", "studio", "assist"):
                    with self.subTest(identity=identity), db.transaction(force_rollback=True):
                        self.assertFalse(rejects(db, "INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) "
                                                "VALUES(%s,%s,999,'probe',0,'proposed','{}')",
                                                ("probe-" + identity, identity), psycopg.errors.CheckViolation),
                                         "missing v2 plan identity support")
                columns = dict(db.execute("SELECT column_name,column_default FROM information_schema.columns "
                                          "WHERE table_schema='public' AND table_name='pr_plan_terms'").fetchall())
                self.assertIn("catalog_state", columns, "missing v2 catalog schema")
                self.assertIn("new_checkout_enabled", columns)
                self.assertTrue(rejects(db, "UPDATE pr_plan_terms SET plan='unknown' WHERE id='trial-v1'",
                                        None, psycopg.errors.CheckViolation))
                self.assertEqual(columns["new_checkout_enabled"], "false")
                with db.transaction(force_rollback=True):
                    row = db.execute("INSERT INTO pr_plan_terms(id,plan,version,label,price_cents,status,entitlements) "
                                     "VALUES('default-probe','creator',998,'probe',0,'proposed','{}') "
                                     "RETURNING catalog_state,new_checkout_enabled").fetchone()
                    self.assertEqual(row, ("legacy", False))
                self.assertTrue(rejects(db, "UPDATE pr_plan_terms SET catalog_state='invalid' WHERE id='trial-v1'",
                                        None, psycopg.errors.CheckViolation))

    def test_02_exact_v2_terms(self):
        for kind, dsn in self.each():
            with self.subTest(install=kind), connect(dsn) as db:
                rows = dict(db.execute("SELECT id,to_jsonb(t) FROM pr_plan_terms t WHERE id=ANY(%s)", (list(V2),)).fetchall())
                self.assertEqual(set(rows), set(V2), "missing seeded v2 plan terms")
                for key, expected in V2.items():
                    row = rows[key]
                    e = row["entitlements"]
                    self.assertEqual((row["plan"], row["version"], row["price_cents"], row["status"], row["catalog_state"],
                                      e.get("monthlyCredits", 0), e["members"], e["connectedAccounts"], e["brands"], e["storageMb"]), expected)
                    self.assertEqual((row["currency"], row["new_checkout_enabled"], row["provider_price_id"]), ("USD", False, None))
                    self.assertEqual((e["writingBatches"], e["mediaCredits"], e["overage"]), (0, 0, "stop"))
                    self.assertEqual(e.get("creditPolicy"), None if key == "free-v1" else POLICY)

    def test_03_creator_variants_share_entitlement(self):
        for kind, dsn in self.each():
            with self.subTest(install=kind), connect(dsn) as db:
                self.assertIsNotNone(db.execute("SELECT to_regclass('public.pr_plan_price_variants')").fetchone()[0], "missing v2 variant schema")
                rows = db.execute("SELECT v.id,v.plan_terms_id,v.variant_key,v.amount_cents,v.currency,v.status,"
                                  "v.provider_price_id,p.entitlements->>'monthlyCredits' FROM pr_plan_price_variants v "
                                  "JOIN pr_plan_terms p ON p.id=v.plan_terms_id ORDER BY v.amount_cents").fetchall()
                self.assertEqual(rows, [(f"creator-{price}-v1", "creator-v1", str(price), price * 100, "USD", "proposed", None, "3500")
                                        for price in (49, 59, 79)])
                self.assertEqual(db.execute("SELECT count(*) FROM pr_price_experiment_assignments").fetchone()[0], 0)
                self.assertTrue(rejects(db, "INSERT INTO pr_plan_price_variants(id,plan_terms_id,variant_key,amount_cents,currency,status) "
                                        "VALUES('duplicate','creator-v1','59',5900,'USD','proposed')", None, psycopg.errors.UniqueViolation))
                for field, value in (("amount_cents", -1), ("currency", "ZZZ"), ("status", "unknown")):
                    self.assertTrue(rejects(db, sql.SQL("UPDATE pr_plan_price_variants SET {}=%s WHERE id='creator-59-v1'").format(sql.Identifier(field)),
                                            (value,), psycopg.errors.CheckViolation))

    def test_04_legacy_data_and_prices_unchanged(self):
        with connect(self.dsns["upgraded"]) as db:
            for table, before in self.legacy_before.items():
                where = LEGACY_FILTERS.get(table, "true")
                self.assertEqual(snapshot(db, table, where), before, table)
            rows = db.execute("SELECT id,price_cents,to_jsonb(t)->>'catalog_state',to_jsonb(t)->>'new_checkout_enabled' "
                              "FROM pr_plan_terms t WHERE id=ANY(%s) ORDER BY id", (list(LEGACY_IDS),)).fetchall()
            self.assertEqual(rows, [("assist-bounded-v1", 3900, "legacy", "false"), ("assist-v1", 3900, "legacy", "false"),
                                    ("studio-v1", 1900, "legacy", "false"), ("trial-v1", 0, "legacy", "false")])

    def test_05_stable_assignments(self):
        with connect(self.dsns["upgraded"]) as db:
            self.assertIsNotNone(db.execute("SELECT to_regclass('public.pr_price_experiment_assignments')").fetchone()[0], "missing stable assignment schema")
            with db.transaction(force_rollback=True):
                db.execute("SET LOCAL ROLE service_role")
                args = (self.wid, "creator-beta-v1", "creator-49-v1", "synthetic-test")
                statement = "INSERT INTO pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) VALUES(%s,%s,%s,%s)"
                db.execute(statement, args)
                self.assertTrue(rejects(db, statement, (self.wid, args[1], "creator-79-v1", args[3]), psycopg.errors.UniqueViolation))
                self.assertTrue(rejects(db, statement, (self.wid, "missing-variant", "missing", args[3]), psycopg.errors.ForeignKeyViolation))
                for stmt in ("UPDATE pr_price_experiment_assignments SET price_variant_id='creator-79-v1'",
                             "DELETE FROM pr_price_experiment_assignments"):
                    self.assertTrue(rejects(db, stmt, None, psycopg.errors.InsufficientPrivilege))
                db.execute("RESET ROLE")
                self.assertTrue(rejects(db, "UPDATE pr_price_experiment_assignments SET price_variant_id='creator-79-v1'", None, psycopg.errors.CheckViolation))
                # Workspace erasure remains possible without rewriting a price assignment.
                db.execute("DELETE FROM pr_workspaces WHERE id=%s", (self.wid,))
                self.assertEqual(db.execute("SELECT count(*) FROM pr_price_experiment_assignments").fetchone()[0], 0)

    def test_06_subscription_variant_package_binding(self):
        with connect(self.dsns["upgraded"]) as db:
            self.assertEqual(db.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema='public' "
                                        "AND table_name='pr_subscriptions' AND column_name='price_variant_id'").fetchone(), ("YES",), "missing nullable subscription variant")
            self.assertEqual(db.execute("SELECT price_variant_id FROM pr_subscriptions").fetchone(), (None,))
            self.assertTrue(rejects(db, "UPDATE pr_subscriptions SET price_variant_id='creator-49-v1'", None, psycopg.errors.ForeignKeyViolation))
            with db.transaction(force_rollback=True):
                db.execute("SET LOCAL ROLE service_role")
                for price in (49, 59, 79):
                    db.execute("UPDATE pr_subscriptions SET plan_terms_id='creator-v1',price_variant_id=%s", (f"creator-{price}-v1",))
                self.assertTrue(rejects(db, "UPDATE pr_subscriptions SET price_variant_id='missing'", None, psycopg.errors.ForeignKeyViolation))
                self.assertTrue(rejects(db, "UPDATE pr_subscriptions SET plan_terms_id='studio-v2'", None, psycopg.errors.ForeignKeyViolation))

    def test_07_inactive_packs_use_existing_schema(self):
        for kind, dsn in self.each():
            with self.subTest(install=kind), connect(dsn) as db:
                rows = db.execute("SELECT id,amount_cents,millicredits,policy_id,currency,price_id,active,livemode "
                                  "FROM pr_credit_packs WHERE id=ANY(%s) ORDER BY id", (list(PACKS),)).fetchall()
                self.assertEqual(rows, [(key, cents, milli, POLICY, "usd", None, False, False) for key, (cents, milli) in PACKS.items()], "missing inactive providerless packs")
                self.assertTrue(rejects(db, "UPDATE pr_credit_packs SET active=true WHERE id='credits-1000-v2'", None, psycopg.errors.CheckViolation))

    def test_08_restricted_roles_and_rls(self):
        for kind, dsn in self.each():
            with self.subTest(install=kind), connect(dsn) as db:
                for table in NEW_TABLES:
                    self.assertEqual(db.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=to_regclass(%s)",
                                                ("public." + table,)).fetchone(), (True, True), "missing v2 forced RLS")
                    for role in ("anon", "authenticated"):
                        with db.transaction(force_rollback=True):
                            db.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
                            for verb in ("SELECT * FROM", "INSERT INTO", "UPDATE", "DELETE FROM"):
                                suffix = {"SELECT * FROM": "", "INSERT INTO": " DEFAULT VALUES", "UPDATE": " SET price_variant_id=price_variant_id" if table.endswith("assignments") else " SET amount_cents=amount_cents", "DELETE FROM": ""}[verb]
                                self.assertTrue(rejects(db, sql.SQL(verb + " public.{}" + suffix).format(sql.Identifier(table)), None, psycopg.errors.InsufficientPrivilege), (role, table, verb))
                    with db.transaction(force_rollback=True):
                        db.execute("SET LOCAL ROLE service_role")
                        db.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(table)))
                # Exercise forced RLS independently of revoked grants, with a role lacking BYPASSRLS.
                with db.transaction(force_rollback=True):
                    wid = db.execute("SELECT id FROM pr_workspaces LIMIT 1").fetchone()
                    if wid is None:
                        db.execute("INSERT INTO auth.users(id) VALUES(%s)", (USER,))
                        wid = db.execute("SELECT pr_bootstrap(%s,'studio')", (USER,)).fetchone()
                    db.execute("INSERT INTO pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) "
                               "VALUES(%s,'creator-beta-v1','creator-49-v1','synthetic-test')", (wid[0],))
                    db.execute("CREATE ROLE pricing_catalog_reader NOLOGIN NOBYPASSRLS")
                    for table in NEW_TABLES:
                        db.execute(sql.SQL("GRANT SELECT,INSERT ON public.{} TO pricing_catalog_reader").format(sql.Identifier(table)))
                    db.execute("SET LOCAL ROLE pricing_catalog_reader")
                    self.assertEqual(db.execute("SELECT count(*) FROM pr_plan_price_variants").fetchone()[0], 0)
                    self.assertEqual(db.execute("SELECT count(*) FROM pr_price_experiment_assignments").fetchone()[0], 0)
                    self.assertTrue(rejects(db, "INSERT INTO pr_plan_price_variants(id,plan_terms_id,variant_key,amount_cents,currency,status) "
                                            "VALUES('rls-forged','creator-v1','rls',1,'USD','proposed')", None, psycopg.errors.InsufficientPrivilege))
                    self.assertTrue(rejects(db, "INSERT INTO pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) "
                                            "VALUES(%s,'forged','creator-49-v1','forged')", (USER,), psycopg.errors.InsufficientPrivilege))
        # Existing subscription tenant-read policy remains intact for the new column.
        with connect(self.dsns["upgraded"]) as db, db.transaction(force_rollback=True):
            db.execute("SET LOCAL ROLE authenticated")
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (OTHER,))
            self.assertEqual(db.execute("SELECT count(*) FROM pr_subscriptions").fetchone()[0], 0)
            db.execute("SELECT set_config('request.jwt.claim.sub',%s,true)", (USER,))
            self.assertEqual(db.execute("SELECT to_jsonb(s)->'price_variant_id' FROM pr_subscriptions s").fetchall(), [(None,)])

    def test_09_free_has_no_wallet_or_grants(self):
        sys.path.insert(0, str(ROOT / "src"))
        from postriff_phase2.credit_wallet import CreditBook
        with connect(self.dsns["upgraded"]) as db, db.transaction(force_rollback=True):
            self.assertEqual(db.execute("SELECT count(*) FROM pr_plan_terms WHERE id='free-v1'").fetchone()[0], 1, "missing Free")
            wid = db.execute("SELECT workspace_id FROM pr_memberships WHERE user_id=%s", (OTHER,)).fetchone()[0]
            db.execute("INSERT INTO pr_entitlements(workspace_id,plan_terms_id,writing_batches_remaining,media_credits_remaining,connected_accounts,members,storage_mb,source) "
                       "VALUES(%s,'free-v1',0,0,1,1,200,'manual')", (wid,))
            book = CreditBook()
            self.assertIsNone(book.policy(db.cursor(), wid))
            self.assertEqual(book.view(db.cursor(), wid)["availableMilliCredits"], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM pr_usage_ledger WHERE workspace_id=%s", (wid,)).fetchone()[0], 0)

    def test_10_migration_replay_preserves_catalog_and_legacy(self):
        self.assertTrue(MIGRATION.is_file(), "missing v2 schema migration")
        for kind, dsn in self.each():
            with self.subTest(install=kind), connect(dsn) as db:
                self.assertTrue(all(row["status"] == "APPLIED" for row in plan(db)))
                # Persist real downstream references, not empty assignment collections.
                user = "00000000-0000-0000-0000-000000000049"
                db.execute("INSERT INTO auth.users(id) VALUES(%s)", (user,))
                wid = db.execute("SELECT pr_bootstrap(%s,'studio')", (user,)).fetchone()[0]
                with db.transaction():
                    db.execute("SET LOCAL ROLE service_role")
                    db.execute("INSERT INTO pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) "
                               "VALUES(%s,'creator-beta-v1','creator-59-v1','synthetic-replay')", (wid,))
                    db.execute("INSERT INTO pr_subscriptions(workspace_id,plan_terms_id,price_variant_id,status,provider_subscription_id) "
                               "VALUES(%s,'creator-v1','creator-59-v1','active','sub_synthetic_replay')", (wid,))
                self.assertEqual(db.execute("SELECT a.price_variant_id,s.price_variant_id,s.plan_terms_id "
                                            "FROM pr_price_experiment_assignments a JOIN pr_subscriptions s USING(workspace_id) "
                                            "WHERE a.workspace_id=%s", (wid,)).fetchall(),
                                 [("creator-59-v1", "creator-59-v1", "creator-v1")])
                tables = ("pr_plan_terms", "pr_plan_price_variants", "pr_price_experiment_assignments", "pr_subscriptions", "pr_credit_packs")
                before = {t: db.execute(sql.SQL("SELECT to_jsonb(t) FROM public.{} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(t))).fetchall() for t in tables}
                self.assertTrue(all(row["status"] == "APPLIED" for row in apply(db)))
                # Direct SQL replay (not just a ledger no-op) must not duplicate or rewrite rows.
                db.execute(body(MIGRATION), prepare=False)
                after = {t: db.execute(sql.SQL("SELECT to_jsonb(t) FROM public.{} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(t))).fetchall() for t in tables}
                self.assertEqual(before, after)

    def test_11_formerly_legal_pack_rows_survive_upgrade(self):
        name = "pricing_catalog_v2_old_packs"
        with connect(BASE_DSN) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            self.databases.append(name)
        dsn = make_conninfo(BASE_DSN, dbname=name)
        with connect(dsn) as db:
            db.execute(self.setup, prepare=False)
            apply(db, self.old)
            # 021 permitted any non-NULL text: active/inactive, empty, spaces,
            # tabs/newlines, valid IDs, and IDs with surrounding whitespace.
            prices = ("", " ", "   ", "\t\n\r", "price_synthetic", " price_synthetic ")
            for active in (False, True):
                for index, price in enumerate(prices):
                    db.execute("INSERT INTO pr_credit_packs VALUES(%s,'Historical pack','old-policy',%s,1,'usd',1000,true,%s)",
                               (f"historical-{active}-{index}", price, active))
            before = snapshot(db, "pr_credit_packs")
            try:
                apply(db)
            except psycopg.errors.CheckViolation as error:
                self.fail(f"048 aborts on formerly legal legacy pack rows: {error.diag.constraint_name}")
            self.assertEqual(snapshot(db, "pr_credit_packs", "id LIKE 'historical-%'"), before)
            check = "SELECT convalidated FROM pg_constraint WHERE conrelid='pr_credit_packs'::regclass AND conname='pr_credit_packs_active_price_check'"
            self.assertEqual(db.execute(check).fetchone(), (False,))
            self.assertTrue(rejects(db, "ALTER TABLE pr_credit_packs VALIDATE CONSTRAINT pr_credit_packs_active_price_check",
                                    None, psycopg.errors.CheckViolation))
            for price in (*prices[:4], None):
                self.assertTrue(rejects(db, "INSERT INTO pr_credit_packs VALUES('new-invalid','New pack','new-policy',%s,1,'usd',1000,false,true)",
                                        (price,), psycopg.errors.CheckViolation))
                self.assertTrue(rejects(db, "UPDATE pr_credit_packs SET active=true,price_id=%s WHERE id='credits-1000-v2'",
                                        (price,), psycopg.errors.CheckViolation))
            db.execute(body(MIGRATION), prepare=False)
            self.assertEqual(snapshot(db, "pr_credit_packs", "id LIKE 'historical-%'"), before)
        # On a known-clean fresh fixture an explicit validation succeeds; the
        # migration itself leaves this operation to a separate reviewed step.
        with connect(self.dsns["fresh"]) as db, db.transaction(force_rollback=True):
            db.execute("ALTER TABLE pr_credit_packs VALIDATE CONSTRAINT pr_credit_packs_active_price_check")
            self.assertEqual(db.execute(check).fetchone(), (True,))

    def test_12_assignment_matches_variant_experiment(self):
        with connect(self.dsns["upgraded"]) as db, db.transaction(force_rollback=True):
            db.execute("SET LOCAL ROLE service_role")
            statement = "INSERT INTO pr_price_experiment_assignments(workspace_id,experiment_key,price_variant_id,assignment_source) VALUES(%s,%s,%s,'synthetic-test')"
            for variant in ("creator-49-v1", "creator-59-v1", "creator-79-v1"):
                with self.subTest(variant=variant):
                    self.assertTrue(rejects(db, statement, (self.wid, "wrong-experiment", variant), psycopg.errors.ForeignKeyViolation))
            db.execute("INSERT INTO pr_plan_price_variants(id,plan_terms_id,variant_key,amount_cents,currency,status) "
                       "VALUES('no-experiment','creator-v1','non-experiment',5900,'USD','proposed')")
            self.assertTrue(rejects(db, statement, (self.wid, "wrong-experiment", "no-experiment"), psycopg.errors.ForeignKeyViolation))
            db.execute(statement, (self.wid, "creator-beta-v1", "creator-49-v1"))
            self.assertTrue(rejects(db, "UPDATE pr_plan_price_variants SET experiment_key='changed-experiment' WHERE id='creator-49-v1'",
                                    None, psycopg.errors.ForeignKeyViolation))


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PricingCatalogV2))
    print(json.dumps({"execution": "disposable-local-postgres; no external calls", "tests": result.testsRun,
                      "failures": len(result.failures), "errors": len(result.errors),
                      "installs": ["fresh", "upgraded-legacy"], "hostedMigrations": len(migrations())}), flush=True)
    sys.exit(0 if result.wasSuccessful() else 1)
