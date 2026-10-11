"""Brand Brain memory: actual request assembly, neutral and privacy boundaries, canonical edits."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from postriff_alpha.domain import AlphaError
from postriff_phase2 import memory


def workspace():
    return {'speaker': {'label': 'Studio', 'activeRevision': 3, 'revisions': [{'revision': 3, 'profile': {'tone': 'plain', 'observations': ['Short paragraphs.']}}]},
            'brandHub': {'audience': 'Readers'}, 'sources': [],
            'profile': {'fields': [{'id': f'boundary-{p}', 'section': 'boundaries', 'label': p, 'value': f'VALUE-{p}', **({'privacy': p} if p != 'unlabelled' else {})}
                                   for p in ('public', 'workspace_only', 'private', 'local_only', 'excluded', 'unlabelled')]}}


class MemoryReceipts(unittest.TestCase):
    def test_authored_profile_needs_explicit_mode_and_cloud_consent(self):
        state = workspace()
        self.assertTrue(memory.manual_profile_available(state, 'local'))
        self.assertFalse(memory.manual_profile_available(state, 'cloud'))
        state['memoryEgress'] = {'cloud': True}
        self.assertTrue(memory.manual_profile_available(state, 'cloud'))
        shared, receipt = memory.prepare_writer(state, 'cloud', 'cloud:test:model', voice_mode='personalized')
        self.assertIn('VOICE.md', receipt['filesIncluded'])
        self.assertEqual(receipt['effectiveVoiceMode'], 'approved')
        state['speaker']['activeRevision'] = None
        self.assertFalse(memory.manual_profile_available(state))

    def test_exactly_five_derived_files_and_three_candidates(self):
        self.assertEqual(tuple(f['name'] for f in memory.render_files(workspace())), memory.FILE_ORDER)
        self.assertEqual(memory.PROMPT_FILES, ('BOUNDARIES.md', 'IDENTITY.md', 'VOICE.md'))

    def test_cloud_denial_receipt_empty_not_candidate_file_list(self):
        shared, receipt = memory.prepare_writer(workspace(), 'cloud', 'cloud:test:model')
        self.assertEqual(shared['files'], [])
        self.assertEqual(receipt['filesIncluded'], [])
        self.assertEqual({i['reason'] for i in receipt['filesWithheld']}, {'cloud_memory_denied'})

    def test_neutral_override_cannot_receive_profile_or_tone_memory(self):
        shared, receipt = memory.prepare_writer(workspace(), 'local', 'local-cli', voice_mode='neutral')
        self.assertEqual(receipt['effectiveVoiceMode'], 'neutral')
        self.assertNotIn('VOICE.md', receipt['filesIncluded'])
        self.assertNotIn('Short paragraphs', str(shared['files']))
        self.assertIn('BOUNDARIES.md', receipt['filesIncluded'])

    def test_cloud_permission_filters_every_restricted_privacy(self):
        state = workspace(); state['memoryEgress'] = {'cloud': True}
        shared, receipt = memory.prepare_writer(state, 'cloud', 'cloud:test:model')
        self.assertEqual(receipt['withheldBoundaries'], 4)
        for privacy in ('private', 'local_only', 'excluded', 'unlabelled'):
            self.assertNotIn(f'VALUE-{privacy}', str(shared['files']))
        self.assertIn('VALUE-public', str(shared['files']))

    def test_budget_tracks_exact_unicode_tail_and_omissions(self):
        files = [{'name': 'BOUNDARIES.md', 'body': '漢字' * 30}, {'name': 'VOICE.md', 'body': 'voice'}]
        sent, fragments = memory.assemble(files, 39)
        joined = '\n\n'.join(f"--- {f['name']} ---\n{f['body']}" for f in sent)
        self.assertLessEqual(len(joined.encode()), 39)
        self.assertTrue(fragments[0]['truncated'])
        self.assertTrue(fragments[1]['withheld'])
        self.assertEqual(fragments[0]['bytesIncluded'], len(sent[0]['body'].encode()))
        self.assertEqual(fragments[0]['digest'], memory.fingerprint(sent[0]['body']))

    def test_header_only_voice_budget_does_not_claim_approved_style(self):
        state = workspace()
        candidates = memory.projection(state, 'local', voice_route='local-cli')['files']
        prefix = '\n\n'.join(f"--- {file['name']} ---\n{file['body']}" for file in candidates if file['name'] != 'VOICE.md')
        budget = len((prefix + '\n\n--- VOICE.md ---\n# Voice').encode())
        shared, receipt = memory.prepare_writer(state, 'local', 'local-cli', max_bytes=budget)
        self.assertEqual(shared['files'][-1]['body'], '# Voice')
        self.assertEqual(receipt['effectiveVoiceMode'], 'not_supplied')
        self.assertTrue(receipt['fragments'][-1]['truncated'])

    def test_zero_budget_reports_all_withheld(self):
        shared, receipt = memory.prepare_writer(workspace(), 'local', 'local-cli', max_bytes=0)
        self.assertEqual(shared['files'], [])
        self.assertEqual(len(receipt['filesWithheld']), 3)
        self.assertEqual(receipt['effectiveVoiceMode'], 'not_supplied')

    def test_receipt_has_no_raw_body_boundary_value_or_sample(self):
        _, receipt = memory.prepare_writer(workspace(), 'local', 'local-cli')
        self.assertNotIn('VALUE-private', str(receipt))
        self.assertNotIn('Short paragraphs', str(receipt))
        self.assertEqual(len(receipt['preferenceSetDigest']), 64)

    def test_preference_fingerprint_changes_independently_of_voice_revision(self):
        state = workspace()
        before = memory.snapshot(state)
        state['learning'] = {'enabled': True, 'revision': 1, 'active': [{'id': 'pref1', 'status': 'active', 'type': 'writing_preference', 'ruleKey': 'other', 'polarity': 'do', 'statement': 'Use short lines.', 'scope': {}, 'evidenceState': 'user_confirmed'}]}
        after = memory.snapshot(state)
        self.assertEqual(before['activeVoiceRevision'], after['activeVoiceRevision'])
        self.assertNotEqual(before['preferenceSetDigest'], after['preferenceSetDigest'])
        _, receipt = memory.prepare_writer(state, 'local', 'local-cli', max_bytes=20)
        self.assertEqual(receipt['preferencesIncludedDigest'], memory.fingerprint([]))

    def test_candidate_analysis_does_not_change_approved_render(self):
        state = workspace(); before = memory.snapshot(state)
        state['speaker']['provisional'] = {'tone': 'CHANGED', 'status': 'proposed'}
        self.assertEqual(memory.snapshot(state), before)

    def test_concurrent_identity_or_boundary_change_rejects_run_apply(self):
        for mutation in (lambda state: state['brandHub'].update(audience='Changed'), lambda state: state['profile']['fields'][0].update(value='Changed')):
            state = workspace(); _, receipt = memory.prepare_writer(state, 'local', 'local-cli')
            mutation(state)
            with self.assertRaises(AlphaError) as caught:
                memory.validate_receipt(state, receipt)
            self.assertEqual(caught.exception.status, 409)

    def test_receipt_revalidates_cloud_revocation(self):
        state = workspace(); state['memoryEgress'] = {'cloud': True}
        _, receipt = memory.prepare_writer(state, 'cloud', 'cloud:test:model')
        state['memoryEgress']['cloud'] = False
        with self.assertRaises(AlphaError): memory.validate_receipt(state, receipt)

    def test_evidence_grant_cannot_be_overridden_by_memory_grant(self):
        state = workspace(); state['memoryEgress'] = {'cloud': True}
        state['sources'] = [{'id': 'sample', 'kind': 'voice_sample', 'active': True, 'selected': True, 'revision': 1, 'contentHash': 'hash', 'text': 'DO NOT LEAK RAW SAMPLE', 'purposeGrants': ['analysis'], 'useGrants': [{'purpose': 'analysis', 'route': 'local-rules'}]}]
        state['speaker']['revisions'][0]['profile'].update(evidenceSourceIds=['sample'], writingExample='DO NOT LEAK RAW SAMPLE')
        shared, receipt = memory.prepare_writer(state, 'cloud', 'cloud:test:model')
        self.assertNotIn('Short paragraphs', str(shared['files']))
        self.assertNotIn('DO NOT LEAK RAW SAMPLE', str(shared))
        self.assertEqual(receipt['effectiveVoiceMode'], 'not_supplied')

    def test_canonical_identity_edit_appears_in_same_render(self):
        state = workspace()
        memory.apply_memory_action(state, 'brand_brain_identity', {'confirmed': True, 'fields': {'identitySentence': 'A ceramics studio', 'audience': 'Makers'}}, 'owner', 1)
        rendered = str(memory.render_files(state))
        self.assertIn('A ceramics studio', rendered); self.assertIn('Makers', rendered)
        self.assertNotIn('memoryFiles', state)
        self.assertEqual(state['you']['artFieldIds'], [])
        self.assertIsNone(state['you']['artwork'])
        state['you']['artwork'] = {'state': 'local_procedural', 'variant': 2}
        memory.apply_memory_action(state, 'brand_brain_identity', {'confirmed': True, 'fields': {'identitySentence': 'Updated studio'}}, 'owner', 2)
        self.assertEqual(state['you']['artwork']['variant'], 2)

    def test_boundary_edit_preserves_immutable_revision_and_privacy(self):
        state = workspace(); state['speaker']['revisions'][0]['profile']['fields'] = [{'id': 'old', 'section': 'boundaries', 'value': 'OLD', 'privacy': 'public'}]
        old = copy.deepcopy(state['speaker']['revisions'])
        memory.apply_memory_action(state, 'brand_brain_boundaries', {'confirmed': True, 'fields': [{'id': 'old', 'label': 'Private rule', 'value': 'NEW PRIVATE', 'privacy': 'private'}]}, 'owner', 1)
        self.assertEqual(state['speaker']['revisions'], old)
        self.assertEqual(next(f for f in memory.boundary_fields(state) if f['id'] == 'old')['value'], 'NEW PRIVATE')
        state['memoryEgress'] = {'cloud': True}
        self.assertNotIn('NEW PRIVATE', str(memory.projection(state, 'cloud')))

    def test_canonical_edits_require_confirmation_and_valid_privacy(self):
        with self.assertRaises(AlphaError): memory.apply_memory_action(workspace(), 'brand_brain_identity', {'fields': {'audience': 'x'}}, 'owner', 1)
        with self.assertRaises(AlphaError): memory.apply_memory_action(workspace(), 'brand_brain_boundaries', {'confirmed': True, 'fields': [{'id': 'a', 'label': 'a', 'value': 'b', 'privacy': 'unknown'}]}, 'owner', 1)

    def test_nonowner_diagnostic_redaction_preserves_source_route_denial(self):
        state = workspace()
        state['sources'] = [{'id': 'sample', 'kind': 'voice_sample', 'active': True, 'selected': True, 'revision': 1, 'contentHash': 'hash', 'text': 'RAW-EXAMPLE', 'purposeGrants': ['analysis'], 'useGrants': [{'purpose': 'analysis', 'route': 'local-rules'}]}]
        state['speaker']['revisions'][0]['profile'].update(evidenceSourceIds=['sample'], writingExample='RAW-EXAMPLE')
        shown = memory.diagnostic_projection(state, 'local', owner=False, voice_route='local-cli')
        self.assertNotIn('RAW-EXAMPLE', str(shown))
        self.assertNotIn('VALUE-private', str(shown))
        self.assertNotIn('Short paragraphs.', str(shown))
        self.assertTrue(shown['restrictedViewer'])

    def test_creator_genome_cannot_bypass_generation_route_permission(self):
        from postriff_phase2.contracts import digest
        state = workspace(); state['memoryEgress'] = {'cloud': True}; state['growthConsent'] = {'routes': ['genome']}
        grants = [{'purpose': 'analysis', 'route': 'local-rules'}]
        state['sources'] = [{'id': 'sample', 'kind': 'voice_sample', 'active': True, 'selected': True, 'revision': 1, 'contentHash': 'hash', 'text': 'raw text', 'purposeGrants': ['analysis'], 'useGrants': grants}]
        state['brandHub']['genome'] = {'status': 'approved', 'evidenceBindings': [{'id': 'sample', 'revision': 1, 'grantsDigest': digest(grants)}], 'outcomeBindings': [], 'consentDigest': digest(state['growthConsent']), 'statements': [{'text': 'GENOME-STYLE-RESTRICTED', 'grade': 'supported'}]}
        self.assertIn('GENOME-STYLE-RESTRICTED', str(memory.render_files(state)))
        self.assertNotIn('GENOME-STYLE-RESTRICTED', str(memory.projection(state, 'cloud', voice_route='cloud:test:model')))
        self.assertNotIn('GENOME-STYLE-RESTRICTED', str(memory.projection(state, 'local', voice_route='local-cli')))

    def test_bounded_request_matches_cloud_formatter_bytes(self):
        from postriff_phase2.model_runtime import ServerModelRuntime, MAX_MEMORY_BYTES
        state = workspace(); state['memoryEgress'] = {'cloud': True}
        state['speaker']['revisions'][0]['profile']['observations'] = ['漢字' * 20000]
        shared, receipt = memory.prepare_writer(state, 'cloud', 'cloud:test:model', max_bytes=MAX_MEMORY_BYTES)
        expected = '\n\n'.join(f"--- {f['name']} ---\n{f['body']}" for f in shared['files'])
        system = ServerModelRuntime._system_prompt({'memory': shared['files']})
        self.assertTrue(system.endswith(expected))
        self.assertLessEqual(len(expected.encode()), MAX_MEMORY_BYTES)
        self.assertTrue(any(f['truncated'] for f in receipt['fragments']))
        for fragment in receipt['fragments']:
            if fragment['bytesIncluded']:
                self.assertEqual(fragment['digest'], memory.fingerprint(next(f['body'] for f in shared['files'] if f['name'] == fragment['name'])))

    def test_post_doctor_context_invalidates_canonical_boundary_edits(self):
        from postriff_phase2.growth.advice_context import fingerprint
        state = workspace()
        before = fingerprint(state)
        memory.apply_memory_action(state, 'brand_brain_boundaries', {'confirmed': True, 'fields': [{'id': 'boundary-public', 'label': 'Rule', 'value': 'VALUE-public', 'privacy': 'private'}]}, 'owner', 2)
        self.assertNotEqual(fingerprint(state), before)
        # Canonical boundary policy changes invalidate even when voice history stays immutable.
        self.assertEqual(state['speaker']['activeRevision'], 3)

    def test_snapshot_is_reproducible_and_matches_each_file(self):
        state = workspace(); before = memory.snapshot(state, 8)
        self.assertEqual(before, memory.snapshot(copy.deepcopy(state), 8))
        for file in memory.render_files(state): self.assertEqual(before['fileDigests'][file['name']], memory.fingerprint(file['body']))

if __name__ == '__main__': unittest.main()
