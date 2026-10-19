"""Synthetic boundary tests and explicit disposable PostgreSQL acceptance."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import unittest
from uuid import uuid4
from postriff_phase2.x_direct_cost import (PRICES, XCostAdmissionError, XCostController,
    XCostPolicy, XCostRequest, admit_x_request, bind_x_cost_context)


def policy(**overrides):
    now = datetime.now(timezone.utc)
    env = {
        "RAFII_X_COST_WINDOW_ID": "test-window-" + uuid4().hex,
        "RAFII_X_COST_APPROVAL_REF": "synthetic:test-only-approval",
        "RAFII_X_COST_APPROVAL_EXPIRES_AT": (now + timedelta(hours=1)).isoformat(),
        "RAFII_X_COST_PRICE_EVIDENCE_REF": "synthetic:test-only-prices",
        "RAFII_X_COST_PRICE_EVIDENCE_EXPIRES_AT": (now + timedelta(hours=1)).isoformat(),
        "RAFII_X_COST_APP_BUDGET_MICROS": "100000",
        "RAFII_X_COST_WORKSPACE_BUDGET_MICROS": "100000",
        "RAFII_X_COST_APP_REQUEST_LIMIT": "100",
        "RAFII_X_COST_WORKSPACE_REQUEST_LIMIT": "100",
        "RAFII_X_COST_ALLOWED_PRICE_KEYS": ",".join(PRICES)}
    return replace(XCostPolicy.from_environment(env), **overrides)


def request(workspace="workspace-a"):
    return XCostRequest(str(uuid4()), workspace, "connection-a", "identity",
                        "GET", "/2/users/me", "identity_read", 1, 10000)


class XCostBoundaryTests(unittest.TestCase):
    def context(self, callback):
        return bind_x_cost_context(workspace_id="workspace-a", connection_id="connection-a",
                                   operation="synthetic", reserve=callback)

    def test_missing_policy_is_inert(self):
        c = XCostController(None, XCostPolicy.from_environment({}), "app-test")
        self.assertFalse(c.ready)
        self.assertFalse(c.eligible(10000, "workspace-a"))
        self.assertFalse(c.status["provider_billing_cap_verified"])

    def test_context_restored_even_after_exception(self):
        with self.assertRaises(XCostAdmissionError):
            admit_x_request(method="GET", path="/2/users/me")
        with self.assertRaises(RuntimeError):
            with self.context(lambda _: "fake-reservation"):
                raise RuntimeError("synthetic")
        with self.assertRaises(XCostAdmissionError):
            admit_x_request(method="GET", path="/2/users/me")

    def test_boolean_reservation_not_accepted(self):
        with self.context(lambda _: True), self.assertRaises(XCostAdmissionError):
            admit_x_request(method="GET", path="/2/users/me")

    def test_each_retry_consumes_new_reservation(self):
        seen = []
        def reserve(value):
            seen.append(value)
            return value.request_id
        with self.context(reserve):
            first = admit_x_request(method="GET", path="/2/users/me")
            second = admit_x_request(method="GET", path="/2/users/me")
        self.assertNotEqual(first, second)
        self.assertEqual([v.estimated_micros for v in seen], [10000,10000])

    def test_url_and_ambiguous_text_reserve_high_price(self):
        seen = []
        def reserve(value):
            seen.append(value)
            return value.request_id
        bodies = [{"text":"Hello music"},{"text":"Visit example.com"},{"text":"example。com"},
                  {"text":"Hello","quote_tweet_id":"123"},{"text":"Sentence with a period."}]
        with self.context(reserve):
            for body in bodies:
                admit_x_request(method="POST",path="/2/tweets",body=body)
        self.assertEqual([v.estimated_micros for v in seen],[15000,200000,200000,200000,200000])

    def test_undercount_expansions_and_unpriced_media_denied_before_reserve(self):
        seen=[]
        def reserve(value):
            seen.append(value)
            return value.request_id
        attempts=[
            dict(method="GET",path="/2/users/123/tweets",query={"max_results":100},max_resources=1),
            dict(method="GET",path="/2/tweets",query={"ids":"1,2,3"},max_resources=1),
            dict(method="GET",path="/2/users/123/tweets",max_resources=100),
            dict(method="GET",path="/2/tweets/123",query={"expansions":"author_id"}),
            dict(method="GET",path="/2/users/me",max_resources=True),
            dict(method="POST",path="/2/media/upload",body={"synthetic":True}),
            dict(method="GET",path="/2/users/123/tweets?max_results=100",query={"max_results":1})]
        with self.context(reserve):
            for values in attempts:
                with self.subTest(values=values),self.assertRaises(XCostAdmissionError):
                    admit_x_request(**values)
        self.assertEqual(seen,[])

    def test_resource_upper_bound_is_reserved(self):
        seen=[]
        def reserve(value):
            seen.append(value)
            return value.request_id
        with self.context(reserve):
            admit_x_request(method="GET",path="/2/tweets",query={"ids":"1,2,3"})
            admit_x_request(method="GET",path="/2/users/123/tweets",query={"max_results":"100"})
        self.assertEqual([(v.estimated_units,v.estimated_micros) for v in seen],[(3,15000),(100,500000)])

    def test_async_tenant_contexts_are_isolated(self):
        observed=[]
        def reserve(v):
            observed.append((v.workspace_id,v.connection_id,v.operation))
            return v.request_id
        async def worker(n):
            with bind_x_cost_context(workspace_id=f"workspace-{n}",connection_id=f"connection-{n}",
                                    operation=f"operation-{n}",reserve=reserve):
                await asyncio.sleep(0)
                admit_x_request(method="GET",path="/2/users/me")
        async def run():
            await asyncio.gather(*(worker(n) for n in range(12)))
        asyncio.run(run())
        self.assertEqual(set(observed),{(f"workspace-{n}",f"connection-{n}",f"operation-{n}") for n in range(12)})

    def test_database_failure_denies_before_provider(self):
        def broken():
            raise RuntimeError("synthetic")
        c=XCostController(broken,policy(),"app-test")
        self.assertTrue(c.ready)
        self.assertFalse(c.eligible(10000,"workspace-a"))
        with self.assertRaises(XCostAdmissionError) as caught:
            c.reserve(request())
        self.assertEqual(caught.exception.code,"x_cost_admission_denied")


@unittest.skipUnless(os.environ.get("RAFII_X_TEST_COST_DSN"),"disposable PostgreSQL DSN not supplied")
class XCostPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        cls.psycopg=psycopg
        cls.dsn=os.environ["RAFII_X_TEST_COST_DSN"]
        options=conninfo_to_dict(cls.dsn)
        if not re.fullmatch(r"/tmp/rafii-x-g14-pg-[A-Za-z0-9_-]+/socket",options.get("host","")) or options.get("hostaddr"):
            raise RuntimeError("Disposable UNIX-socket-only X cluster required")
        migration=Path(__file__).resolve().parents[1]/"migrations/postriff/131_x_direct_cost.sql"
        with psycopg.connect(cls.dsn,autocommit=True) as db:
            db.execute(migration.read_text())
            if db.execute("SELECT to_regclass('postriff.x_cost_grants')").fetchone()[0] is None:
                db.execute(migration.with_name("133_x_cost_approval_grants.sql").read_text())

    def setUp(self):
        self.app="synthetic-app-"+uuid4().hex
        self.p=policy()
        self.factory=lambda:self.psycopg.connect(self.dsn)
        self.c=XCostController(self.factory,self.p,self.app)

    def counts(self):
        with self.factory() as db:
            return db.execute("SELECT estimated_micros,request_count FROM postriff.x_cost_windows WHERE app_key=%s AND window_id=%s",(self.app,self.p.window_id)).fetchone()

    def test_reservation_visible_before_io_and_never_refunded(self):
        self.p=replace(self.p,app_budget_micros=10000)
        self.c=XCostController(self.factory,self.p,self.app)
        self.c.activate("synthetic:test-fixture")
        with self.c.context("workspace-a","connection-a","identity"):
            with self.assertRaises(TimeoutError):
                admit_x_request(method="GET",path="/2/users/me")
                self.assertEqual(self.counts(),(10000,1))
                raise TimeoutError("synthetic ambiguous provider response")
            with self.assertRaises(XCostAdmissionError):
                admit_x_request(method="GET",path="/2/users/me")
        self.assertEqual(self.counts(),(10000,1))

    def test_concurrent_tenants_share_app_budget(self):
        self.p=replace(self.p,app_budget_micros=70000)
        self.c=XCostController(self.factory,self.p,self.app)
        self.c.activate("synthetic:test-fixture")
        def attempt(n):
            try:
                with self.c.context(f"workspace-{n}",f"connection-{n}","identity"):
                    admit_x_request(method="GET",path="/2/users/me")
                return True
            except XCostAdmissionError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted=list(pool.map(attempt,range(20)))
        self.assertEqual(sum(admitted),7)
        self.assertEqual(self.counts(),(70000,7))
        with self.factory() as db:
            row=db.execute("SELECT count(*),sum(estimated_micros) FROM postriff.x_cost_reservations WHERE app_key=%s",(self.app,)).fetchone()
        self.assertEqual(row,(7,70000))

    def test_workspace_limit_separate_from_other_tenants(self):
        self.p=replace(self.p,workspace_request_limit=1)
        self.c=XCostController(self.factory,self.p,self.app)
        self.c.activate("synthetic:test-fixture")
        self.c.reserve(request("workspace-a"))
        with self.assertRaises(XCostAdmissionError):
            self.c.reserve(request("workspace-a"))
        self.c.reserve(request("workspace-b"))
        self.assertFalse(self.c.eligible(10000,"workspace-a"))
        self.assertTrue(self.c.eligible(10000,"workspace-c"))
        self.assertEqual(self.counts(),(20000,2))

    def test_identity_only_policy_cannot_admit_post(self):
        from postriff_phase2.x_direct_contract import normalize_operation
        self.p=replace(self.p,allowed_price_keys=frozenset({"identity_read"}))
        self.c=XCostController(self.factory,self.p,self.app)
        self.c.activate("synthetic:test-fixture")
        plan=normalize_operation("posts.create",workspace_id="workspace-a",account_id="connection-a",
                                 actor_user_id="123",body={"text":"Synthetic"})
        self.assertFalse(self.c.eligible_request(plan,"workspace-a"))
        with self.c.context("workspace-a","connection-a","publish"),self.assertRaises(XCostAdmissionError):
            admit_x_request(method="POST",path="/2/tweets",body={"text":"Synthetic"})
        self.assertIsNone(self.counts())

    def test_changed_policy_cannot_reset_consumed_window(self):
        self.c.activate("synthetic:test-fixture")
        self.c.reserve(request())
        changed=XCostController(self.factory,replace(self.p,app_budget_micros=200000),self.app)
        self.assertFalse(changed.eligible(10000,"workspace-a"))
        with self.assertRaises(XCostAdmissionError):
            changed.reserve(request())
        self.assertEqual(self.counts(),(10000,1))

    def test_database_clock_overrules_stale_application_clock(self):
        now=datetime.now(timezone.utc)
        c=XCostController(self.factory,replace(self.p,approval_expires_at=now-timedelta(seconds=1)),
                          self.app,clock=lambda:now-timedelta(minutes=1))
        self.assertTrue(c.ready)
        with self.assertRaises(XCostAdmissionError):
            c.activate("synthetic:expired-approval")
        self.assertFalse(c.eligible(10000,"workspace-a"))
        with self.assertRaises(XCostAdmissionError):
            c.reserve(request())
        self.assertIsNone(self.counts())

    def test_duplicate_reservation_cannot_authorize_second_attempt(self):
        self.c.activate("synthetic:test-fixture")
        value=request()
        self.c.reserve(value)
        with self.assertRaises(XCostAdmissionError):
            self.c.reserve(value)
        self.assertEqual(self.counts(),(10000,1))

    def test_forged_lower_amount_rejected(self):
        self.c.activate("synthetic:test-fixture")
        with self.assertRaises(XCostAdmissionError):
            self.c.reserve(replace(request(),estimated_micros=1))
        self.assertIsNone(self.counts())

    def test_autocommit_connection_has_atomic_reservation(self):
        c=XCostController(lambda:self.psycopg.connect(self.dsn,autocommit=True),self.p,self.app)
        c.activate("synthetic:autocommit-fixture")
        c.reserve(request())
        self.assertEqual(self.counts(),(10000,1))

    def test_authenticated_cannot_read_cost_records(self):
        self.c.activate("synthetic:test-fixture")
        self.c.reserve(request())
        with self.factory() as db:
            db.execute("SET ROLE authenticated")
            with self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                db.execute("SELECT * FROM postriff.x_cost_reservations").fetchall()

    def grant_counts(self,approval=None):
        with self.factory() as db:
            return db.execute("""SELECT estimated_micros,request_count FROM postriff.x_cost_grants
                WHERE app_key=%s AND approval_ref=%s""",(self.app,approval or self.p.approval_ref)).fetchone()

    def test_same_approval_many_windows_admits_only_three_identity_reads(self):
        self.p=replace(self.p,app_request_limit=3,workspace_request_limit=3,allowed_price_keys=frozenset({'identity_read'}))
        self.c=XCostController(self.factory,self.p,self.app)
        self.c.activate('synthetic:identity-max-three')
        controllers=[XCostController(self.factory,replace(self.p,window_id='synthetic-window-'+str(n)),self.app) for n in range(4)]
        def attempt(n):
            try:
                controllers[n%4].reserve(request('workspace-'+str(n)))
                return True
            except XCostAdmissionError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted=list(pool.map(attempt,range(32)))
        self.assertEqual(sum(admitted),3)
        self.assertEqual(self.grant_counts(),(30000,3))
        restarted=XCostController(self.factory,replace(self.p,window_id='synthetic-window-restart'),self.app)
        self.assertFalse(restarted.eligible(10000,'workspace-new'))
        with self.assertRaises(XCostAdmissionError):
            restarted.reserve(request('workspace-new'))

    def test_other_approval_requires_explicit_cas_and_old_usage_survives(self):
        self.p=replace(self.p,app_request_limit=3)
        self.c=XCostController(self.factory,self.p,self.app)
        self.assertEqual(self.c.activate('synthetic:activate-A'),1)
        self.c.reserve(request())
        b=XCostController(self.factory,replace(self.p,approval_ref='synthetic:approval-B',window_id='synthetic:B-window'),self.app)
        self.assertFalse(b.eligible(10000,'workspace-a'))
        with self.assertRaises(XCostAdmissionError):
            b.reserve(request())
        self.assertEqual(b.activate('synthetic:switch-B',1,self.p.approval_ref),2)
        self.assertFalse(self.c.eligible(10000,'workspace-a'))
        b.reserve(request())
        self.assertEqual(self.c.activate('synthetic:switch-back-A',2,b.policy.approval_ref),3)
        self.assertEqual(self.grant_counts(),(10000,1))
        self.c.reserve(request());self.c.reserve(request())
        self.assertFalse(self.c.eligible(10000,'workspace-a'))
        def activate(controller):
            try:
                return controller.activate('synthetic:competing-switch',3,self.p.approval_ref)
            except XCostAdmissionError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(activate,[self.c,b]))
        self.assertEqual(sum(v==4 for v in results),1)

    def test_price_evidence_renewal_and_window_rotation_never_reset_usage(self):
        self.p=replace(self.p,app_request_limit=3,allowed_price_keys=frozenset({'identity_read'}))
        self.c=XCostController(self.factory,self.p,self.app)
        self.c.activate('synthetic:initial-price')
        self.c.reserve(request());self.c.reserve(request())
        renewed=XCostController(self.factory,replace(self.p,price_evidence_ref='synthetic:renewed-price',
            price_evidence_expires_at=self.p.price_evidence_expires_at+timedelta(hours=1)),self.app)
        self.assertEqual(renewed.policy.limits_hash,self.p.limits_hash)
        self.assertNotEqual(renewed.policy.evidence_hash,self.p.evidence_hash)
        renewed.activate('synthetic:price-evidence-renewal',1,self.p.approval_ref)
        self.assertEqual(self.grant_counts(),(20000,2))
        self.assertFalse(self.c.eligible(10000,'workspace-a'))
        self.assertTrue(renewed.eligible(10000,'workspace-a'))
        for amount in (True,1,9999,10001):
            with self.assertRaises(XCostAdmissionError):
                renewed.reserve(replace(request(),estimated_micros=amount))
        renewed.reserve(request())
        self.assertEqual(self.grant_counts(),(30000,3))
        rotated=XCostController(self.factory,replace(renewed.policy,window_id='synthetic:later'),self.app)
        self.assertFalse(rotated.eligible(10000,'workspace-new'))

    def test_no_implicit_activation_and_old_binary_insert_is_fenced(self):
        self.assertFalse(self.c.eligible(10000,'workspace-a'))
        with self.assertRaises(XCostAdmissionError):
            self.c.reserve(request())
        with self.factory() as db:
            self.assertIsNone(db.execute('SELECT * FROM postriff.x_cost_app_activation WHERE app_key=%s',(self.app,)).fetchone())
        self.c.activate('synthetic:explicit-fixture')
        self.c.reserve(request())
        with self.factory() as db:
            with self.assertRaises(self.psycopg.errors.NotNullViolation):
                db.execute("""INSERT INTO postriff.x_cost_reservations
                    (request_id,app_key,window_id,workspace_id,connection_id,operation,method,endpoint,
                     price_key,estimated_units,estimated_micros,policy_hash)
                    VALUES(%s,%s,%s,'workspace-a','connection-a','identity','GET','/2/users/me','identity_read',1,10000,%s)""",
                    (str(uuid4()),self.app,self.p.window_id,self.p.fingerprint))
        self.assertEqual(self.grant_counts(),(10000,1))
