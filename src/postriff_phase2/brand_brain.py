"""Brand Brain commands over the canonical speaker/source state, never a memory store.

Hosted repository owns membership, workspace fencing and the transaction. Approved
profiles use the existing voice activation/invalidation path. No command here calls
an AI provider; the explicit quoted route delegates to HostedVoiceAnalysis.
"""
from __future__ import annotations

import copy
import json
import re

from postriff_alpha.domain import AlphaError
from .contracts import digest
from . import voice_analysis, voice_sources

ACTIONS = frozenset({'brand_brain_import', 'brand_brain_analyze', 'brand_brain_review',
                     'brand_brain_preview', 'brand_brain_approve', 'brand_brain_restore', 'brand_brain_discard',
                     'brand_brain_feedback', 'brand_brain_clean_restore', 'brand_brain_manual'})
BOUND = ('scheduled', 'approved', 'claimed')


def request_key(payload):
    if not isinstance(payload, dict):
        raise AlphaError('Expected a structured Brand Brain command.')
    key = payload.get('requestId')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
        raise AlphaError('A unique Brand Brain request ID is required.')
    return key


def impact(state):
    variants, jobs = state.get('variants', []), state.get('phase2', {}).get('jobs', [])
    binding = {'drafts': [{key: item.get(key) for key in ('id', 'revision', 'needsReview')} for item in variants],
               'jobs': [{key: item.get(key) for key in ('id', 'state')} for item in jobs],
               'activeRevision': state.get('speaker', {}).get('activeRevision')}
    return {'drafts': len(variants), 'heldPosts': sum(j.get('state') in BOUND for j in jobs),
            'needsReview': sum(bool(v.get('needsReview')) for v in variants),
            'currentlyHeld': sum(j.get('state') == 'held' for j in jobs), 'impactDigest': digest(binding)}


def validate_profile(state, profile):
    if not isinstance(profile, dict) or profile.get('status') == 'stale':
        raise AlphaError('Voice evidence is stale. Analyse current permitted sources again.', 409)
    bindings = profile.get('sourceBindings', [])
    if not bindings:
        if profile.get('evidenceSourceIds'):
            raise AlphaError('Voice evidence bindings are unavailable. Analyse the sources again.', 409)
        return
    projection = voice_sources.project(state, [b['id'] for b in bindings], 'analysis', profile.get('analysisRoute', 'local-rules'))
    current = [{key: item[key] for key in ('id', 'revision', 'contentHash')} for item in projection['samples']]
    if projection['excluded'] or current != bindings:
        raise AlphaError('Voice evidence or analysis permission changed. Analyse current sources again.', 409)
    samples = {s['id']: s for s in projection['samples']}
    for dimension in profile.get('dimensions', []):
        if dimension.get('decision') == 'reject' or dimension.get('evidenceLevel') in ('user-defined', 'insufficient'):
            continue
        cited = set(dimension.get('support', []) + dimension.get('counterEvidence', []))
        quotes = dimension.get('quotes', [])
        if not cited or cited - {q.get('sourceId') for q in quotes}:
            raise AlphaError('Evidence unavailable. Reanalyse or edit this trait as a user-authored rule.', 409, code='voice_evidence_unavailable')
        for quote in quotes:
            sample = samples.get(quote.get('sourceId'))
            if not sample or not quote.get('text') or quote['text'] not in sample['text']:
                raise AlphaError('Evidence unavailable. Reanalyse or edit this trait as a user-authored rule.', 409, code='voice_evidence_unavailable')


def projection(state):
    speaker = state.get('speaker', {})
    proposed = speaker.get('provisional')
    status = proposed.get('status', 'proposed') if proposed else 'none'
    if proposed:
        try:
            validate_profile(state, proposed)
        except AlphaError as error:
            if error.code != 'voice_evidence_unavailable':
                status = 'stale'
    versions = []
    for record in reversed(speaker.get('revisions', [])):
        eligible = not record.get('stale')
        try:
            validate_profile(state, record.get('profile'))
        except AlphaError:
            eligible = False
        versions.append({**copy.deepcopy(record), 'restoreEligible': eligible})
    return {'schema': 'rafii.brand-brain.v1.1', 'proposalDigest': digest(proposed) if proposed else None,
            'proposalStatus': status, 'impact': impact(state), 'versions': versions,
            'limits': {'maxSamples': 50, 'maxInputBytes': 60000, 'maxTextChars': voice_sources.MAX_TEXT_CHARS},
            'preview': copy.deepcopy(speaker.get('brandBrainPreview')),
            'analysisQuote': copy.deepcopy(speaker.get('analysisQuote')),
            'lastReceipt': copy.deepcopy(speaker.get('brandBrainReceipt'))}


