"""Rafii POC-1 candidate: one account, one native metric, one 24h cohort. SYNTHETIC stored observations only.

No provider, model, network or database: pure qualification, eligibility, snapshot/export and draft-link semantics.
Acceptance IDs from the 2026-10-15 research pack are named in each test.
"""
import copy
import csv
import io
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from postriff_alpha.domain import AlphaError
from postriff_phase2 import insights, operation_eligibility as OE
from postriff_phase2.contracts import digest
from postriff_phase2.coworker import growth_loop, review
from postriff_phase2.growth import metric_schedule as M
from postriff_phase2.providers import ThreadsProvider

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc).timestamp()
DAY = 86400
SCOPES = sorted(M.NATIVE_ANALYTICS_SCOPES['instagram'])
SHA = 'a' * 40


def eligibility(**overrides):
    channel = {'id': 'own', 'platform': 'Instagram', 'expiresAt': NOW + 30 * DAY}
    args = dict(channel=channel, capability={'level': 'Direct', 'evidence': ''},
                credential={'provider': 'instagram', 'scopes': SCOPES, 'revoked': False}, account_deletion=False, now=NOW,
                latest_reading={'id': 'reach0', 'observedAt': NOW - DAY})
    args.update(overrides)
    return {'own': OE.analytics_read('workspace', 'own', **args)}


def fixture(n=6, values=None):
    """n verified Instagram posts, each with a native reach reading exactly at +24h (and a likes reading)."""
    values = values or [i * 10 for i in range(n)]
    jobs, rows = [], []
    for i in range(n):
        at = NOW - (3 + i) * DAY
        job = {'id': str(i), 'state': 'verified', 'providerReference': 'post-' + str(i), 'verification': {'at': at},
               'manifest': {'channelId': 'own', 'platform': 'Instagram', 'contentType': {'id': 'text', 'formatId': 'text'},
                            'payload': {'language': 'en', 'text': 'Synthetic original ' + str(i)}}}
        jobs.append(job)
        for name, value in (('reach', values[i]), ('likes', i)):
            rows.append({'observationId': name + str(i), 'jobId': str(i), 'connectionId': 'own', 'provider': 'instagram',
                         'nativePostId': job['providerReference'], 'nativeName': name, 'definitionVersion': insights.DEFINITION_VERSION,
                         'unit': 'count', 'value': value, 'availability': 'available', 'observedAt': at + DAY,
                         'ingestedAt': at + DAY + 1, 'readOffset': '24h', 'sourceRef': 'https://graph.instagram.com/v25.0/post/insights?access_token=SYNTHETIC',
                         'collectionState': 'measured'})
    state = {'phase2': {'channels': [{'id': 'own', 'platform': 'Instagram', 'expiresAt': NOW + 30 * DAY}], 'jobs': jobs}}
    scope = {'channelIds': ['own'], 'publicationPeriod': {'start': '2026-10-01T00:00:00Z', 'end': '2026-10-15T00:00:00Z', 'timezone': 'America/Indiana/Indianapolis'},
             'horizon': '24h', 'language': 'en', 'formatIds': ['text'],
             'nativeMetric': [{'provider': 'instagram', 'nativeName': 'reach', 'definitionVersion': insights.DEFINITION_VERSION, 'unit': 'count'}],
             'comparison': {'kind': 'none'}, 'aggregation': 'median'}
    return state, rows, scope


def reach(rows, job):
    return next(r for r in rows if r['jobId'] == job and r['nativeName'] == 'reach')


