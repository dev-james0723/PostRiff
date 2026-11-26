/**
 * Profile review of a proposal built from imported posts: evidence by post id, the four quick corrections, scope
 * labels, the review's identity across corrections, and the links into the Brand page.
 *   node --test tests/voice-import-review.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadTs } from './fixtures/voice-import/load-ts.mjs';

const { isImportProfile, traitEvidence, traitSettled, correctionState, scopePlatforms, correctionPayload, scopeLabels, basisLabel, reviewKey } = await loadTs('lib/voice-import/review.ts');
const { brainLanding, REVIEW_HREF, MANUAL_SETUP_HREF } = await loadTs('features/workspace/brand/voice-import/deep-link.ts');

const trait = (extra = {}) => ({ id: 'opening_shape.ai', dimension: 'opening_shape', observation: 'Opens with one concrete image.', evidenceLevel: 'supported', support: [], counterEvidence: [], quotes: [], basis: 'model', status: 'active', period: { from: '2026-01-01', to: '2026-10-27' }, evidence: { postIds: ['p1', 'p2', 'p3'], count: 9, counter: 2 }, ...extra });

test('only a proposal built from imported posts gets the import review', () => {
  assert.equal(isImportProfile({ analysisMethod: 'voice_import' }), true);
  for (const profile of [{ analysisMethod: 'local-rules' }, { analysisMethod: 'ai' }, { analysisMethod: 'user-authored' }, {}, null, undefined]) assert.equal(isImportProfile(profile), false);
});

test('evidence is post ids and two counts; nothing else is trusted', () => {
  assert.deepEqual(traitEvidence(trait()), { postIds: ['p1', 'p2', 'p3'], count: 9, counter: 2 });
  assert.deepEqual(traitEvidence(trait({ evidence: { postIds: ['p1', 7, '', null], count: 'many' } })), { postIds: ['p1'], count: 1, counter: 0 });
  assert.deepEqual(traitEvidence(trait({ evidence: undefined })), { postIds: [], count: 0, counter: 0 });
  assert.deepEqual(traitEvidence(trait({ evidence: { postIds: 'p1', counter: [1, 2] } })), { postIds: [], count: 0, counter: 0 });
});

test('a trait is settled when it has evidence, is the person’s own rule, or is already out of the voice', () => {
  assert.equal(traitSettled(trait()), true);
  assert.equal(traitSettled(trait({ evidence: { postIds: [], count: 0, counter: 0 } })), false, 'a supported trait with no evidence is not');
  assert.equal(traitSettled(trait({ evidence: undefined, evidenceLevel: 'insufficient' })), true);
  assert.equal(traitSettled(trait({ evidence: undefined, evidenceLevel: 'user-defined', userAuthored: true })), true);
  assert.equal(traitSettled(trait({ evidence: undefined, decision: 'reject' })), true);
  assert.equal(traitSettled(trait({ evidence: undefined, status: 'historical' })), true);
});

test('the four corrections are read back from the proposal, and each sends the documented payload', () => {
  assert.deepEqual(correctionState(trait()), { soundsLikeMe: false, notMe: false, oldStyle: false, onlyFor: [] });
  assert.deepEqual(correctionState(trait({ decision: 'accept' })), { soundsLikeMe: true, notMe: false, oldStyle: false, onlyFor: [] });
  assert.deepEqual(correctionState(trait({ decision: 'reject' })), { soundsLikeMe: false, notMe: true, oldStyle: false, onlyFor: [] });
  assert.deepEqual(correctionState(trait({ decision: 'accept', status: 'historical' })), { soundsLikeMe: false, notMe: false, oldStyle: true, onlyFor: [] });
  assert.deepEqual(correctionState(trait({ scope: { platforms: ['LinkedIn'] } })).onlyFor, ['linkedin']);

  assert.deepEqual(correctionPayload(trait(), 'd1', 'sounds_like_me'), { proposalDigest: 'd1', traitId: 'opening_shape.ai', correction: 'sounds_like_me' });
  assert.deepEqual(correctionPayload(trait(), 'd1', 'not_me'), { proposalDigest: 'd1', traitId: 'opening_shape.ai', correction: 'not_me' });
  assert.deepEqual(correctionPayload(trait(), 'd1', 'old_style'), { proposalDigest: 'd1', traitId: 'opening_shape.ai', correction: 'old_style' });
  assert.deepEqual(correctionPayload(trait(), 'd1', 'only_scope', 'LinkedIn'), { proposalDigest: 'd1', traitId: 'opening_shape.ai', correction: 'only_scope', scope: { platforms: ['linkedin'] } });
  assert.deepEqual(correctionPayload(trait({ scope: { languages: ['yue'], platforms: ['threads'] } }), 'd1', 'only_scope', 'instagram').scope, { languages: ['yue'], platforms: ['instagram'] }, 'a language limit already on the trait is kept');
  assert.ok(!JSON.stringify(correctionPayload(trait(), 'd1', 'only_scope', 'linkedin')).includes('Opens with'), 'no wording travels with a correction');
});

test('"only for" offers the trait’s own platforms first, then the platforms that were imported, without repeats', () => {
  assert.deepEqual(scopePlatforms(trait(), ['threads', 'x']), ['threads', 'x']);
  assert.deepEqual(scopePlatforms(trait({ scope: { platforms: ['linkedin'] } }), ['threads', 'LinkedIn', 'x']), ['linkedin', 'threads', 'x']);
  assert.deepEqual(scopePlatforms(trait(), []), []);
  assert.equal(scopePlatforms(trait(), ['a', 'b', 'c', 'd', 'e']).length, 4);
});

test('scope and basis read as words in each locale', () => {
  const scoped = trait({ scope: { platforms: ['linkedin'], languages: ['yue'], accounts: ['side-project'] } });
  assert.deepEqual(scopeLabels(scoped, 'en'), ['Only on LinkedIn', 'Only in Cantonese', 'Only for side-project']);
  assert.deepEqual(scopeLabels(scoped, 'zh-Hant'), ['只限 LinkedIn', '只限廣東話', '只限帳戶 side-project']);
  assert.deepEqual(scopeLabels(trait(), 'en'), []);
  assert.equal(basisLabel(trait(), 'en'), 'Read by AI from your posts');
  assert.equal(basisLabel(trait({ basis: 'measured' }), 'en'), 'Measured in your posts');
  assert.equal(basisLabel(trait({ basis: 'measured', evidenceLevel: 'user-defined', userAuthored: true }), 'en'), 'Your own rule');
  assert.equal(basisLabel(trait({ basis: 'measured' }), 'zh-Hant'), '從你的貼文量度');
});

test('the review stays mounted through corrections on one import proposal and resets for a new one', () => {
  const proposal = { analysisMethod: 'voice_import', proposedAt: 1795000000 };
  assert.equal(reviewKey(proposal, 'digest-a'), reviewKey(proposal, 'digest-b'), 'a correction changes the digest, not the review');
  assert.notEqual(reviewKey(proposal, 'd'), reviewKey({ ...proposal, proposedAt: 1795000500 }, 'd'), 'a rebuilt proposal is a new review');
  assert.equal(reviewKey({ analysisMethod: 'voice_import' }, 'digest-a'), 'digest-a', 'without a build time the digest is the key');
  assert.equal(reviewKey({ analysisMethod: 'local-rules', proposedAt: 5 }, 'digest-a'), 'digest-a', 'other proposals behave as before');
  assert.equal(reviewKey(null, null), 'none');
});

test('links into the Brand page: the voice review link, the import receipt, the no-samples setup, and the old ones', () => {
  assert.deepEqual(brainLanding('?section=teach&step=review'), { area: 'teach', step: 'review' });
  assert.deepEqual(brainLanding(new URL(REVIEW_HREF, 'https://rafii.invalid').search), { area: 'teach', step: 'review' });
  assert.deepEqual(brainLanding(new URL(MANUAL_SETUP_HREF, 'https://rafii.invalid').search), { area: 'teach', step: 'sources', manualSetup: true });
  assert.deepEqual(brainLanding('?section=teach'), { area: 'teach' });
  assert.deepEqual(brainLanding('?section=teach&step=publish'), { area: 'teach' }, 'an unknown step is ignored');
  assert.deepEqual(brainLanding('?section=sources'), { area: 'sources' });
  assert.deepEqual(brainLanding('?section=identity'), { area: 'identity' });
  assert.deepEqual(brainLanding('?section=boundaries'), { area: 'identity' });
  assert.deepEqual(brainLanding('', '#manual-writing-samples'), { area: 'teach', step: 'sources' });
  assert.deepEqual(brainLanding('?section=elsewhere', '#other'), {});
  assert.deepEqual(brainLanding(''), {});
});