def _candidate(state, payload):
    profile = state.get('speaker', {}).get('provisional')
    if not profile or payload.get('proposalDigest') != digest(profile):
        raise AlphaError('The proposal changed. Reload and review the latest proposal.', 409)
    return profile


def _confirm_impact(state, payload):
    if payload.get('confirmed') is not True:
        raise AlphaError('Confirm the effect on existing drafts and approved or scheduled posts.')
    if payload.get('impactDigest') != impact(state)['impactDigest']:
        raise AlphaError('Draft or schedule impact changed. Review the latest impact before approving.', 409)


def _preserve_boundaries(state):
    """Move the effective legacy boundary layer forward before switching a voice.

    Old profiles can own boundary fields. Copy their current effective values to the
    canonical structured boundary source, keeping current overrides and immutable
    historical voice snapshots. A voice change never restores old privacy policy.
    """
    from .memory import boundary_fields
    effective = copy.deepcopy(boundary_fields(state))
    fields = state.setdefault('profile', {}).setdefault('fields', [])
    identities = {f.get('id') or f.get('key') for f in fields if isinstance(f, dict)}
    for field in effective:
        identity = field.get('id') or field.get('key')
        if identity not in identities:
            fields.append(field)
            identities.add(identity)


def apply_action(state, action, payload, actor, now, engine):
    if action not in ACTIONS:
        return False
    key = request_key(payload)
    speaker = state.setdefault('speaker', {})
    requests = speaker.setdefault('brandBrainRequests', [])
    fingerprint = digest({'action': action, 'payload': payload})
    previous = next((item for item in requests if item['id'] == key), None)
    if previous:
        if previous['fingerprint'] != fingerprint:
            raise AlphaError('This request ID was already used for a different action.', 409)
        return True
    before = speaker.get('activeRevision')
    impact_before = impact(state)
    if action == 'brand_brain_import':
        if payload.get('authorshipConfirmed') is not True or payload.get('retentionConfirmed') is not True:
            raise AlphaError('Confirm authorship or permission and retention before saving writing.')
        result = voice_sources.apply_action(state, 'voice_samples_import', payload, actor, now)
        for source in state['sources']:
            if source['id'] in result['imported'] + result['revised']:
                source['authorshipConfirmed'] = True
                source['retentionConfirmed'] = True
    elif action == 'brand_brain_manual':
        # Validate with the existing domain on a private copy. Purpose/audience/mode
        # stay pending with the voice; no draft/Memory changes happen while teaching.
        candidate = copy.deepcopy(state)
        context = payload.get('context')
        if not isinstance(context, dict):
            raise AlphaError('Provide the brand context for this proposed voice.')
        engine._apply(candidate, 'mode', {'mode': payload.get('mode')})
        engine._apply(candidate, 'context', context)
        engine._apply(candidate, 'profile_propose', {'tone': payload.get('tone'), 'writing': ''})
        profile = candidate['speaker']['provisional']
        profile.update(workflow='brand_brain', status='proposed', analysisMethod='user-authored', toneBasis='user_defined',
                       userGuidance=list(profile.get('observations', [])), dimensions=[], sourceBindings=[], evidenceSourceIds=[],
                       brandContext={key: copy.deepcopy(candidate['brandHub'].get(key)) for key in ('mode', 'purpose', 'audience', 'subject', 'speaker', 'layers')},
                       proposedBy=actor, proposedAt=now)
        # The context command accepts only hybrid input blocks; nonhybrid modes
        # derive their own persisted layer (personal is not an input block).
        if profile['brandContext']['mode'] != 'hybrid':
            profile['brandContext']['layers'] = []
        speaker['provisional'] = profile
        speaker.pop('brandBrainPreview', None)
    elif action == 'brand_brain_analyze':
        if payload.get('route', 'local-rules') != 'local-rules':
            raise AlphaError('AI analysis requires a current quote and the hosted analysis service.', 409)
        speaker['provisional'] = voice_analysis.build_proposal(state, payload.get('sourceIds'), actor, now)
        speaker['provisional']['workflow'] = 'brand_brain'
        for source in state.get('sources', []):
            if source.get('id') in speaker['provisional']['evidenceSourceIds']:
                source['lastAnalysis'] = {'route': 'local-rules', 'model': None, 'provider': None, 'at': now, 'contentHash': source.get('contentHash')}
        speaker.pop('brandBrainPreview', None)
    elif action == 'brand_brain_clean_restore':
        record = next((r for r in speaker.get('revisions', []) if r['revision'] == payload.get('revision')), None)
        if not record:
            raise AlphaError('Choose an existing voice version.', 404)
        old = record['profile']
        dimensions = []
        for item in old.get('dimensions', []):
            if item.get('userAuthored') or item.get('evidenceLevel') == 'user-defined':
                if item.get('decision') != 'reject':
                    dimensions.append({'id': item['id'], 'observation': item['observation'], 'userAuthored': True,
                        'evidenceLevel': 'user-defined', 'support': [], 'counterEvidence': [], 'quotes': [], 'decision': 'accept'})
        explicit = list(old.get('userGuidance', []))
        if old.get('observationsBasis') == 'owner_edited' or not old.get('analysisMethod'):
            explicit.extend(old.get('observations', []))
        tone = old.get('tone') if old.get('toneBasis') == 'user_defined' or not old.get('analysisMethod') else None
        speaker['provisional'] = {'schema': 'postriff.voice-profile-proposal.v1', 'workflow': 'brand_brain',
            'status': 'proposed', 'analysisMethod': 'user-authored', 'tone': tone, 'toneBasis': 'user_defined',
            'dimensions': dimensions, 'userGuidance': list(dict.fromkeys(explicit)),
            'observations': list(dict.fromkeys([d['observation'] for d in dimensions] + explicit)),
            'unknowns': ['Clean proposal: all inferred evidence, raw quotations and historical permissions were removed. Review the remaining user-authored guidance before approval.'],
            'writingExample': '', 'preferences': [], 'sourceBindings': [], 'evidenceSourceIds': [],
            'cleanedFromRevision': record['revision'], 'proposedBy': actor, 'proposedAt': now}
        speaker.pop('brandBrainPreview', None)
    elif action == 'brand_brain_feedback':
        profile = _candidate(state, payload)
        rating, note = payload.get('rating'), payload.get('note', '')
        if rating not in ('more_like_me', 'less_like_me') or not isinstance(note, str) or len(note) > 240:
            raise AlphaError('Choose more or less like me and keep your guidance under 240 characters.')
        profile.setdefault('feedback', []).append({'rating': rating, 'note': note.strip(), 'actor': actor, 'at': now, 'source': 'user_authored'})
        if note.strip():
            profile.setdefault('userGuidance', []).append(note.strip())
            profile.setdefault('observations', []).append(note.strip())
        profile.update(status='reviewing', reviewedBy=actor, reviewedAt=now)
        speaker.pop('brandBrainPreview', None)
    elif action == 'brand_brain_review':
        profile = _candidate(state, payload)
        decisions = payload.get('decisions')
        if not isinstance(decisions, list) or len(decisions) > 18:
            raise AlphaError('Review up to 18 writing traits.')
        dimensions = {item['id']: item for item in profile.get('dimensions', [])}
        if not dimensions and 'userGuidance' not in profile and not profile.get('evidenceSourceIds'):
            profile['userGuidance'] = list(profile.get('observations', []))
        seen = set()
        for item in decisions:
            if not isinstance(item, dict) or item.get('id') not in dimensions or item['id'] in seen or item.get('decision') not in ('accept', 'edit', 'reject'):
                raise AlphaError('Choose one accept, edit or reject decision per writing trait.')
            seen.add(item['id'])
            dimension = dimensions[item['id']]
            if item['decision'] == 'edit':
                text = item.get('observation')
                if not isinstance(text, str) or not text.strip() or len(text) > 240:
                    raise AlphaError('Keep an edited trait between 1 and 240 characters.')
                dimension['originalObservation'] = dimension.get('originalObservation', dimension['observation'])
                dimension.update(observation=text.strip(), evidenceLevel='user-defined', userAuthored=True)
            dimension.update(decision=item['decision'], reviewedBy=actor, reviewedAt=now)
        if 'tone' in payload:
            tone = payload['tone']
            if not isinstance(tone, str) or len(tone) > 160:
                raise AlphaError('Keep the core voice under 160 characters.')
            profile.update(tone=tone.strip() or None, toneBasis='user_defined')
        profile['observations'] = [d['observation'] for d in dimensions.values() if d.get('decision') != 'reject' and d.get('evidenceLevel') not in ('conflicting', 'insufficient')] + list(profile.get('userGuidance', []))
        profile.update(status='reviewing', reviewedBy=actor, reviewedAt=now)
        speaker.pop('brandBrainPreview', None)
    elif action == 'brand_brain_preview':
        profile = _candidate(state, payload)
        validate_profile(state, profile)
        prompt = payload.get('prompt', '')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1500:
            raise AlphaError('Enter a preview prompt between 1 and 1500 characters.')
        for field in ('platform', 'language'):
            if not isinstance(payload.get(field, ''), str) or len(payload.get(field, '')) > 80:
                raise AlphaError('Choose a bounded language and channel for the preview.')
        speaker['brandBrainPreview'] = {'kind': 'guideline', 'generated': False,
            'label': 'Guideline preview — not a generated A/B test', 'prompt': prompt.strip(),
            'language': payload.get('language', ''), 'platform': payload.get('platform', ''),
            'neutral': {'guidance': ['Use the same supplied facts and mandatory boundaries.', 'No approved or proposed writing voice is supplied.']},
            'proposed': {'guidance': list(profile.get('observations', [])), 'proposalDigest': digest(profile)},
            'receipt': {'model': None, 'provider': None, 'paid': False, 'activeRevisionUnchanged': True,
                        'factualContextDigest': digest(state.get('brandHub', {})), 'generatedAt': now}}
    elif action == 'brand_brain_discard':
        _candidate(state, payload)
        speaker['provisional'] = None
        speaker.pop('brandBrainPreview', None)
    elif action in ('brand_brain_approve', 'brand_brain_restore'):
        _confirm_impact(state, payload)
        _preserve_boundaries(state)
        if action == 'brand_brain_approve':
            profile = _candidate(state, payload)
            validate_profile(state, profile)
            engine._apply(state, 'profile_decide', {'decision': 'approve'})
        else:
            record = next((r for r in speaker.get('revisions', []) if r['revision'] == payload.get('revision')), None)
            if not record or record.get('stale'):
                raise AlphaError('This version cannot be restored. Create a clean proposal using current permitted evidence.', 409)
            validate_profile(state, record['profile'])
            # Restore only writing voice, never old identity fields, boundaries or grants.
            restored = copy.deepcopy(record['profile'])
            restored.pop('brandContext', None)
            restored.pop('fields', None)
            engine._voice(state, restored, 'Explicit restore of voice revision ' + str(record['revision']))
            engine._mark_stale(state)
        approved = speaker['revisions'][-1]
        approved.update(approvedBy=actor, activationSource='brand_brain', restoredFrom=payload.get('revision') if action == 'brand_brain_restore' else None)
        approved['profile']['status'] = 'approved'
        engine.invalidate(state)
        speaker.pop('brandBrainPreview', None)
    after = impact(state)
    speaker['brandBrainReceipt'] = {'action': action, 'actor': actor, 'at': now, 'requestId': key,
        'activeRevisionBefore': before, 'activeRevisionAfter': speaker.get('activeRevision'),
        'impactBefore': impact_before, 'needsReview': after['needsReview'], 'heldPosts': after['currentlyHeld']}
    requests.append({'id': key, 'fingerprint': fingerprint, 'action': action, 'at': now})
    # Keep idempotency records for the workspace lifetime. They contain hashes, never source text.
    return True


