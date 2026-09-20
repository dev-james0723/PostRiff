/**
 * When each template was last checked against its app, and how sure that check was (high: open-source code,
 * official specs or first-hand; medium: App Store or news screenshots, or a mix; low: parts unconfirmed). The
 * research and sources are in docs/postriff-post-preview-templates.md §2. Update a row whenever a template is
 * re-checked, including when nothing needed to change.
 */
export type CheckConfidence = 'high' | 'medium' | 'low';

export const TEMPLATE_CHECKS: Record<string, { checkedOn: string; confidence: CheckConfidence }> = {
  bilibili: { checkedOn: '2026-09-16', confidence: 'medium' },
  bluesky: { checkedOn: '2026-09-16', confidence: 'high' },
  dcard: { checkedOn: '2026-09-16', confidence: 'high' },
  discord: { checkedOn: '2026-09-16', confidence: 'medium' },
  douyin: { checkedOn: '2026-09-16', confidence: 'medium' },
  facebook: { checkedOn: '2026-09-16', confidence: 'high' },
  'feishu-lark': { checkedOn: '2026-09-16', confidence: 'high' },
  'google-business-profile': { checkedOn: '2026-09-16', confidence: 'medium' },
  instagram: { checkedOn: '2026-09-16', confidence: 'high' },
  'kakaotalk-channel': { checkedOn: '2026-09-16', confidence: 'high' },
  kuaishou: { checkedOn: '2026-09-16', confidence: 'medium' },
  'line-official-account': { checkedOn: '2026-09-16', confidence: 'high' },
  linkedin: { checkedOn: '2026-09-16', confidence: 'medium' },
  mastodon: { checkedOn: '2026-09-16', confidence: 'high' },
  moj: { checkedOn: '2026-09-16', confidence: 'medium' },
  'naver-blog': { checkedOn: '2026-09-16', confidence: 'medium' },
  'note-jp': { checkedOn: '2026-09-16', confidence: 'medium' },
  pinterest: { checkedOn: '2026-09-16', confidence: 'medium' },
  pixelfed: { checkedOn: '2026-09-16', confidence: 'high' },
  reddit: { checkedOn: '2026-09-16', confidence: 'high' },
  sharechat: { checkedOn: '2026-09-16', confidence: 'low' },
  snapchat: { checkedOn: '2026-09-16', confidence: 'medium' },
  telegram: { checkedOn: '2026-09-16', confidence: 'high' },
  'tencent-qq': { checkedOn: '2026-09-16', confidence: 'medium' },
  threads: { checkedOn: '2026-09-16', confidence: 'high' },
  tiktok: { checkedOn: '2026-09-16', confidence: 'high' },
  'wechat-channels': { checkedOn: '2026-09-16', confidence: 'medium' },
  weibo: { checkedOn: '2026-09-16', confidence: 'medium' },
  'whatsapp-channels': { checkedOn: '2026-09-16', confidence: 'high' },
  x: { checkedOn: '2026-09-16', confidence: 'high' },
  xiaohongshu: { checkedOn: '2026-09-16', confidence: 'medium' },
  youtube: { checkedOn: '2026-09-16', confidence: 'high' },
  zhihu: { checkedOn: '2026-09-16', confidence: 'high' }
};

/** Apps redesign often; past this a preview says its check is old rather than implying it is current. */
export const RECHECK_AFTER_DAYS = 60;

export function templateCheck(channel: string, now = new Date()) {
  const check = TEMPLATE_CHECKS[channel];
  if (!check) return null;
  const checked = new Date(`${check.checkedOn}T00:00:00Z`);
  const days = Math.floor((now.getTime() - checked.getTime()) / 86_400_000);
  const label = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(checked);
  return { ...check, label, stale: days > RECHECK_AFTER_DAYS };
}