class Qualification(unittest.TestCase):
    def setUp(self):
        self.state, self.rows, self.scope = fixture()
        self.rights = eligibility()

    def project(self, rights=None):
        rights = self.rights if rights is None else rights
        context = review.resolve_review_context('workspace', self.scope, self.state, NOW, rights_epoch=OE.rights_epoch(rights))
        return review.project_review(self.state, context, self.rows, rights, NOW)

    def result(self, projection, job):
        return next(e for e in projection['nativeResults'] if e['publicationBinding']['jobId'] == job)

    def test_A_D01_observed_zero_and_missing_stay_distinct(self):
        reach(self.rows, '1').update(value=None, availability='unavailable')
        p = self.project()
        zero, missing = self.result(p, '0'), self.result(p, '1')
        self.assertEqual((zero['value'], zero['valueState'], zero['eligible']), (0.0, 'measured', True))
        self.assertEqual((missing['value'], missing['valueState'], missing['reason'], missing['eligible']), (None, 'missing', 'missing_reading', False))
        self.assertEqual(p['groups'][0]['sampleSize'], 5)
        self.assertEqual(p['groups'][0]['value'], 30.0)          # median of 0,20,30,40,50: the missing reading is not a zero
        self.assertEqual(p['coverage']['excludedByReason'], {'missing_reading': 1})

    def test_A_D02_late_unknown_and_early_readings_never_enter_the_24h_cohort(self):
        published = self.state['phase2']['jobs'][1]['verification']['at']
        reach(self.rows, '1').update(observedAt=published + DAY + 4 * 3600, ingestedAt=published + DAY + 4 * 3600 + 1)   # +3h tolerance missed
        reach(self.rows, '2').update(readOffset=None)                                                                     # legacy row of unknown age
        published3 = self.state['phase2']['jobs'][3]['verification']['at']
        reach(self.rows, '3').update(observedAt=published3 + 20 * 3600, ingestedAt=published3 + 20 * 3600 + 1)            # early, labelled 24h
        published4 = self.state['phase2']['jobs'][4]['verification']['at']
        reach(self.rows, '4').update(observedAt=published4 + DAY + 2 * 3600, ingestedAt=published4 + DAY + 2 * 3600 + 1) # within tolerance
        p = self.project()
        late, legacy, early, within = (self.result(p, j) for j in '1234')
        self.assertEqual((late['eligible'], late['reason'], late['value']), (False, 'window_late', None))
        self.assertEqual(late['rejectedReadings'][0]['actualAgeSeconds'], DAY + 4 * 3600)
        self.assertEqual(late['rejectedReadings'][0]['windowQualification'], 'missed')
        self.assertEqual((legacy['reason'], legacy['rejectedReadings'][0]['windowQualification']), ('unknown_read_offset', 'unknown'))
        self.assertEqual(legacy['rejectedReadings'][0]['actualAgeSeconds'], DAY)   # actual age is kept even when the label is unknown
        self.assertEqual((early['reason'], early['rejectedReadings'][0]['windowQualification']), ('window_unqualified', 'early'))
        self.assertEqual((within['eligible'], within['windowQualification'], within['actualAgeSeconds']), (True, 'within_tolerance', DAY + 7200))
        self.assertEqual(p['coverage']['excludedByReason'], {'window_late': 1, 'unknown_read_offset': 1, 'window_unqualified': 1})
        self.assertEqual(p['resolvedContext']['windowTolerance'], {'24h': M.WINDOW_TOLERANCE['24h']})

    def test_A_D02_readings_after_the_cutoff_do_not_exist_for_the_scope(self):
        p = self.project()
        later = {**reach(self.rows, '0'), 'observationId': 'later', 'value': 999, 'observedAt': NOW + 10, 'ingestedAt': NOW + 11}
        self.rows.append(later)
        self.scope['cutoffAt'] = p['resolvedContext']['cutoffAt']
        again = self.project()
        self.assertEqual(again['basisDigest'], p['basisDigest'])

    def test_A_D03_native_definition_unit_and_metric_identity_are_exact(self):
        reach(self.rows, '0')['definitionVersion'] = '2025-01'
        reach(self.rows, '1')['unit'] = 'percent'
        p = self.project()
        self.assertEqual(self.result(p, '0')['reason'], 'definition_mismatch')
        self.assertEqual(self.result(p, '1')['reason'], 'definition_mismatch')
        group = p['groups'][0]
        self.assertEqual((group['cohort']['nativeName'], group['cohort']['definitionVersion'], group['cohort']['unit']), ('reach', insights.DEFINITION_VERSION, 'count'))
        self.assertEqual(group['sampleSize'], 4)                  # likes readings never join the reach group
        self.assertTrue(all(e['nativeName'] == 'reach' for e in p['nativeResults']))
        with self.assertRaises(AlphaError):
            self.scope['nativeMetric'] = [{'provider': 'instagram', 'nativeName': 'reach', 'definitionVersion': '2025-01', 'unit': 'count'}]
            self.project()
        likes, views = reach(self.rows, '2') | {'nativeName': 'likes'}, reach(self.rows, '2')
        self.assertEqual(review.matched_ratio(likes, {**views, 'observedAt': views['observedAt'] + 1})['reason'], 'incompatible_readings')

    def test_A_D05_insufficient_sample_degrades_without_an_aggregate(self):
        for job in '2345':
            reach(self.rows, job).update(value=None, availability='unavailable')
        p = self.project()
        group = p['groups'][0]
        self.assertEqual((group['sampleSize'], group['value'], group['qualification'], group['minimumSample']), (2, None, 'insufficient_sample', 3))
        self.assertEqual(p['qualification'], 'insufficient_sample')
        self.assertEqual(p['coverage']['excludedByReason'], {'missing_reading': 4})
        self.assertEqual(review.review_takeaways(p, self.state, NOW), [])
        self.assertTrue(any('not statistical confidence' in line for line in p['limitations']))

    def test_A_D11_takeaways_use_only_measured_snapshot_numbers(self):
        reach(self.rows, '5').update(value=None, availability='unavailable')
        p = self.project()
        p['takeaways'] = review.review_takeaways(p, self.state, NOW)
        self.assertEqual(len(p['takeaways']), 1)
        t = p['takeaways'][0]
        self.assertEqual((t['contextDigest'], t['basisDigest'], t['generatedBy'], t['causal']), (p['contextDigest'], p['basisDigest'], 'deterministic', False))
        self.assertIn('was 20 across 5 comparable publications', t['statement'])
        self.assertEqual({e['observationId'] for e in t['supportBindings']}, {'reach0', 'reach1', 'reach2', 'reach3', 'reach4'})
        self.assertTrue(all(e['value'] is not None for e in t['supportBindings']))
        self.assertIn('1 publication readings were excluded', ' '.join(t['unknowns']))
        snapshot = review.build_review_snapshot(p, self.state, [], 'owner', SHA, NOW)
        self.assertEqual(snapshot['takeaways'][0]['basisDigest'], snapshot['basisDigest'])

    def test_A_U01_comparison_takeaway_keeps_support_counter_evidence_and_exclusions(self):
        self.scope['publicationPeriod'] = {'start': '2026-10-10T00:00:00Z', 'end': '2026-10-15T00:00:00Z', 'timezone': 'UTC'}
        self.scope['comparison'] = {'kind': 'previous_period', 'publicationPeriod': {'start': '2026-10-03T00:00:00Z', 'end': '2026-10-10T00:00:00Z', 'timezone': 'UTC'}}
        self.state, self.rows, _ = fixture(n=8, values=[90, 10, 80, 70, 20, 20, 20, 30])
        p = self.project()
        t = review.review_takeaways(p, self.state, NOW)[0]
        self.assertIn('against 20 across', t['statement'])
        self.assertEqual({e['observationId'] for e in t['counterEvidenceBindings']}, {'reach1'})   # current post below the baseline median
        self.assertTrue(all(e['sourceRef'] == 'https://graph.instagram.com/v25.0/post/insights' for e in t['supportBindings'] + t['baselineBindings']))
        self.assertEqual(t['excludedByReason'], p['coverage']['excludedByReason'])

    def test_A_S01_scope_cannot_reach_another_workspace_or_account(self):
        with self.assertRaises(AlphaError):
            review.resolve_review_context('workspace', {**self.scope, 'workspaceId': 'foreign'}, self.state, NOW)
        with self.assertRaises(AlphaError):
            review.resolve_review_context('workspace', {**self.scope, 'channelIds': ['foreign']}, self.state, NOW)
        reach(self.rows, '0')['connectionId'] = 'foreign'
        reach(self.rows, '1')['nativePostId'] = 'post-other'
        p = self.project()
        self.assertEqual(p['coverage']['excludedByReason'], {'publication_mismatch': 2})

    def test_A_S02_A_C05_current_rights_withhold_values_sources_and_aggregates(self):
        cases = {'scope_missing': eligibility(credential={'provider': 'instagram', 'scopes': ['instagram_business_basic'], 'revoked': False}),
                 'capability_not_direct': eligibility(capability={'level': 'Unsupported', 'evidence': 'Disconnected'}),
                 'credential_revoked': eligibility(credential={'provider': 'instagram', 'scopes': SCOPES, 'revoked': True})}
        for reason, rights in cases.items():
            with self.subTest(reason=reason):
                p = self.project(rights)
                self.assertTrue(all(e['value'] is None and e['sourceRef'] is None and e['observationId'] is None and e['accessState'] == 'not_authorized' for e in p['nativeResults']))
                self.assertTrue(all(reason in e['accessReasons'] for e in p['nativeResults']))
                self.assertEqual((p['groups'], p['qualification']), ([], 'not_comparable'))
        self.state['phase2']['channels'][0]['expiresAt'] = NOW - 1
        p = self.project()
        self.assertTrue(all(e['reason'] == 'expired' and e['value'] is None for e in p['nativeResults']))
        self.state['phase2']['channels'][0].update(expiresAt=NOW + DAY, revoked=True)
        self.assertTrue(all(e['accessState'] == 'revoked' for e in self.project()['nativeResults']))

    def test_trend_lineage_publication_is_excluded_fail_closed(self):
        self.state['phase2']['jobs'][0]['manifest']['trendLineage'] = [{'receiptId': 'r'}]
        e = self.result(self.project(), '0')
        self.assertEqual((e['reason'], e['value'], e['observationId']), ('trend_lineage_out_of_scope', None, None))


