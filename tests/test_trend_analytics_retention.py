"""Independent retention: synthetic reviewed grants, actual scoped SQL/cascades."""
import copy
import json
import os
import time
import unittest
import uuid
from datetime import timedelta

import test_trend_integration as integration
from postriff_phase2.growth.trends import analytics_retention as ar, contracts, learning, opportunities, retention, revocation
from postriff_phase2.growth.trends.store import TrendStore, TrendStorageError


@unittest.skipUnless(os.environ.get("TREND_SERVICE_TEST_DSN"), "explicit disposable PostgreSQL required")
class AnalyticsRetentionSQL(unittest.TestCase):
    def setUp(self):
        integration.DurableServiceTests.setUpClass.__func__(type(self))
        self.store = TrendStore(self.connect)
        self.scope = "workspace:" + self.wid
        page = self.svc.list(self.wid, "fixture-session", kind="opportunity")
        shown = next(p for p in page["data"] if p["id"] == self.oid)
        event = self.svc.exposure(self.wid, "fixture-session", {
            "event_id": str(uuid.uuid4()), "exposure_token": page["exposure_token"],
            "opportunity_id": self.oid, "opportunity_revision": shown["revision"],
            "trust_receipt_id": shown["trust_receipt_id"], "context_digest": shown["context_digest"],
            "eligible_candidates": [{"opportunity_id": p["id"], "revision": p["revision"]} for p in page["data"]
                if p["state"] in ("candidate", "ready") and p["verification_state"] == "verified"]})
        self.eid = event["data"]["exposure_id"]
        with self.connect() as db:
            self.raw = db.execute("SELECT observation_id::text,provider_id,source_identity,source_policy_version,author_key FROM pr_trend_observations WHERE scope_key=%s", (self.scope,)).fetchone()

    def authority(self, change=None, *, contract_change=None):
        now = time.time(); until = opportunities.iso(now + 30*86400)
        provider = "analytics-fixture-" + uuid.uuid4().hex[:12]
        with self.connect() as db, db.cursor() as cur:
            preview = ar.review_requirements(self.store, cur, self.wid, self.actor, self.eid)
            self.assertFalse(preview["reviewed"])
            grant = {"schema_version": ar.VERSION, "enabled": True, "permission": "allow", "operation": ar.OPERATION,
                "purpose": ar.PURPOSE, "data_class": "content_free_exposure_metadata", "survive_raw_ttl": True,
                "cascade": ar.CASCADE, "reviewed_by": "synthetic-reviewer", "review_ref": "synthetic-contract-only-not-live-permission",
                "reviewed_at": opportunities.iso(now-1), "expires_at": until, "max_retention_seconds": 7*86400,
                "purge_within_seconds": 60, "allowed_fields": preview["allowed_fields"], "source_authorities": preview["source_authorities"]}
            if change: grant.update(change)
            rights = {name: {"state": "allow" if name in ar.PERMISSIONS else "deny", "policy_ref": "synthetic-independent-analytics-only",
                "audience_scope": self.scope, "expires_at": until} for name in contracts.PERMISSIONS}
            contract_grant = {**grant, **(contract_change or {})}
            self.store.register_contract(provider, "1", list(ar.PERMISSIONS), opportunities.iso(now-60), until,
                {"analytics_retention": contract_grant}, cursor=cur)
            self.store.register_policy({"scope_key": self.scope, "provider_id": provider, "version": "1", "operation": ar.OPERATION,
                "rights": rights, "effective_at": opportunities.iso(now-60), "expires_at": until, "readiness": "ready",
                "retention_seconds": 7*86400, "analytics_retention": grant}, provider_contract_version="1", cursor=cur)
        return {"provider_id": provider, "policy_version": "1"}

    def retain(self, authority=None, enabled=True):
        with self.connect() as db, db.cursor() as cur:
            return ar.retain_exposure(self.store, cur, self.wid, self.actor, self.eid, authority=authority, enabled=enabled)

    def read(self, oid):
        with self.connect() as db, db.cursor() as cur:
            return ar.read_current(self.store, cur, self.wid, self.actor, oid)

    def expire_raw(self):
        # Force only the synthetic raw-node TTL to pass; no grant/permission is
        # extended or rewritten. Independent aggregate validity must survive.
        with self.connect() as db:
            db.execute("UPDATE pr_trend_nodes SET retention_until=clock_timestamp()-interval '1 second' WHERE scope_key=%s AND node_id=%s", (self.scope, self.raw[0]))
        retention.sweep(self.store, limit=100)

    def assert_purged(self, oid):
        self.assertEqual(self.read(oid)["status"], "unavailable")
        result = ar.sweep(self.store, limit=100)
        self.assertGreaterEqual(result["suppressed"], 1)
        with self.connect() as db:
            data = db.execute("SELECT payload FROM pr_trend_projections WHERE scope_key=%s AND object_id=%s", (self.scope, oid)).fetchone()[0]
            root = db.execute("SELECT payload,purged_at FROM pr_trend_observations WHERE scope_key=%s AND metric_id=%s", (self.scope, ar.VERSION)).fetchone()
        self.assertEqual(data, {}); self.assertEqual(root[0], {}); self.assertIsNotNone(root[1])

    def test_default_unknown_and_unreviewed_grants_do_not_write_or_replace_short_path(self):
        self.assertEqual(self.retain(enabled=False), {"status": "disabled"})
        self.assertEqual(self.retain()["status"], "unavailable")
        for change in ({"permission": "unknown"}, {"enabled": False}, {"survive_raw_ttl": False},
                       {"allowed_fields": sorted(ar.FIELDS) + ["text"]}, {"cascade": "keep_forever"}):
            self.assertEqual(self.retain(self.authority(change))["status"], "unavailable")
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM pr_trend_observations WHERE scope_key=%s AND metric_id=%s", (self.scope, ar.VERSION)).fetchone()[0], 0)
            with db.cursor() as cur:
                self.assertEqual(self.store.get_projection(self.wid, self.actor, "exposure", self.eid, cursor=cur)["validity"], "valid")

    def test_independent_content_free_branch_survives_raw_physical_ttl_purge(self):
        authority = self.authority(); saved = self.retain(authority)
        self.assertEqual(saved["status"], "available", saved)
        self.assertGreater(opportunities.epoch(saved["analytics_expires_at"]), opportunities.epoch(saved["metadata"]["source_expires_at"]))
        self.assertFalse(saved["source_rights_extended"])
        self.assertEqual(set(saved["metadata"]), set(ar.FIELDS))
        self.assertTrue(self.retain(authority)["existing"])
        self.expire_raw()
        self.assertEqual(self.read(saved["object_id"])["status"], "available")
        with self.connect() as db, db.cursor() as cur:
            raw = db.execute("SELECT payload,author_key,purged_at FROM pr_trend_observations WHERE scope_key=%s AND observation_id=%s", (self.scope, self.raw[0])).fetchone()
            self.assertEqual(raw[0], {}); self.assertIsNone(raw[1]); self.assertIsNotNone(raw[2])
            # Generic aggregate-only projection remains redacted. The dedicated
            # reader permits strictly validated metadata, never raw prose.
            self.assertEqual(self.store.get_projection(self.wid, self.actor, "analytics_exposure", saved["object_id"], cursor=cur)["payload"], {})
            self.assertEqual(len(ar.list_current(self.store, cur, self.wid, self.actor)["items"]), 1)
        self.assertEqual(ar.sweep(self.store)["suppressed"], 0)

    def test_source_deletion_after_raw_purge_uses_durable_tombstone(self):
        saved = self.retain(self.authority()); self.expire_raw()
        revocation.revoke_source(self.store, self.scope, self.raw[1], self.raw[2])
        self.assert_purged(saved["object_id"])

    def test_author_deletion_after_raw_purge_uses_durable_author_digest(self):
        saved = self.retain(self.authority()); self.expire_raw()
        revocation.revoke_author(self.store, self.raw[1], self.raw[4])
        self.assert_purged(saved["object_id"])

    def test_source_policy_and_contract_revocation_are_not_ttl_exceptions(self):
        saved = self.retain(self.authority()); self.expire_raw()
        revocation.revoke_policy(self.store, self.scope, self.raw[1], self.raw[3])
        self.assert_purged(saved["object_id"])

    def test_source_contract_revocation_after_raw_purge(self):
        saved = self.retain(self.authority()); self.expire_raw()
        with self.connect() as db:
            db.execute("UPDATE pr_trend_provider_contracts SET revoked_at=now() WHERE provider_id=%s", (self.raw[1],))
        self.assert_purged(saved["object_id"])

    def test_independent_analytics_grant_revocation_physically_purges_branch(self):
        authority = self.authority(); saved = self.retain(authority)
        revocation.revoke_policy(self.store, self.scope, authority["provider_id"], "1")
        self.assert_purged(saved["object_id"])

    def test_exact_contract_fingerprint_and_review_scope_required(self):
        mismatch = self.authority(contract_change={"review_ref": "different-review"})
        self.assertEqual(self.retain(mismatch)["status"], "unavailable")
        authority = self.authority()
        with self.connect() as db:
            db.execute("UPDATE pr_trend_provider_contracts SET manifest=manifest||'{\"changed\":true}'::jsonb WHERE provider_id=%s", (self.raw[1],))
        self.assertEqual(self.retain(authority)["status"], "unavailable")

    def test_missing_privacy_identity_anchor_fails_closed_after_purge(self):
        saved = self.retain(self.authority()); self.expire_raw()
        with self.connect() as db:
            db.execute("DELETE FROM pr_trend_observations WHERE scope_key=%s AND observation_id=%s", (self.scope, self.raw[0]))
        self.assert_purged(saved["object_id"])

    def test_profile_deletion_and_cross_tenant_reads_never_leak_metadata(self):
        saved = self.retain(self.authority())
        with self.connect() as db, db.cursor() as cur:
            with self.assertRaises(TrendStorageError):
                ar.read_current(self.store, cur, str(uuid.uuid4()), self.actor, saved["object_id"])
        with self.connect() as db:
            db.execute("UPDATE pr_profiles SET deleted_at=now() WHERE user_id=%s", (self.actor,))
        with self.assertRaises(TrendStorageError): self.read(saved["object_id"])
        self.assertGreaterEqual(ar.sweep(self.store)["suppressed"], 1)
        with self.connect() as db:
            self.assertEqual(db.execute("SELECT payload FROM pr_trend_projections WHERE scope_key=%s AND object_id=%s", (self.scope, saved["object_id"])).fetchone()[0], {})

    def test_content_in_a_typed_field_or_unbound_projection_is_not_readable(self):
        saved = self.retain(self.authority())
        with self.connect() as db:
            db.execute("""UPDATE pr_trend_projections SET payload=jsonb_set(payload,'{metadata,context_digest}','\"secret raw prose\"'::jsonb)
                WHERE scope_key=%s AND object_id=%s""", (self.scope, saved["object_id"]))
        self.assertEqual(self.read(saved["object_id"])["status"], "unavailable")

    def test_learning_prefers_retained_metadata_without_double_count_or_source_revival(self):
        saved = self.retain(self.authority())
        def report():
            with self.connect() as db, db.cursor() as cur:
                return learning.report(cur, self.wid, self.actor, time.time(), store=self.store)
        before = report()
        self.assertEqual(before["denominator"]["exposures"], 1)
        self.assertEqual(before["coverage"]["independent_analytics_views"], 1)
        self.expire_raw()
        after = report()
        self.assertEqual(after["denominator"]["exposures"], 1)
        self.assertEqual(after["denominator"]["unaccepted"], 1)
        self.assertEqual(after["outcome_states"], {})
        self.assertFalse(after["exposures"][0]["source_rights_extended"])
        revocation.revoke_source(self.store, self.scope, self.raw[1], self.raw[2])
        self.assertEqual(report()["denominator"]["exposures"], 0)

    def test_unresolved_author_privacy_is_not_inferred_allowed(self):
        authority = self.authority()
        with self.connect() as db:
            db.execute("UPDATE pr_trend_observations SET author_key=NULL,author_status='unknown' WHERE scope_key=%s AND observation_id=%s", (self.scope, self.raw[0]))
        self.assertEqual(self.retain(authority)["status"], "unavailable")

    def test_sweep_cursor_reaches_invalid_later_metadata_behind_valid_records(self):
        first = self.retain(self.authority())
        authority = self.authority(); second = self.retain(authority)
        with self.connect() as db:
            db.execute("""UPDATE pr_trend_observations SET payload=jsonb_set(payload,'{analytics,metadata,context_digest}','\"invalid\"'::jsonb)
                WHERE scope_key=%s AND source_identity=%s""", (self.scope, "analytics-exposure:" + second["object_id"]))
        with self.connect() as db:
            expiry, node = db.execute("""SELECT n.retention_until,o.observation_id::text FROM pr_trend_observations o
                JOIN pr_trend_nodes n ON(n.scope_key,n.node_id)=(o.scope_key,o.observation_id)
                WHERE o.scope_key=%s AND o.source_identity=%s""", (self.scope, "analytics-exposure:" + first["object_id"])).fetchone()
        # Previous test tenants share this disposable DB; begin this bounded
        # page immediately before our first record instead of assuming a global
        # empty retention table.
        page = ar.sweep(self.store, limit=1, after=[opportunities.iso(expiry-timedelta(microseconds=1)), self.scope, node])
        self.assertEqual(page["checked"], 1)
        self.assertIsNotNone(page["next_key"])
        next_page = ar.sweep(self.store, limit=1, after=page["next_key"])
        self.assertEqual(next_page["suppressed"], 1)
        self.assertEqual(self.read(first["object_id"])["status"], "available")
        self.assertEqual(self.read(second["object_id"])["status"], "unavailable")

    def test_restore_guard_defers_privacy_reconciliation_without_tombstones(self):
        saved = self.retain(self.authority())
        with self.connect() as db:
            db.execute("UPDATE pr_trend_runtime_guard SET reads_ready=false WHERE singleton")
        try:
            self.assertEqual(ar.sweep(self.store)["deferred"], "restore_in_progress")
        finally:
            with self.connect() as db:
                db.execute("UPDATE pr_trend_runtime_guard SET reads_ready=true WHERE singleton")
        self.assertEqual(self.read(saved["object_id"])["status"], "available")


if __name__ == "__main__":
    unittest.main()
