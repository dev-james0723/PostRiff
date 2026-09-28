"""Independent adversarial contract/policy/flag tests. All fixtures are synthetic.

No provider credentials, clock dependence, network access, or implementation writes.
Acceptance anchors: T02/T03/T06/T17/T20/T21/T31/T32.
"""
import copy
import math
import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from postriff_phase2.growth.trends import contracts as C, config
from postriff_phase2.growth.trends.policy import SourcePolicy, ProviderCapability, admit, evidence_projection
from postriff_phase2.growth.trends.providers.base import observation

NOW = "2026-09-27T12:00:00Z"
BEFORE = "2026-09-26T12:00:00Z"
AFTER = "2026-09-28T12:00:00Z"
WORKSPACE = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
SCOPE = "workspace:" + WORKSPACE


def permissions(scope_key=SCOPE, **states):
    return {name: {"state": states.get(name, "allow"), "policy_ref": "synthetic-policy",
                   "audience_scope": scope_key, "expires_at": AFTER} for name in C.PERMISSIONS}


def policy(scope_key=SCOPE, **overrides):
    values = dict(id="synthetic-policy", version="fixture-v1", provider_id="fixture",
                  operation="sample", scope_key=scope_key, rights=permissions(scope_key),
                  reviewed_by="synthetic-reviewer", review_ref="fixture-review", effective_at=BEFORE,
                  expires_at=AFTER, retention_seconds=3600, readiness="ready",
                  verified_scopes=("read",), price_ref="synthetic-price", approved_attempt_cap_microusd=100)
    values.update(overrides)
    return SourcePolicy(**values)


def payload(kind):
    return {
        "raw_post": {"platform": "fixture", "native_id": "item-1", "author_status": "known",
                     "author_key": "fixture:author", "text": "喺呢度 test 😎", "language": "yue-en",
                     "canonical_url": "https://example.com/post/1"},
        "owned_post": {"platform": "fixture", "native_id": "item-1", "author_status": "unknown",
                       "connection_id": "synthetic-connection", "text": "original"},
        "aggregate_metric": {"dataset_id": "sample-1", "metric_definition": "count-v1", "unit": "posts",
                             "population": "declared sample", "aggregation_semantics": "disjoint",
                             "window_start": BEFORE, "window_end": NOW, "value": 0},
        "search_lead": {"canonical_url": "https://example.com/lead", "text": "permitted excerpt"},
        "trend_seed": {"topic_id": "seed-1", "native_score_semantics": "normalized provider interest"},
    }[kind]


def row(kind="raw_post", *, source_identity="item-1", scope_key=SCOPE, **kwargs):
    args = dict(policy=policy(scope_key), source_identity=source_identity, revision_identity="rev-1",
                sequence=1, kind=kind, operation="create", payload=payload(kind), event_at=BEFORE,
                received_at=NOW, available_at=NOW, coverage_epoch="sample-v1",
                contract_version="fixture-v1", access_method="synthetic")
    args.update(kwargs)
    return observation(**args)


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.net = []
        for target in ("socket.create_connection", "socket.socket.connect", "socket.getaddrinfo",
                       "urllib.request.urlopen", "urllib.request.OpenerDirector.open"):
            p = patch(target, side_effect=AssertionError("UNEXPECTED_EGRESS: " + target))
            self.net.append(p.start()); self.addCleanup(p.stop)

    def tearDown(self):
        for mock in self.net:
            mock.assert_not_called()

    def reject(self, function, *args, **kwargs):
        with self.assertRaises(C.ContractError):
            function(*args, **kwargs)