class Snapshot(unittest.TestCase):
    def setUp(self):
        self.state, self.rows, self.scope = fixture()
        reach(self.rows, '1').update(value=None, availability='unavailable')
        rights = eligibility()
        context = review.resolve_review_context('workspace', self.scope, self.state, NOW, rights_epoch=OE.rights_epoch(rights))
        self.projection = review.project_review(self.state, context, self.rows, rights, NOW)
        self.projection['takeaways'] = review.review_takeaways(self.projection, self.state, NOW)
        self.snapshot = review.build_review_snapshot(self.projection, self.state, ['=SUM(A1)', '繁體註記,含逗號'], 'owner', SHA, NOW)

    def test_A_D13_every_rendering_comes_from_one_frozen_payload(self):
        s = self.snapshot
        frozen = copy.deepcopy(s)
        self.assertEqual(s['payloadDigest'], digest({k: v for k, v in s.items() if k != 'payloadDigest'}))
        outputs = {f: review.format_snapshot(s, f) for f in ('markdown', 'csv', 'pdf')}
        self.assertEqual(s, frozen)
        for name, out in outputs.items():
            with self.subTest(format=name):
                self.assertEqual((out['snapshotId'], out['payloadDigest'], out['inputDigest']), (s['snapshotId'], s['payloadDigest'], s['inputDigest']))
                for needle in (s['snapshotId'], s['payloadDigest'], s['inputDigest'], s['qualification'], '繁體註記'):
                    self.assertIn(needle, out['content'])
        rows = list(csv.DictReader(io.StringIO(outputs['csv']['content'])))
        screen = {e['publicationBinding']['jobId']: e for e in s['nativeResults']}   # the payload the screen renders
        self.assertEqual(len(rows), len(screen))
        for row in rows:
            e = screen[row['jobId']]
            self.assertEqual(row['value'], 'null' if e['value'] is None else str(e['value']))
            self.assertEqual((row['valueState'], row['reason'] or None, row['windowQualification']), (e['valueState'], e['reason'], e['windowQualification']))
            self.assertEqual(row['payloadDigest'], s['payloadDigest'])
        self.assertEqual(next(r for r in rows if r['jobId'] == '1')['value'], 'null')
        self.assertEqual(next(r for r in rows if r['jobId'] == '0')['value'], '0.0')
        self.assertTrue(rows[0]['humanNotes'].startswith("'="))                # spreadsheet formula injection is neutralised
        self.assertIn('null · missing · missing_reading', outputs['markdown']['content'])
        self.assertNotIn('access_token', outputs['markdown']['content'] + outputs['csv']['content'] + outputs['pdf']['content'])

    def test_snapshot_versions_are_immutable_and_require_a_source_sha(self):
        b = review.build_review_snapshot(self.projection, self.state, ['New note'], 'owner', SHA, NOW + 1, previous=self.snapshot)
        self.assertEqual((b['version'], b['supersedes']), (2, f"{self.snapshot['snapshotId']}@v1"))
        self.assertNotEqual(b['payloadDigest'], self.snapshot['payloadDigest'])
        self.assertEqual(self.snapshot['humanNotes'], ['=SUM(A1)', '繁體註記,含逗號'])
        with self.assertRaises(AlphaError):
            review.build_review_snapshot(self.projection, self.state, [], 'owner', None, NOW)

    def test_generic_workspace_presentation_never_contains_private_review_storage(self):
        from postriff_phase2.hosted import HostedPhase2Commands
        commands = HostedPhase2Commands.__new__(HostedPhase2Commands)
        commands.engine = SimpleNamespace(_present=lambda state, revision: {'state': copy.deepcopy(state), 'revision': revision})
        state = {'coworker': {'review': {'snapshots': [self.snapshot]}, 'growthLoop': {'experiments': []}}}
        from unittest.mock import patch
        with patch('postriff_phase2.hosted.brand_brain.projection', return_value={}):
            shown = commands.present(state, 3)
        self.assertNotIn('review', shown['state']['coworker'])
        self.assertIn('review', state['coworker'])


