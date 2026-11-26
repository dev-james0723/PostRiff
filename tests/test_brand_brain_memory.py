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


# --- Scope-aware rendering (brand intelligence spec 5.6) ----------------------------------------------------------------
def golden_state():
    """An approved profile with no scoped or historical trait, learned preferences, boundaries and a Genome whose
    statements all belong to the request's cohort. Its rendering was captured at 0ebc002b, before traits had a scope."""
    import hashlib  # noqa: F401  (kept beside the fixture that the digests below were taken from)
    from postriff_phase2.contracts import digest
    grants = [{'purpose': 'analysis', 'route': 'local-rules'}, {'purpose': 'generation', 'route': 'local-cli'}]
    state = {
        'speaker': {'label': 'Studio', 'activeRevision': 2, 'revisions': [
            {'revision': 1, 'profile': {'tone': 'old', 'observations': ['Superseded.']}},
            {'revision': 2, 'approvedAt': '2026-03-04T05:06:07Z', 'reason': 'Explicit provisional-profile approval',
             'profile': {'tone': 'warm, exact', 'observations': ['Short paragraphs.', 'Opens with a plain statement.', 'Keeps one idea to a line.'],
                         'unknowns': ['Samples show writing form only.'], 'writingExample': '',
                         'dimensions': [{'id': 'paragraph_length', 'observation': 'Short paragraphs.', 'evidenceLevel': 'supported', 'decision': 'accept'},
                                        {'id': 'openings', 'observation': 'Opens with a plain statement.', 'evidenceLevel': 'user-defined', 'userAuthored': True, 'decision': 'edit'},
                                        {'id': 'humor', 'observation': 'Humor is not explicitly marked.', 'evidenceLevel': 'insufficient'}],
                         'userGuidance': ['Keeps one idea to a line.']}}]},
        'brandHub': {'mode': 'personal', 'purpose': 'Teach', 'audience': 'Readers', 'subject': 'Craft', 'speaker': 'Studio', 'layers': ['personal']},
        'you': {'identitySentence': 'A small studio.'},
        'sources': [{'id': 'sample', 'kind': 'voice_sample', 'active': True, 'selected': True, 'revision': 1, 'contentHash': 'hash', 'text': 'raw text',
                     'purposeGrants': ['analysis', 'generation'], 'useGrants': grants}],
        'growthConsent': {'routes': ['genome']},
        'learning': {'enabled': True, 'revision': 3, 'active': [
            {'id': 'pref1', 'status': 'active', 'type': 'writing_preference', 'ruleKey': 'other', 'polarity': 'do', 'statement': 'Use short lines.', 'scope': {}, 'evidenceState': 'user_confirmed', 'since': '2026-01-02T00:00:00Z'},
            {'id': 'pref2', 'status': 'active', 'type': 'writing_preference', 'ruleKey': 'hashtags', 'polarity': 'avoid', 'statement': 'No hashtags.', 'scope': {'platform': 'LinkedIn'}, 'evidenceState': 'observed_in_approved_example', 'evidenceSummary': 'from 4 edits', 'since': '2026-02-03T00:00:00Z'}]},
        'profile': {'fields': [{'id': 'boundary-public', 'section': 'boundaries', 'label': 'Clients', 'value': 'Never name clients.', 'privacy': 'public'},
                               {'id': 'boundary-private', 'section': 'boundaries', 'label': 'Family', 'value': 'No family details.', 'privacy': 'private'}]},
    }
    state['brandHub']['genome'] = {'status': 'approved', 'evidenceBindings': [{'id': 'sample', 'revision': 1, 'grantsDigest': digest(grants)}], 'outcomeBindings': [],
        'consentDigest': digest(state['growthConsent']),
        'statements': [{'id': str(i), 'text': f'Lesson {i} appears among your stronger observed posts.', 'grade': 'supported' if i % 3 else 'limited',
                        'cohort': {'platform': 'LinkedIn', 'connectionId': 'unknown', 'format': 'text', 'language': 'en', 'timeBucket': 'unknown'}} for i in range(9)]}
    return state