class HostedPreview:
    """Two bounded, non-paid synchronous writer attempts, fenced before and after.

The existing runtime interface and memory projection assemble both requests. The
same prompt/facts/boundaries/destination/model/settings are used; only voice varies.
Cloud, paid and asynchronous routes require their own durable admission and remain
unavailable here. No preview is committed to the draft or publishing store.
"""
    def __init__(self, service):
        self.service = service

    def run(self, workspace_id, token, revision, payload):
        from . import memory
        from .agent_runtime import check_destinations
        from .permissions import Membership, require
        from .api_tokens import is_api_token
        if is_api_token(token):
            raise AlphaError('An interactive sign-in is required for a voice preview.', 403)
        key = request_key(payload)
        model = payload.get('model')
        runtime = self.service.ideas._select_runtime(model)
        if not any(m.get('id') == model and m.get('qualified') for m in runtime.list_supported_models()):
            raise AlphaError('The selected preview model is unavailable; no substitute was called.', 409)
        if (getattr(runtime, 'provider_class', 'local') != 'local'
                or getattr(runtime, 'cost_class', None) != 'none'
                or getattr(runtime, 'asynchronous', False)):
            raise AlphaError('This preview route requires a separate bounded generation approval. Choose the guideline preview or an available non-paid local writer.', 409)
        destinations = [{'platform': payload.get('platform', 'LinkedIn'), 'language': payload.get('language', 'en')}]
        check_destinations(destinations)
        prompt = payload.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 1500:
            raise AlphaError('Enter a preview prompt between 1 and 1500 characters.')
        prepared = {}
        def claim(state, actor):
            if state.get('workspace', {}).get('sample'):
                raise AlphaError('Sample workspaces are read-only.', 403)
            profile = _candidate(state, payload)
            validate_profile(state, profile)
            speaker = state['speaker']
            if any(item['id'] == key for item in speaker.get('brandBrainRequests', [])):
                raise AlphaError('This preview request was already submitted. Reload its result; no automatic retry was made.', 409)
            source_ids = profile.get('evidenceSourceIds', [])
            source_context = voice_sources.project(state, source_ids, 'generation', 'local-cli')
            if source_context['excluded']:
                raise AlphaError('Selected evidence needs a separate generation grant for this exact writer route. No writer was called.', 409)
            source_context.update(mode='personalized', bindings=profile.get('sourceBindings', []))
            # Canonical state is never switched to the candidate. Only this private request copy is projected.
            candidate_state = copy.deepcopy(state)
            _preserve_boundaries(candidate_state)
            candidate_revision = max([r['revision'] for r in speaker.get('revisions', [])] + [0]) + 1
            candidate_profile = copy.deepcopy(profile)
            candidate_profile['writingExample'] = ''
            candidate_state['speaker']['revisions'].append({'revision': candidate_revision, 'profile': candidate_profile})
            candidate_state['speaker']['activeRevision'] = candidate_revision
            common = {'model': model, 'idea': prompt.strip(), 'reasoning': 'quick', 'destinations': destinations,
                      'context': {'sources': [], 'excluded': [], 'candidateOnly': True},
                      'brandContext': copy.deepcopy(state.get('brandHub', {}))}
            shared_neutral, receipt_neutral = memory.prepare_writer(state, 'local', 'local-cli', destinations=destinations, voice_mode='neutral')
            shared_proposed, receipt_proposed = memory.prepare_writer(candidate_state, 'local', 'local-cli', destinations=destinations, voice_mode='personalized', voice_context=source_context)
            receipt_proposed['effectiveVoiceMode'] = 'override'
            mandatory_neutral = [f for f in shared_neutral['files'] if f['name'] != 'VOICE.md']
            mandatory_proposed = [f for f in shared_proposed['files'] if f['name'] != 'VOICE.md']
            if mandatory_neutral != mandatory_proposed:
                raise AlphaError('The candidate changes mandatory identity or boundaries. Review the context before comparing voice; no writer was called.', 409)
            # Raw sources do not enter either request; abstract candidate guidance is purpose-granted above.
            neutral = {**copy.deepcopy(common), 'tone': None, 'voice': {}, 'styleDirectives': {}, 'voiceMode': 'neutral', 'memory': shared_neutral['files'],
                       'voiceContext': {'mode': 'neutral', 'bindings': [], 'route': 'local-cli'}}
            proposed = {**copy.deepcopy(common), 'tone': profile.get('tone'), 'styleDirectives': voice_sources.style_directives(source_context), 'voice': {'observations': profile.get('observations', [])},
                        'voiceMode': 'personalized', 'memory': shared_proposed['files'],
                        'voiceContext': {k: source_context.get(k) for k in ('mode', 'bindings', 'digest', 'route')}}
            prepared.update(neutral=neutral, proposed=proposed, memory=[receipt_neutral, receipt_proposed],
                            proposalDigest=digest(profile), activeRevision=speaker.get('activeRevision'),
                            comparabilityDigest=digest({'request': common, 'mandatoryMemory': mandatory_neutral}), actor=actor)
            speaker.setdefault('brandBrainRequests', []).append({'id': key, 'fingerprint': digest(payload), 'action': 'brand_brain_preview', 'at': self.service.clock(), 'status': 'started'})
            return state
        saved = self.service.repository.command(workspace_id, token, revision, claim, requirement='edit',
            audit_event=lambda state: ('voice.preview_started', key, {'model': model, 'route': 'local-cli'}))
        outputs = []
        for name in ('neutral', 'proposed'):
            # Re-read immediately before each transport; a first-run revocation blocks the second.
            latest = self.service.repository.get(workspace_id, token)
            require(Membership((latest.get('membership') or {}).get('role')), 'edit')
            if latest['revision'] != saved['revision']:
                raise AlphaError('Workspace or source permissions changed before preview. No further writer was called.', 409)
            live_profile = _candidate(latest['state'], payload)
            validate_profile(latest['state'], live_profile)
            if voice_sources.project(latest['state'], live_profile.get('evidenceSourceIds', []), 'generation', 'local-cli')['excluded']:
                raise AlphaError('Writing permissions changed before preview. No further writer was called.', 409)
            result = runtime.start_turn(prepared[name], lambda event: None)
            variants = result.get('artifact', {}).get('variants', []) if isinstance(result, dict) else []
            if len(variants) != 1 or not isinstance(variants[0].get('text'), str) or len(variants[0]['text']) > 12000:
                raise AlphaError('The preview writer returned an invalid comparison. No voice was activated.', 502)
            outputs.append(variants[0]['text'])
        def finish(state, actor):
            profile = _candidate(state, payload)
            validate_profile(state, profile)
            current = voice_sources.project(state, profile.get('evidenceSourceIds', []), 'generation', 'local-cli')
            if current['excluded']:
                raise AlphaError('Writing permissions changed during preview. No result was saved.', 409)
            template = runtime.provider == 'fixture'
            state['speaker']['brandBrainPreview'] = {'kind': 'paired', 'generated': True,
                'label': 'Template comparison — no AI model' if template else 'Generated A/B preview — not active',
                'prompt': prompt.strip(), **destinations[0], 'neutral': {'guidance': [], 'text': outputs[0]},
                'proposed': {'guidance': list(profile.get('observations', [])), 'text': outputs[1], 'proposalDigest': digest(profile)},
                'receipt': {'model': model, 'provider': runtime.provider, 'paid': False, 'activeRevisionUnchanged': True,
                            'activeRevision': prepared['activeRevision'], 'comparabilityDigest': prepared['comparabilityDigest'],
                            'generationKind': 'template' if template else 'model', 'memory': prepared['memory'], 'generatedAt': self.service.clock()}}
            for request in state['speaker']['brandBrainRequests']:
                if request['id'] == key:
                    request['status'] = 'completed'
            return state
        completed = self.service.repository.command(workspace_id, token, saved['revision'], finish, requirement='edit',
            audit_event=lambda state: ('voice.preview_completed', key, {'model': model, 'route': 'local-cli', 'comparabilityDigest': prepared['comparabilityDigest']}))
        return self.service._present(completed)