class Eligibility(unittest.TestCase):
    def test_A_C05_projection_reports_each_axis_and_minimal_repair(self):
        ok = eligibility()['own']
        self.assertEqual((ok['usableNow'], ok['userGrant'], ok['platformApproval'], ok['repairAction']), (True, 'valid', 'unknown', 'none'))
        self.assertEqual(ok['unverifiedAxes'], ['platformApproval'])
        cases = [({'credential': {'provider': 'instagram', 'scopes': ['instagram_business_basic'], 'revoked': False}}, 'downgraded', 'scope_missing', 'reconnect'),
                 ({'credential': None}, 'missing', 'credential_missing', 'reconnect'),
                 ({'credential': {'provider': 'threads', 'scopes': SCOPES, 'revoked': False}}, 'missing', 'credential_provider_mismatch', 'reconnect'),
                 ({'account_deletion': True}, 'revoked', 'account_deletion', 'await_review'),
                 ({'capability': None}, 'valid', 'capability_not_direct', 'await_review'),
                 ({'channel': None}, 'missing', 'account_not_in_workspace', 'select_account')]
        for overrides, grant, reason, repair in cases:
            with self.subTest(reason=reason):
                p = eligibility(**overrides)['own']
                self.assertEqual((p['usableNow'], p['userGrant'], p['repairAction']), (False, grant, repair))
                self.assertIn(reason, p['blockedReasons'])
        unsupported = OE.analytics_read('workspace', 'li', {'id': 'li', 'platform': 'LinkedIn'}, {'level': 'Direct'},
                                        {'provider': 'linkedin', 'scopes': [], 'revoked': False}, account_deletion=False, now=NOW)
        self.assertEqual((unsupported['engineering'], unsupported['usableNow']), ('absent', False))
        self.assertIn('operation_not_supported', unsupported['blockedReasons'])

    def test_rights_epoch_changes_with_rights_not_with_new_readings(self):
        base = OE.rights_epoch(eligibility())
        self.assertEqual(base, OE.rights_epoch(eligibility(latest_reading={'id': 'newer', 'observedAt': NOW})))
        self.assertNotEqual(base, OE.rights_epoch(eligibility(credential={'provider': 'instagram', 'scopes': SCOPES[:1], 'revoked': False})))
        stale = eligibility(latest_reading={'id': 'old', 'observedAt': NOW - 30 * DAY})['own']
        self.assertEqual((stale['dataFreshness'], stale['usableNow']), ('stale', True))
        none = eligibility(latest_reading=None)['own']
        self.assertEqual((none['nativeVerification'], none['unverifiedAxes']), ('not_run', ['platformApproval', 'nativeVerification']))