GOLDEN_VOICE = """# Voice

Revision 2 · approved 2026-03-04 05:06 UTC · Explicit provisional-profile approval

Tone: warm, exact

## Observations
How to handle what you supply. A trait is never a reason to add a detail, habit or admission you did not supply.
- Short paragraphs.
- Opens with a plain statement.
- Keeps one idea to a line.

## Learned from how you edit (style rev 3)
Form only. The facts and what you ask for in the message win over these.
- [All channels] Use short lines. — remembered · 2026-01-02
- [LinkedIn · all languages] No hashtags. — from 4 edits · 2026-02-03

## Writing example
(none supplied)

## Unknowns kept explicit
- Samples show writing form only.

## Approved Creator Genome
Observed writing preferences, never new personal facts or guaranteed outcomes.
- Lesson 1 appears among your stronger observed posts.
- Lesson 2 appears among your stronger observed posts.
- Lesson 4 appears among your stronger observed posts.
- Lesson 5 appears among your stronger observed posts.
- Lesson 7 appears among your stronger observed posts.
- Lesson 8 appears among your stronger observed posts."""
LINKEDIN = [{'platform': 'LinkedIn', 'language': 'en'}]


def files_digest(files):
    import hashlib, json
    return hashlib.sha256(json.dumps([[f['name'], f['purpose'], f['source'], f['body'], f['editHref']] for f in files], ensure_ascii=False).encode()).hexdigest()


class GoldenUnscopedRender(unittest.TestCase):
    """An unscoped profile renders byte for byte as it did before traits could carry a scope."""

    def test_voice_file_is_byte_identical_with_and_without_destinations(self):
        state = golden_state()
        for files in (memory.render_files(state), memory.render_files(state, destinations=LINKEDIN),
                      memory.render_files(state, shareable=memory.CLOUD_SHAREABLE, destinations=LINKEDIN, content_type_id='post')):
            self.assertEqual(next(f['body'] for f in files if f['name'] == 'VOICE.md'), GOLDEN_VOICE)

    def test_all_five_files_and_the_writer_bytes_are_unchanged(self):
        state = golden_state()
        self.assertEqual(files_digest(memory.render_files(state)), '2aaa32e2720783682e00ad8995dd8e4d7551212bb4397469629787b27ef3fdf7')
        self.assertEqual(files_digest(memory.render_files(state, destinations=LINKEDIN)), '2aaa32e2720783682e00ad8995dd8e4d7551212bb4397469629787b27ef3fdf7')
        self.assertEqual(files_digest(memory.render_files(state, shareable=memory.CLOUD_SHAREABLE, destinations=LINKEDIN, content_type_id='post')),
                         '03b5c45bde906e2a85fd7841af940fcd2e4364092f1c2d6cffdafd377de0f429')
        _, receipt = memory.prepare_writer(state, 'local', 'local-cli', destinations=LINKEDIN)
        self.assertEqual(receipt['memoryContextDigest'], 'fa594d1cd57d4efa700f50bc904a97c89eaab3c840161ced05a2b7624a384a0e')
        _, neutral = memory.prepare_writer(state, 'local', 'local-cli', destinations=LINKEDIN, voice_mode='neutral')
        self.assertEqual(neutral['memoryContextDigest'], '531d2972e145269458f33f7c76aeeca9b30845f733fce7f1d77f69af9e41d472')


# --- Which traits and Genome lessons reach which destination (CTX-2, PRO-5) ---------------------------------------------
INSTAGRAM = [{'platform': 'Instagram', 'language': 'en'}]
LINKEDIN_ONLY = {'id': 'emoji:linkedin', 'dimension': 'emoji', 'observation': 'Rarely uses emoji (2 of 40 posts).', 'evidenceLevel': 'supported', 'basis': 'measured',
                 'status': 'active', 'scope': {'platforms': ['linkedin']}}


def voice_md(state, destinations=None):
    return next(f['body'] for f in memory.render_files(state, destinations=destinations) if f['name'] == 'VOICE.md')


def scoped_state(*traits, channels=()):
    state = golden_state()
    state['speaker']['revisions'][1]['profile']['dimensions'].extend(copy.deepcopy(list(traits)))
    if channels:
        state['phase2'] = {'channels': [dict(channel) for channel in channels]}
    return state


def lessons(body):
    """The Genome lessons a VOICE.md carries, in order."""
    parts = body.split('## Approved Creator Genome')
    return [line[2:].split(' appears')[0] for line in parts[1].splitlines() if line.startswith('- ')] if len(parts) > 1 else []