class ObservationContracts(OfflineTest):
    def test_all_five_unions_accept_valid_independent_payloads(self):
        self.assertEqual(set(C.KINDS), {"raw_post", "owned_post", "aggregate_metric", "search_lead", "trend_seed"})
        for kind in C.KINDS:
            with self.subTest(kind=kind):
                source = row(kind)
                checked = C.validate_observation(source)
                self.assertEqual(checked, source)
                checked["payload"]["private_mutation"] = True
                self.assertNotIn("private_mutation", source["payload"])

    def test_exact_envelope_no_missing_or_extra_fields(self):
        source = row()
        for key in source:
            with self.subTest(missing=key):
                bad = copy.deepcopy(source); del bad[key]
                self.reject(C.validate_observation, bad)
        self.reject(C.validate_observation, dict(source, fabricated_stage="hot"))

    def test_kind_operation_revision_and_schema_are_strict(self):
        for key, values in {"kind": ["post", None, []], "operation": ["publish", None],
                            "revision_sequence": [True, -1, 1.5, 2**63], "schema_version": ["v0"]}.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    bad = row(); bad[key] = value
                    self.reject(C.validate_observation, bad)

    def test_unknown_author_is_not_known_creator(self):
        for changes in ({"author_status": "known", "author_key": None},
                        {"author_status": "unknown", "author_key": "made-up"},
                        {"author_status": "withheld", "author_key": "made-up"}):
            with self.subTest(changes=changes):
                bad = row(); bad["payload"].update(changes); bad["payload_digest"] = C.digest(bad["payload"])
                self.reject(C.validate_observation, bad)

    def test_identity_and_author_fields_cannot_be_arrays(self):
        for key in ("platform", "native_id", "author_key"):
            with self.subTest(key=key):
                bad = row(); bad["payload"][key] = ["synthetic"] * 1000
                bad["payload_digest"] = C.digest(bad["payload"])
                self.reject(C.validate_observation, bad)

    def test_owned_post_cannot_enter_shared_domain_or_omit_connection(self):
        self.reject(row, "owned_post", scope_key="shared:fixture")
        bad = row("owned_post"); del bad["payload"]["connection_id"]
        bad["payload_digest"] = C.digest(bad["payload"])
        self.reject(C.validate_observation, bad)

    def test_unions_reject_fabricated_cross_kind_evidence(self):
        probes = [("aggregate_metric", "native_id", "fake"), ("aggregate_metric", "representative_posts", []),
                  ("search_lead", "mention_count", 10), ("search_lead", "engagement", 10),
                  ("trend_seed", "mention_count", 10), ("trend_seed", "author_key", "fake")]
        for kind, key, value in probes:
            with self.subTest(kind=kind, key=key):
                bad = row(kind); bad["payload"][key] = value; bad["payload_digest"] = C.digest(bad["payload"])
                self.reject(C.validate_observation, bad)

    def test_zero_null_and_invalid_aggregate_numbers(self):
        self.assertEqual(row("aggregate_metric")["payload"]["value"], 0)
        for value in (None, True, [], float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                bad = row("aggregate_metric"); bad["payload"]["value"] = value
                # Nonfinite JSON is rejected while generating or validating a digest.
                with self.assertRaises(C.ContractError):
                    bad["payload_digest"] = C.digest(bad["payload"])
                    C.validate_observation(bad)
        good = row("aggregate_metric"); good["payload"].update(value=None, null_reason="not_returned")
        good["payload_digest"] = C.digest(good["payload"])
        self.assertIsNone(C.validate_observation(good)["payload"]["value"])

    def test_timestamp_boundaries_and_unknown_publication_time(self):
        for key, value in (("received_at", AFTER), ("retention_until", NOW),
                           ("event_at", "2026-09-27T12:00:00"),
                           ("event_at", "2026-09-27T12:00:00+01:00"), ("event_at", None)):
            with self.subTest(key=key, value=value):
                bad = row(); bad[key] = value
                self.reject(C.validate_observation, bad)
        unknown = row(event_at=None)
        self.assertEqual(unknown["time_basis"], "retrieval")

    def test_text_bytes_and_nested_payload_are_bounded(self):
        for content in ("a" * (C.MAX_TEXT + 1), ["not", "text"]):
            with self.subTest(content_type=type(content).__name__):
                bad = row(); bad["payload"]["text"] = content; bad["payload_digest"] = C.digest(bad["payload"])
                self.reject(C.validate_observation, bad)
        bad = row(); bad["payload"]["metadata"] = ["中" * 1000] * 30
        bad["payload_digest"] = C.digest(bad["payload"])
        self.reject(C.validate_observation, bad)

    def test_digest_order_independent_and_tamper_detected(self):
        self.assertEqual(C.digest({"b": 2, "a": "喺"}), C.digest({"a": "喺", "b": 2}))
        bad = row(); bad["payload"]["text"] = "changed"
        self.reject(C.validate_observation, bad)

    def test_identity_binds_native_item_revision_and_domain_not_text(self):
        first = row()
        self.assertEqual(first["observation_id"], row()["observation_id"])
        variants = [row(source_identity="item-2"), row(revision_identity="rev-2"),
                    row(scope_key="workspace:" + OTHER)]
        self.assertTrue(all(first["observation_id"] != x["observation_id"] for x in variants))
        self.assertTrue(all(first["payload_digest"] == x["payload_digest"] for x in variants))

    def test_delete_tombstone_cannot_retain_content(self):
        for kind in C.KINDS:
            with self.subTest(kind=kind):
                tomb = row(kind, operation="delete", payload={"platform": "fixture"})
                self.assertEqual(tomb["payload"], {"platform": "fixture"})
                tomb["payload"]["text"] = "must be purged"; tomb["payload_digest"] = C.digest(tomb["payload"])
                self.reject(C.validate_observation, tomb)

    def test_coverage_axes_and_measured_breadth_denominator(self):
        coverage = dict(availability="available", representation="aggregate_only",
                        completeness="complete_within_scope", breadth="unknown",
                        scope_ref="sample", coverage_epoch="v1")
        self.assertEqual(C.validate_coverage(coverage), coverage)
        for key, value in (("breadth", "high"), ("availability", "aggregate_only"), ("completeness", "global")):
            with self.subTest(key=key): self.reject(C.validate_coverage, dict(coverage, **{key: value}))


class RightsAndPolicy(OfflineTest):
    def test_each_permission_is_independent_fail_closed(self):
        for name in C.PERMISSIONS:
            with self.subTest(permission=name):
                rights = permissions(); self.assertTrue(C.permits(rights, name, SCOPE, NOW))
                for state in ("unknown", "deny"):
                    rights[name]["state"] = state
                    self.assertFalse(C.permits(rights, name, SCOPE, NOW))
                del rights[name]
                self.assertFalse(C.permits(rights, name, SCOPE, NOW))
        self.assertFalse(C.permits(permissions(), "invent_permission", SCOPE, NOW))

    def test_grant_scope_expiry_and_unknown_states(self):
        for name in C.PERMISSIONS:
            with self.subTest(permission=name):
                rights = permissions(); rights[name]["expires_at"] = NOW
                self.assertFalse(C.permits(rights, name, SCOPE, NOW))
                self.assertFalse(C.permits(permissions(), name, "workspace:" + OTHER, NOW))
        self.reject(C.validate_rights, {"llm_process": True})
        self.reject(C.validate_rights, dict(permissions(), made_up={}))

    def test_raw_and_metric_storage_require_their_own_grants(self):
        for kind, permission in (("raw_post", "store_raw"), ("aggregate_metric", "store_metrics"), ("search_lead", "store_raw")):
            with self.subTest(kind=kind):
                self.reject(row, kind, policy=policy(rights=permissions(**{permission: "unknown"})))

    def test_rights_cross_scope_rejected_even_if_policy_object_created(self):
        wrong = permissions(); wrong["retrieve"]["audience_scope"] = "workspace:" + OTHER
        self.reject(row, policy=policy(rights=wrong))

    def test_policy_effective_expiry_revocation_and_readiness(self):
        p = policy()
        self.assertTrue(p.valid(NOW)); self.assertFalse(p.valid(AFTER))
        for changed in (replace(p, effective_at="2026-09-27T13:00:00Z"), replace(p, revoked_at=NOW)):
            self.assertFalse(changed.valid(NOW))
        for readiness in C.READINESS:
            with self.subTest(readiness=readiness):
                self.assertEqual(replace(p, readiness=readiness).valid(NOW), readiness == "ready")

    def test_admission_checks_limits_funding_entitlements_scopes(self):
        cap = ProviderCapability("fixture", "sample", "v1", ("raw_post",), "https://example.com/feed",
                                 "fixture", "synthetic", ("read",), 10, 4096, 5, 1, "request", "delete")
        args = dict(at=NOW, requested_scope=SCOPE, enabled=True, item_limit=10, byte_limit=4096,
                    reservation_microusd=50, entitlement_current=True)
        admit(cap, policy(), **args)
        for key, value in (("enabled", False), ("entitlement_current", False), ("requested_scope", "workspace:"+OTHER),
                           ("item_limit", 11), ("item_limit", True), ("byte_limit", 4097),
                           ("reservation_microusd", 101), ("reservation_microusd", 0)):
            with self.subTest(key=key, value=value): self.reject(admit, cap, policy(), **dict(args, **{key: value}))
        for p in (policy(verified_scopes=()), policy(operation="other"), policy(price_ref=None),
                  policy(rights=permissions(retrieve="unknown"))): self.reject(admit, cap, p, **args)

    def test_capability_integer_limits_reject_boolean_and_fractional(self):
        cap = ProviderCapability("fixture", "sample", "v1", ("raw_post",), "https://example.com/feed",
                                 "fixture", "synthetic", (), 10, 4096, 5, 1, "request", "delete")
        for key, bad in (("max_items", True), ("max_items", 1.5), ("timeout_seconds", True),
                         ("max_attempts", 1.5), ("max_response_bytes", 1024.5)):
            with self.subTest(key=key, value=bad): self.reject(replace, cap, **{key: bad})

    def test_shared_admission_requires_explicit_cross_workspace_right(self):
        cap = ProviderCapability("fixture", "sample", "v1", ("raw_post",), "https://example.com/feed",
                                 "fixture", "synthetic", (), 10, 4096, 5, 1, "request", "delete")
        self.reject(admit, cap, policy("shared:sample", rights=permissions("shared:sample", share_across_workspaces="unknown")),
                    at=NOW, requested_scope="shared:sample", enabled=True, item_limit=1, byte_limit=1024,
                    reservation_microusd=0, entitlement_current=True, billable=False)

    def test_projection_needs_both_current_and_observation_display_rights(self):
        source = row()
        for permission, field in (("display_excerpt", "excerpt"), ("display_link", "url")):
            for revoke_where in ("source", "policy"):
                with self.subTest(permission=permission, revoke_where=revoke_where):
                    changed = copy.deepcopy(source); p = policy()
                    if revoke_where == "source": changed["rights"][permission]["state"] = "unknown"
                    else: p = policy(rights=permissions(**{permission:"unknown"}))
                    self.assertNotIn(field, evidence_projection(changed, p, at=NOW, entitled=True))
        for p, at, entitled in ((policy(), NOW, False), (policy(revoked_at=NOW), NOW, True),
                                (policy(version="other"), NOW, True), (policy(), AFTER, True)):
            self.assertIsNone(evidence_projection(source, p, at=at, entitled=entitled))

    def test_policy_for_another_provider_cannot_display_same_version(self):
        self.assertIsNone(evidence_projection(row(), policy(provider_id="unrelated"), at=NOW, entitled=True))


class FeatureGates(OfflineTest):
    def test_every_new_flag_defaults_off_even_with_ambient_flags_on(self):
        with patch.dict(os.environ, {name:"true" for name in config.FLAG_NAMES}):
            for name in config.NAMES:
                with self.subTest(flag=name): self.assertFalse(config.enabled(name, {}))
        self.assertFalse(config.workspace_allowed(WORKSPACE, {}))
        self.assertFalse(config.dispatch_allowed("bluesky", "live_sample", {}))

    def test_preview_environment_cuts_off_egress_even_if_flags_requested_on(self):
        values = {name: "true" for name in config.FLAG_NAMES}
        values.update(VERCEL_ENV="preview", RAFII_TREND_ALLOWED_OPERATIONS="bluesky:live_sample")
        with patch.dict(os.environ, values, clear=True), patch.object(config.flags, "_values", None):
            self.assertFalse(config.dispatch_allowed("bluesky", "live_sample"))
            for name in ("PROVIDER_OPERATIONS", "MODEL_ENRICHMENT", "NOTIFICATIONS", "MULTIMODAL"):
                with self.subTest(name=name): self.assertFalse(config.enabled(name))

    def test_dispatch_needs_each_switch_and_exact_operation_allowlist(self):
        values = {name:"true" for name in config.FLAG_NAMES}
        values["RAFII_TREND_ALLOWED_OPERATIONS"] = "bluesky:live_sample"
        self.assertTrue(config.dispatch_allowed("bluesky", "live_sample", values))
        for flag in ("INTELLIGENCE", "RADAR", "PROVIDER_OPERATIONS"):
            v = dict(values); v["RAFII_TREND_"+flag+"_ENABLED"] = "false"
            self.assertFalse(config.dispatch_allowed("bluesky", "live_sample", v))
        self.assertFalse(config.dispatch_allowed("bluesky", "archive", values))
        self.assertFalse(config.dispatch_allowed("web", "corroborate", values))

    def test_stage_gate_requires_current_receipt_method_and_actual_boolean_qualification(self):
        values = {name:"true" for name in config.FLAG_NAMES}
        args = dict(verification_state="verified", cohort_qualified=True, method_state="production", values=values)
        self.assertTrue(config.stage_allowed(**args))
        for key, value in (("verification_state", "pending"), ("verification_state", "inputs_deleted"),
                           ("cohort_qualified", 1), ("cohort_qualified", False), ("method_state", "shadow")):
            with self.subTest(key=key,value=value): self.assertFalse(config.stage_allowed(**dict(args, **{key:value})))
        self.assertFalse(config.stage_allowed(**dict(args, values=dict(values, RAFII_TREND_TRUST_RECEIPTS_ENABLED="false"))))

    def test_workspace_allowlist_has_no_wildcard_or_cross_tenant_default(self):
        values = {"RAFII_TREND_INTELLIGENCE_ENABLED":"true", "RAFII_TREND_WORKSPACE_ALLOWLIST":WORKSPACE}
        self.assertTrue(config.workspace_allowed(WORKSPACE, values))
        self.assertFalse(config.workspace_allowed(OTHER, values))
        self.assertFalse(config.workspace_allowed(WORKSPACE, dict(values, RAFII_TREND_WORKSPACE_ALLOWLIST="*")))


if __name__ == "__main__": unittest.main()
