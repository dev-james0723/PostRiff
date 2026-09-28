import test from 'node:test';
import assert from 'node:assert/strict';
import {
  commercialLabel,
  consentText,
  initialChoice,
  interactionDisabled,
  privacyDisabled,
  problems,
  toOptions,
  withCommercial
} from '../src/lib/channels/tiktok-rules.ts';

const info = {
  nickname: 'James',
  username: 'jamesau',
  avatarUrl: null,
  privacyLevelOptions: ['PUBLIC_TO_EVERYONE', 'FOLLOWER_OF_CREATOR', 'SELF_ONLY'],
  commentDisabled: false,
  duetDisabled: true,
  stitchDisabled: false,
  maxVideoPostDurationSec: 60
};
const video = { durationSec: 30 };

test('nothing is chosen for the person: no privacy default, interactions off, no consent', () => {
  const choice = initialChoice();
  assert.equal(choice.privacyLevel, null);
  assert.deepEqual([choice.allowComment, choice.allowDuet, choice.allowStitch, choice.consent], [false, false, false, false]);
  assert.ok(problems(choice, info, video).includes('Choose who can see this post.'));
  assert.equal(toOptions(choice, info, video), null);
});

test('interactions the creator turned off are greyed out and stay off', () => {
  assert.equal(interactionDisabled('duet', info), true);
  assert.equal(interactionDisabled('comment', info), false);
  assert.equal(interactionDisabled('stitch', null), true); // before the settings load
  const choice = { ...initialChoice(), privacyLevel: 'PUBLIC_TO_EVERYONE', allowDuet: true, allowComment: true, consent: true };
  const options = toOptions(choice, info, video);
  assert.equal(options.allowDuet, false);
  assert.equal(options.allowComment, true);
});

test('commercial content needs a kind, labels the post and branded content is never private', () => {
  let choice = withCommercial({ ...initialChoice(), privacyLevel: 'SELF_ONLY', consent: true }, { enabled: true });
  assert.ok(problems(choice, info, video).includes('You need to indicate if your content promotes yourself, a third party, or both.'));
  choice = withCommercial(choice, { yourBrand: true });
  assert.equal(commercialLabel(choice), "Your photo/video will be labeled as 'Promotional content'");
  assert.equal(choice.privacyLevel, 'SELF_ONLY'); // your own brand may stay private
  assert.equal(choice.consent, true);
  choice = withCommercial(choice, { brandedContent: true });
  assert.equal(commercialLabel(choice), "Your photo/video will be labeled as 'Paid partnership'");
  assert.equal(choice.privacyLevel, null); // branded content cleared the private-only choice
  assert.equal(choice.consent, false); // the declaration changed, so consent is asked again
  assert.equal(privacyDisabled('SELF_ONLY', choice), true);
  assert.equal(privacyDisabled('PUBLIC_TO_EVERYONE', choice), false);
});

test('the declaration is exact and branded content adds the Branded Content Policy', () => {
  assert.equal(consentText(false), "By posting, you agree to TikTok's Music Usage Confirmation");
  assert.equal(consentText(true), "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation");
  const branded = withCommercial({ ...initialChoice(), privacyLevel: 'PUBLIC_TO_EVERYONE' }, { enabled: true, brandedContent: true });
  const options = toOptions({ ...branded, consent: true }, info, video);
  assert.equal(options.consentText, consentText(true));
  assert.equal(options.commercial.brandedContent, true);
});

test('a video is required and must fit the account limit; privacy must be one TikTok offers', () => {
  const choice = { ...initialChoice(), privacyLevel: 'PUBLIC_TO_EVERYONE', consent: true };
  assert.ok(problems(choice, info, null).some((p) => p.startsWith('TikTok needs one video')));
  assert.ok(problems(choice, info, { durationSec: 90 }).some((p) => p.includes('60 seconds')));
  assert.ok(problems({ ...choice, privacyLevel: 'MUTUAL_FOLLOW_FRIENDS' }, info, video).includes('TikTok doesn’t offer that privacy setting for this account.'));
  assert.deepEqual(problems(choice, info, video), []);
});