class ScopeAwareRender(unittest.TestCase):
    def test_a_platform_scoped_trait_reaches_only_a_matching_destination(self):
        state = scoped_state(LINKEDIN_ONLY)
        line = '- [LinkedIn] Rarely uses emoji (2 of 40 posts).'
        self.assertEqual(voice_md(state, LINKEDIN), GOLDEN_VOICE.replace('- Keeps one idea to a line.\n', '- Keeps one idea to a line.\n' + line + '\n'))
        self.assertIn(line, voice_md(state, INSTAGRAM + LINKEDIN).splitlines(), 'a request for several destinations carries it, labelled')
        for destinations in (None, INSTAGRAM, [{'platform': 'Threads', 'language': 'en'}]):
            self.assertNotIn('Rarely uses emoji', voice_md(state, destinations))
        self.assertEqual(voice_md(state), GOLDEN_VOICE, 'without a destination nothing scoped renders, and the rest is unchanged')

    def test_a_language_scoped_trait_follows_the_draft_language(self):
        state = scoped_state({**LINKEDIN_ONLY, 'id': 'emoji:yue', 'observation': 'Uses emoji in most posts (30 of 34).', 'scope': {'languages': ['yue']}})
        self.assertIn('- [廣東話（香港）] Uses emoji in most posts (30 of 34).', voice_md(state, [{'platform': 'Instagram', 'language': 'yue-Hant-HK'}]).splitlines())
        for language in ('en', 'zh-Hant-HK', 'zh-Hans'):
            self.assertNotIn('Uses emoji in most posts', voice_md(state, [{'platform': 'Instagram', 'language': language}]))

    def test_old_style_rejected_and_unsettled_traits_never_render(self):
        old = {'id': 'openings-old', 'dimension': 'openings', 'observation': 'Opens with a rhetorical question.', 'evidenceLevel': 'supported', 'status': 'historical'}
        old_scoped = {**LINKEDIN_ONLY, 'id': 'emoji:linkedin-old', 'observation': 'Uses many emoji on that channel.', 'status': 'historical'}
        rejected = {**LINKEDIN_ONLY, 'id': 'hashtags:linkedin', 'observation': 'Ends with a block of hashtags.', 'decision': 'reject'}
        unsettled = [{**LINKEDIN_ONLY, 'id': f'emoji:{level}', 'observation': f'Habit marked {level}.', 'evidenceLevel': level} for level in ('conflicting', 'insufficient')]
        state = scoped_state(old, old_scoped, rejected, *unsettled)
        # A profile saved by older code may still list an old-style trait among its plain observations.
        state['speaker']['revisions'][1]['profile']['observations'].append('Opens with a rhetorical question.')
        for destinations in (None, LINKEDIN, INSTAGRAM):
            body = voice_md(state, destinations)
            for text in ('rhetorical question', 'many emoji', 'block of hashtags', 'Habit marked'):
                self.assertNotIn(text, body)
        self.assertEqual(voice_md(state), GOLDEN_VOICE)
        self.assertEqual(voice_md(state, LINKEDIN), voice_md(golden_state(), LINKEDIN))

    def test_a_separate_accounts_traits_reach_only_drafts_for_that_account(self):
        side = {'id': 'tone.ai@separate-threads-side', 'dimension': 'tone', 'observation': 'Dry and brief.', 'evidenceLevel': 'supported', 'basis': 'model', 'status': 'active',
                'group': 'separate:threads:side-id', 'scope': {'accounts': ['side-id'], 'platforms': ['threads']}}
        channels = ({'id': 'conn-side', 'platform': 'Threads', 'account': '@side.handle', 'providerAccountId': 'side-id'},
                    {'id': 'conn-main', 'platform': 'Threads', 'account': '@main.handle', 'providerAccountId': 'main-id'})
        state = scoped_state(side, channels=channels)

        def threads(**account):
            return {'platform': 'Threads', 'language': 'en', **account}
        for destinations in ([threads(channelId='conn-side')], [threads(account='@side.handle')]):
            body = voice_md(state, destinations)
            self.assertIn('- [Threads · one account] Dry and brief.', body.splitlines())
            for leaked in ('side-id', 'side.handle', 'conn-side'):
                self.assertNotIn(leaked, body, 'an account is never named in VOICE.md')
        for destinations in (None, [threads()], [threads(channelId='conn-main')], [threads(channelId='conn-side'), {'platform': 'LinkedIn', 'language': 'en'}],
                             [{'platform': 'LinkedIn', 'language': 'en', 'channelId': 'conn-side'}]):
            self.assertNotIn('Dry and brief.', voice_md(state, destinations), destinations)

    def test_genome_lessons_follow_the_destination_cohort(self):
        state = golden_state()
        statements = state['brandHub']['genome']['statements']
        statements[1]['cohort']['platform'] = 'Threads'
        statements[2]['cohort']['connectionId'] = 'conn-a'
        statements[4]['cohort']['language'] = 'zh-Hant'
        statements[5]['cohort']['platform'] = 'unknown'
        self.assertEqual(lessons(voice_md(state)), ['Lesson 1', 'Lesson 2', 'Lesson 4', 'Lesson 5', 'Lesson 7', 'Lesson 8'])
        self.assertEqual(lessons(voice_md(state, LINKEDIN)), ['Lesson 2', 'Lesson 5', 'Lesson 7', 'Lesson 8'])
        self.assertEqual(lessons(voice_md(state, [{'platform': 'LinkedIn', 'language': 'en', 'channelId': 'conn-b'}])), ['Lesson 5', 'Lesson 7', 'Lesson 8'])
        self.assertEqual(lessons(voice_md(state, [{'platform': 'LinkedIn', 'language': 'en', 'channelId': 'conn-a'}])), ['Lesson 2', 'Lesson 5', 'Lesson 7', 'Lesson 8'])
        self.assertEqual(lessons(voice_md(state, [{'platform': 'Threads', 'language': 'en'}])), ['Lesson 1', 'Lesson 5'])
        self.assertEqual(lessons(voice_md(state, [{'platform': 'LinkedIn', 'language': 'zh-Hant-HK'}])), ['Lesson 4'])
        self.assertEqual(lessons(voice_md(state, INSTAGRAM)), ['Lesson 5'])

    def test_the_twelve_newest_supported_lessons_are_rendered(self):
        state = golden_state()
        genome = state['brandHub']['genome']
        cohort = genome['statements'][0]['cohort']
        genome['statements'] = [{'id': str(index), 'text': f'Lesson {index:02d} appears among your stronger observed posts.', 'grade': 'supported', 'cohort': dict(cohort)}
                                for index in range(15)] + [{'id': 'late', 'text': 'A limited lesson appears here.', 'grade': 'limited', 'cohort': dict(cohort)}]
        for destinations in (None, LINKEDIN):
            self.assertEqual(lessons(voice_md(state, destinations)), [f'Lesson {index:02d}' for index in range(3, 15)])

    def test_the_writer_receipt_names_the_traits_and_lessons_that_reached_the_writer(self):
        instagram_only = {**LINKEDIN_ONLY, 'id': 'emoji:instagram', 'observation': 'Uses emoji in most posts (38 of 40).', 'scope': {'platforms': ['instagram']}}
        state = scoped_state(LINKEDIN_ONLY, instagram_only)
        shared, receipt = memory.prepare_writer(state, 'local', 'local-cli', destinations=LINKEDIN)
        self.assertEqual((receipt['traitsIncluded'], receipt['genomeIncluded']), (['paragraph_length', 'openings', 'emoji:linkedin'], ['1', '2', '4', '5', '7', '8']))
        _, other = memory.prepare_writer(state, 'local', 'local-cli', destinations=INSTAGRAM)
        self.assertEqual((other['traitsIncluded'], other['genomeIncluded']), (['paragraph_length', 'openings', 'emoji:instagram'], []))
        _, neutral = memory.prepare_writer(state, 'local', 'local-cli', destinations=LINKEDIN, voice_mode='neutral')
        self.assertEqual((neutral['traitsIncluded'], neutral['genomeIncluded']), ([], []))
        # Only what survived the writer's byte budget is named.
        joined = '\n\n'.join(f"--- {f['name']} ---\n{f['body']}" for f in shared['files'])
        _, cut = memory.prepare_writer(state, 'local', 'local-cli', destinations=LINKEDIN, max_bytes=len(joined[:joined.index('## Learned')].encode()))
        self.assertEqual((cut['traitsIncluded'], cut['genomeIncluded']), (['paragraph_length', 'openings', 'emoji:linkedin'], []))
        _, mid = memory.prepare_writer(state, 'local', 'local-cli', destinations=LINKEDIN, max_bytes=len(joined[:joined.index('- [LinkedIn]') + 12].encode()))
        self.assertEqual(mid['traitsIncluded'], ['paragraph_length', 'openings'])
        # The golden receipt's digests are unchanged by the new fields.
        _, golden = memory.prepare_writer(golden_state(), 'local', 'local-cli', destinations=LINKEDIN)
        self.assertEqual(golden['memoryContextDigest'], 'fa594d1cd57d4efa700f50bc904a97c89eaab3c840161ced05a2b7624a384a0e')
        self.assertEqual(golden['traitsIncluded'], ['paragraph_length', 'openings'])


if __name__ == '__main__': unittest.main()