class WindowTruth(unittest.TestCase):
    """The scheduler half of the 24h window (PR #142 subset): a late read is closed, never stored under 24h."""
    def scheduler(self, now, calls):
        class OAuth:
            providers = {"threads": ThreadsProvider("synthetic-client", "synthetic-secret", production_reviewed=True)}
            def token_for_worker(self, ws, conn):
                return {"accessToken": "t", "provider": "threads", "scopes": sorted(M.NATIVE_ANALYTICS_SCOPES["threads"])}
        def transport(method, url, **kw):
            calls.append(url)
            return {"status": 200, "body": {"data": []}}
        s = M.MetricScheduler(None, OAuth(), transport=transport, workspace_allowlist={"w"}, clock=lambda: now)
        s._eligible = lambda row: "read"
        return s

    def test_late_read_is_closed_without_a_provider_call(self):
        anchor = NOW - 30 * 3600
        row = {"workspaceId": "w", "connectionId": "c", "provider": "threads", "postId": "p", "offset": "24h", "anchorAt": anchor}
        calls = []
        outcome = self.scheduler(NOW, calls).read(row, {})
        self.assertEqual((outcome["state"], outcome["failure"], outcome["providerRead"], calls), ("unavailable", "window_missed", False, []))
        on_time = self.scheduler(anchor + 86400 + 600, calls).read(row, {})
        self.assertEqual((on_time["state"], on_time["readAt"]), ("done", anchor + 86400 + 600))
        self.assertEqual(len(calls), 1)
        self.assertEqual(M.window_deadline("24h", anchor), anchor + 86400 + 3 * 3600)
        self.assertIsNone(M.window_deadline("backfill", anchor))
        self.assertFalse(M.window_missed({"offset": "backfill", "anchorAt": anchor}, NOW))


