/**
 * Image rules the workspace enforces when a post is prepared, and nothing else. Each entry mirrors a check in
 * `src/postriff_phase2/store.py` (`build_manifest`); a platform without an entry has no recorded rule, and the
 * detail says so instead of implying the image fits.
 */

interface RatioRule {
  /** Narrowest accepted width / height. */
  min: number;
  /** Widest accepted width / height. */
  max: number;
  /** How the platform's range is written for people. */
  range: string;
}

/** `build_manifest`: "Instagram images must have an aspect ratio between 4:5 and 1.91:1." */
const RATIO_RULES: Record<string, RatioRule> = {
  Instagram: { min: 0.8, max: 1.91, range: '4:5 to 1.91:1' }
};

export interface ImageRuleCheck {
  platform: string;
  /** The recorded rule in words, or null when none is recorded for this platform. */
  rule: string | null;
  /** true inside the rule, false outside it, null when there is no rule or no dimensions to check. */
  fits: boolean | null;
  note: string;
}

function ratioText(width: number, height: number) {
  return `${(width / height).toFixed(2)}:1`;
}

export function imageRuleChecks(platforms: string[], width?: number, height?: number): ImageRuleCheck[] {
  return platforms.map((platform) => {
    const rule = RATIO_RULES[platform];
    if (!rule) {
      return { platform, rule: null, fits: null, note: `No image rule recorded for ${platform}.` };
    }
    const words = `${platform} accepts ${rule.range}.`;
    if (!width || !height) {
      return { platform, rule: words, fits: null, note: 'The dimensions of this image are not recorded, so it cannot be checked.' };
    }
    const ratio = width / height;
    const fits = ratio >= rule.min && ratio <= rule.max;
    return {
      platform,
      rule: words,
      fits,
      note: fits
        ? `This image is ${ratioText(width, height)}, inside that range.`
        : `This image is ${ratioText(width, height)}. A ${platform} post with it will not be prepared until it is cropped to fit.`
    };
  });
}
