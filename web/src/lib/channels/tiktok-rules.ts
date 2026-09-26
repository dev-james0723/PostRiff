/**
 * TikTok's Content Sharing Guidelines as composer rules. The server checks the same rules again
 * (src/postriff_phase2/publish_options.py), so an approval can never carry a choice this refuses.
 * Self-contained on purpose: node's own test runner imports it directly (web/tests/tiktok-composer.test.mjs).
 */

export type TikTokPrivacy = 'PUBLIC_TO_EVERYONE' | 'MUTUAL_FOLLOW_FRIENDS' | 'FOLLOWER_OF_CREATOR' | 'SELF_ONLY';

export interface TikTokCreatorInfo {
  nickname: string;
  username: string;
  avatarUrl: string | null;
  privacyLevelOptions: string[];
  commentDisabled: boolean;
  duetDisabled: boolean;
  stitchDisabled: boolean;
  maxVideoPostDurationSec: number | null;
}

export interface TikTokChoice {
  /** No default: the person picks who can see the post. */
  privacyLevel: TikTokPrivacy | null;
  /** All off until the person allows them. */
  allowComment: boolean;
  allowDuet: boolean;
  allowStitch: boolean;
  commercial: { enabled: boolean; yourBrand: boolean; brandedContent: boolean };
  consent: boolean;
}

// A type alias (not an interface) so it is assignable to PublishOptionsValue's Record<string, unknown>.
export type TikTokOptions = {
  privacyLevel: TikTokPrivacy;
  allowComment: boolean;
  allowDuet: boolean;
  allowStitch: boolean;
  commercial: { enabled: boolean; yourBrand: boolean; brandedContent: boolean };
  consent: true;
  consentText: string;
};

export const PRIVACY_LABELS: Record<TikTokPrivacy, string> = {
  PUBLIC_TO_EVERYONE: 'Everyone',
  MUTUAL_FOLLOW_FRIENDS: 'Friends',
  FOLLOWER_OF_CREATOR: 'Followers',
  SELF_ONLY: 'Only me'
};

export const PROCESSING_NOTICE = 'After you publish, your content may take a few minutes to process and appear on your profile.';
export const UNAUDITED_NOTICE = 'Until TikTok audits Rafii, posts are private: only you can see them.';

export function initialChoice(): TikTokChoice {
  return {
    privacyLevel: null,
    allowComment: false,
    allowDuet: false,
    allowStitch: false,
    commercial: { enabled: false, yourBrand: false, brandedContent: false },
    consent: false
  };
}

const branded = (choice: TikTokChoice) => choice.commercial.enabled && choice.commercial.brandedContent;

/** The exact declaration shown beside the consent box. */
export function consentText(isBranded: boolean): string {
  return isBranded
    ? "By posting, you agree to TikTok's Branded Content Policy and Music Usage Confirmation"
    : "By posting, you agree to TikTok's Music Usage Confirmation";
}

/** Branded content can never be private-only. */
export function privacyDisabled(level: string, choice: TikTokChoice): boolean {
  return level === 'SELF_ONLY' && branded(choice);
}

/** Greyed out when the creator has turned the interaction off on TikTok. */
export function interactionDisabled(kind: 'comment' | 'duet' | 'stitch', info: TikTokCreatorInfo | null): boolean {
  if (!info) return true;
  return kind === 'comment' ? info.commentDisabled : kind === 'duet' ? info.duetDisabled : info.stitchDisabled;
}

/** The label TikTok will put on the post, shown as soon as a kind of commercial content is chosen. */
export function commercialLabel(choice: TikTokChoice): string | null {
  if (!choice.commercial.enabled) return null;
  if (choice.commercial.brandedContent) return "Your photo/video will be labeled as 'Paid partnership'";
  if (choice.commercial.yourBrand) return "Your photo/video will be labeled as 'Promotional content'";
  return null;
}

/** Choosing branded content clears a private-only choice it no longer allows; everything else stays as chosen. */
export function withCommercial(choice: TikTokChoice, commercial: Partial<TikTokChoice['commercial']>): TikTokChoice {
  const next: TikTokChoice = { ...choice, commercial: { ...choice.commercial, ...commercial } };
  if (!next.commercial.enabled) next.commercial = { enabled: false, yourBrand: false, brandedContent: false };
  if (privacyDisabled(next.privacyLevel ?? '', next)) next.privacyLevel = null;
  // The declaration changes with branded content, so an earlier consent no longer covers it.
  if (branded(next) !== branded(choice)) next.consent = false;
  return next;
}

/** Every reason the post can't be approved yet, in the order the form shows them. Empty means ready. */
export function problems(choice: TikTokChoice, info: TikTokCreatorInfo | null, video: { durationSec: number | null } | null): string[] {
  const out: string[] = [];
  if (!info) out.push('Waiting for your TikTok settings.');
  if (!video) out.push('TikTok needs one video. Rafii can’t upload videos yet.');
  else if (info?.maxVideoPostDurationSec && video.durationSec !== null && video.durationSec > info.maxVideoPostDurationSec) {
    out.push(`This video is longer than TikTok allows this account (${info.maxVideoPostDurationSec} seconds).`);
  }
  if (!choice.privacyLevel) out.push('Choose who can see this post.');
  else if (info && !info.privacyLevelOptions.includes(choice.privacyLevel)) out.push('TikTok doesn’t offer that privacy setting for this account.');
  if (choice.commercial.enabled && !choice.commercial.yourBrand && !choice.commercial.brandedContent) {
    out.push('You need to indicate if your content promotes yourself, a third party, or both.');
  }
  if (branded(choice) && choice.privacyLevel === 'SELF_ONLY') out.push('Branded content visibility cannot be set to private.');
  if (!choice.consent) out.push('Agree to the declaration to post.');
  return out;
}

/** The options sent with the review; null until every rule is met. */
export function toOptions(choice: TikTokChoice, info: TikTokCreatorInfo | null, video: { durationSec: number | null } | null): TikTokOptions | null {
  if (problems(choice, info, video).length > 0 || !choice.privacyLevel || !info) return null;
  return {
    privacyLevel: choice.privacyLevel,
    allowComment: choice.allowComment && !info.commentDisabled,
    allowDuet: choice.allowDuet && !info.duetDisabled,
    allowStitch: choice.allowStitch && !info.stitchDisabled,
    commercial: { ...choice.commercial },
    consent: true,
    consentText: consentText(branded(choice))
  };
}