class DraftLink(unittest.TestCase):
    """A-U02/A-U03 pure half: attaching an existing versioned draft never creates review, approval or jobs."""
    def setUp(self):
        self.state = {'variants': [{'id': 'v1', 'revision': 2, 'platform': 'Instagram', 'language': 'en', 'text': 'Draft', 'needsReview': True}],
                      'phase2': {'jobs': [], 'reviews': []}}
        self.experiment = {'id': 'ge_x', 'status': 'preparing', 'cohort': {'provider': 'instagram', 'language': 'en'},
                           'generatedVariantIds': [], 'reviewSnapshot': {'snapshotId': 'rs_1', 'version': 1, 'payloadDigest': 'p'}, 'takeawayId': 't'}

    def test_attach_is_explicit_bounded_idempotent_and_side_effect_free(self):
        before = copy.deepcopy(self.state)
        binding = growth_loop.attach_draft(self.state, self.experiment, {'variantId': 'v1', 'variantRevision': 2}, 'owner', NOW)
        self.assertEqual((binding['revision'], binding['reviewSnapshot']['snapshotId'], binding['takeawayId']), (2, 'rs_1', 't'))
        self.assertIs(growth_loop.attach_draft(self.state, self.experiment, {'variantId': 'v1', 'variantRevision': 2}, 'owner', NOW), binding)
        self.assertEqual(self.experiment['generatedVariantIds'], ['v1'])
        self.assertEqual(self.state, before)                                   # no variant, review, approval or job is written
        self.assertEqual(growth_loop.draft_state(self.state, self.experiment)[0]['state'], 'current')
        self.state['variants'][0].update(revision=3, text='Edited draft')
        self.assertEqual(growth_loop.draft_state(self.state, self.experiment)[0]['state'], 'revision_changed')

    def test_attach_refuses_wrong_stage_revision_platform_and_rejected_drafts(self):
        attempts = [({'status': 'proposed'}, {'variantId': 'v1', 'variantRevision': 2}, 409),
                    ({}, {'variantId': 'v1', 'variantRevision': 1}, 409),
                    ({}, {'variantId': 'missing', 'variantRevision': 2}, 404),
                    ({'cohort': {'provider': 'threads', 'language': 'en'}}, {'variantId': 'v1', 'variantRevision': 2}, 409)]
        for change, payload, status in attempts:
            with self.subTest(change=change, payload=payload):
                experiment = {**copy.deepcopy(self.experiment), **change}
                with self.assertRaises(AlphaError) as raised:
                    growth_loop.attach_draft(self.state, experiment, payload, 'owner', NOW)
                self.assertEqual(raised.exception.status, status)
        self.state['variants'][0]['rejected'] = True
        with self.assertRaises(AlphaError):
            growth_loop.attach_draft(self.state, self.experiment, {'variantId': 'v1', 'variantRevision': 2}, 'owner', NOW)


if __name__ == '__main__':
    unittest.main()
