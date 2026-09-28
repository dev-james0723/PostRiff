/**
 * Channel directory. Hosted connectors come from `src/postriff_phase2/providers.py`
 * and the connector audit; desktop-companion (local) channels are the skills
 * that exist under `skills/james-au-channel-*`. Only channels that really
 * exist in the codebase are listed. Capability labels are honest by rule:
 * nothing is "Direct" until the provider review has passed.
 */
import type { CapabilityLevel } from '@/components/marketing/capability-badge';

export type ChannelGroup = 'hosted' | 'local';
export type ChannelCapabilityKey =
  | 'identity'
  | 'publish'
  | 'schedule'
  | 'analytics'
  | 'comments_read'
  | 'reply';
export type ChannelCapabilityLevel = 'Direct' | 'Assisted' | 'Unsupported';

export interface Channel {
  slug: string;
  name: string;
  nameZh?: string;
  group: ChannelGroup;
  capability: CapabilityLevel;
  /** Shown next to the badge, e.g. "publishing in review". */
  reviewStatus?: string;
  capabilities: Partial<Record<ChannelCapabilityKey, ChannelCapabilityLevel>>;
  description: string;
  formats: string[];
  region?: 'global' | 'cn' | 'jp' | 'kr' | 'tw' | 'in';
  notes?: string[];
}

const hostedPending = 'Publishing is still in review. Export posts until it opens.';
/** Platforms with no app review: publishing opens once Rafii has tested the connection with real accounts. */
const hostedTesting =
  'Publishing opens after Rafii finishes testing this connection. Export posts until then.';
const identityOnly = {
  identity: 'Direct',
  publish: 'Assisted',
  schedule: 'Assisted',
  analytics: 'Unsupported',
  comments_read: 'Unsupported',
  reply: 'Unsupported'
} as const;

const local = (
  slug: string,
  name: string,
  description: string,
  formats: string[],
  extra: Partial<Channel> = {}
): Channel => ({
  slug,
  name,
  group: 'local',
  capability: 'unsupported',
  reviewStatus: 'Companion not available yet',
  capabilities: { identity: 'Unsupported', publish: 'Unsupported', schedule: 'Unsupported' },
  description,
  formats,
  region: 'global',
  ...extra
});

const wave4 = (
  slug: string,
  name: string,
  description: string,
  formats: string[],
  identity: ChannelCapabilityLevel,
  extra: Partial<Channel> = {}
): Channel => ({
  slug,
  name,
  group: 'hosted',
  capability: 'unsupported',
  reviewStatus: identity === 'Direct' ? 'identity connection only' : 'provider approval required',
  capabilities: {
    identity,
    publish: 'Unsupported',
    schedule: 'Unsupported',
    analytics: 'Unsupported',
    comments_read: 'Unsupported',
    reply: 'Unsupported'
  },
  description,
  formats,
  region: 'global',
  notes: [
    'Connected does not mean publishing enabled. Wave 4 abilities stay unavailable until their exact provider permission and live test are verified.'
  ],
  ...extra
});

export const channels: Channel[] = [
  {
    slug: 'linkedin',
    name: 'LinkedIn',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: {
      identity: 'Direct',
      publish: 'Assisted',
      schedule: 'Assisted',
      analytics: 'Unsupported',
      comments_read: 'Unsupported',
      reply: 'Unsupported'
    },
    description: 'Text posts on your profile. Image posts aren’t available yet.',
    formats: ['Text post'],
    region: 'global',
    notes: [
      hostedPending,
      'LinkedIn access lasts 60 days. The account card shows when to reconnect.',
      'Company pages, analytics and comments aren’t available yet; they need LinkedIn’s approval.'
    ]
  },
  {
    slug: 'threads',
    name: 'Threads',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: {
      identity: 'Direct',
      publish: 'Assisted',
      schedule: 'Assisted',
      analytics: 'Unsupported',
      comments_read: 'Unsupported',
      reply: 'Unsupported'
    },
    description: 'Text and single-image posts. Carousels aren’t available yet.',
    formats: ['Text (500 chars)', 'Single image'],
    region: 'global',
    notes: [
      hostedPending,
      'Threads limits how often you can post, including posts made outside Rafii.'
    ]
  },
  {
    slug: 'instagram',
    name: 'Instagram',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: {
      identity: 'Direct',
      publish: 'Assisted',
      schedule: 'Assisted',
      analytics: 'Unsupported',
      comments_read: 'Unsupported',
      reply: 'Unsupported'
    },
    description:
      'Single-image posts for professional accounts. Publishing needs Instagram’s permission first.',
    formats: ['Single image'],
    region: 'global',
    notes: [hostedPending, 'Instagram allows 100 published posts per 24 hours per account.']
  },

  {
    slug: 'bluesky',
    name: 'Bluesky',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing opens after testing',
    capabilities: { ...identityOnly },
    description: 'Text posts with one image on your Bluesky account. Links stay clickable.',
    formats: ['Text (300 characters)', 'Single image'],
    region: 'global',
    notes: [
      hostedTesting,
      'You sign in on your own Bluesky server. Rafii never sees your password.'
    ]
  },
  {
    slug: 'mastodon',
    name: 'Mastodon',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing opens after testing',
    capabilities: { ...identityOnly },
    description: 'Posts with one image to your account on any Mastodon server.',
    formats: ['Text (500 characters on most servers)', 'Single image'],
    region: 'global',
    notes: [hostedTesting, 'Enter your server name first, such as mastodon.social.']
  },
  {
    slug: 'telegram',
    name: 'Telegram',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing opens after testing',
    capabilities: { ...identityOnly },
    description: 'Channel posts with text or one photo, sent by Rafii’s bot.',
    formats: ['Text', 'Photo (1024-character caption)'],
    region: 'global',
    notes: [
      hostedTesting,
      'Add Rafii’s bot as a channel admin that can post. It needs no other rights.'
    ]
  },
  {
    slug: 'discord',
    name: 'Discord',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing opens after testing',
    capabilities: { ...identityOnly },
    description: 'Announcements with one image in the server channel you choose.',
    formats: ['Text (2000 characters)', 'Single image'],
    region: 'global',
    notes: [hostedTesting, 'Rafii’s bot never pings @everyone or roles.']
  },
  {
    slug: 'x',
    name: 'X',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing opens after testing',
    capabilities: { ...identityOnly },
    description: 'Posts with one image on your X account.',
    formats: ['Text (280 characters)', 'Single image'],
    region: 'global',
    notes: [hostedTesting, 'X charges Rafii for every post and read.']
  },

  {
    slug: 'facebook',
    name: 'Facebook Pages',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: { ...identityOnly },
    description: 'Text, a link or one photo on the Facebook Page you choose.',
    formats: ['Text', 'Link', 'Single photo'],
    region: 'global',
    notes: [
      hostedPending,
      'Rafii publishes at the time you approve; nothing is scheduled on Facebook itself.'
    ]
  },
  {
    slug: 'youtube',
    name: 'YouTube',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: { ...identityOnly },
    description: 'Video uploads with the title, visibility and audience you choose.',
    formats: ['Video'],
    region: 'global',
    notes: [hostedPending, 'Until Google audits Rafii, YouTube keeps every upload private.']
  },
  {
    slug: 'tiktok',
    name: 'TikTok',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: { ...identityOnly },
    description:
      'Short vertical video with TikTok’s own privacy, interaction and disclosure choices.',
    formats: ['Video'],
    region: 'global',
    notes: [hostedPending, 'Until TikTok audits Rafii, posts are private: only you can see them.']
  },
  {
    slug: 'pinterest',
    name: 'Pinterest',
    group: 'hosted',
    capability: 'assisted',
    reviewStatus: 'publishing in review',
    capabilities: { ...identityOnly },
    description: 'One image Pin with a title and link, on the board you choose for each Pin.',
    formats: ['Image pin'],
    region: 'global',
    notes: [
      hostedPending,
      'While Pinterest reviews Rafii, Pins go to a test area only you can see.'
    ]
  },

  /* ---- Desktop companion (signs in on your own machine) ---- */
  wave4(
    'xiaohongshu',
    'Xiaohongshu',
    'Official device authorization can expose identity/basic_info after app approval; notes, analytics and comments remain disabled.',
    ['Image note', 'Video note'],
    'Direct',
    { nameZh: '小紅書', region: 'cn', reviewStatus: 'identity approval required' }
  ),
  wave4(
    'bilibili',
    'Bilibili',
    'Account linking is awaiting Bilibili developer identity and application approval.',
    ['Video', 'Article'],
    'Unsupported',
    { nameZh: '哔哩哔哩', region: 'cn' }
  ),
  wave4(
    'zhihu',
    'Zhihu',
    'Identity and owned-content access await a current approved Zhihu API contract; publishing stays unsupported.',
    ['Article', 'Answer'],
    'Unsupported',
    { nameZh: '知乎', region: 'cn' }
  ),
  wave4(
    'weibo',
    'Weibo',
    'Developer service, OAuth and paid API status must be approved before account connection opens.',
    ['Text', 'Image'],
    'Unsupported',
    { nameZh: '微博', region: 'cn' }
  ),
  wave4(
    'douyin',
    'Douyin',
    'Identity connection plumbing is behind its flag and still needs a live provider test; video and comments remain permission-gated.',
    ['Video'],
    'Direct',
    { nameZh: '抖音', region: 'cn' }
  ),
  wave4(
    'kuaishou',
    'Kuaishou',
    'Identity connection plumbing is behind its flag and still needs a live provider test; video publishing remains permission-gated.',
    ['Video'],
    'Direct',
    { nameZh: '快手', region: 'cn' }
  ),
  local(
    'wechat-channels',
    'WeChat Channels',
    'Short video and image posts inside WeChat.',
    ['Video', 'Image'],
    { nameZh: '微信視頻號', region: 'cn' }
  ),
  local('tencent-qq', 'Tencent QQ', 'Posts to Qzone and QQ communities.', ['Text', 'Image'], {
    nameZh: 'QQ 空間',
    region: 'cn'
  }),
  local(
    'feishu-lark',
    'Feishu / Lark',
    'Announcements and documents to Feishu and Lark workspaces.',
    ['Message', 'Document'],
    { nameZh: '飛書', region: 'cn' }
  ),
  local(
    'dcard',
    'Dcard',
    'Forum posts for Taiwan’s largest student and young-adult community.',
    ['Text', 'Image'],
    { region: 'tw' }
  ),
  wave4(
    'line-official-account',
    'LINE Official Account',
    'Official Account channel onboarding needs a confidential token handoff and verified webhook before messaging opens.',
    ['Text', 'Image'],
    'Unsupported',
    { region: 'jp' }
  ),
  local('note-jp', 'note', 'Articles for Japan’s creator publishing platform.', ['Article'], {
    region: 'jp'
  }),
  local(
    'naver-blog',
    'Naver Blog',
    'Blog posts for Korea’s largest portal.',
    ['Article', 'Image'],
    { region: 'kr' }
  ),
  local(
    'kakaotalk-channel',
    'KakaoTalk Channel',
    'Messages to subscribers of your KakaoTalk channel.',
    ['Text', 'Image'],
    { region: 'kr' }
  ),
  local(
    'sharechat',
    'ShareChat',
    'Regional-language posts for India.',
    ['Text', 'Image', 'Video'],
    { region: 'in' }
  ),
  local('moj', 'Moj', 'Short vertical video for India.', ['Video'], { region: 'in' }),
  wave4(
    'reddit',
    'Reddit',
    'Identity-only OAuth is behind Reddit approval; every future post or comment remains a separate explicit user action.',
    ['Text', 'Link', 'Image'],
    'Direct'
  ),
  wave4(
    'pixelfed',
    'Pixelfed',
    'Read-only identity connection probes each instance before dynamic OAuth registration; publishing varies by instance and stays unavailable.',
    ['Image'],
    'Direct',
    { reviewStatus: 'identity connection only' }
  ),
  local('whatsapp-channels', 'WhatsApp Channels', 'Broadcast updates to channel followers.', [
    'Text',
    'Image'
  ]),
  local('snapchat', 'Snapchat', 'Public profile stories and spotlight.', ['Video', 'Image']),
  wave4(
    'google-business-profile',
    'Google Business Profile',
    'Manager-account and location-picker plumbing still needs project approval and a live test; posts, performance and review replies remain disabled.',
    ['Update', 'Offer', 'Event'],
    'Direct'
  )
];

export const hostedChannels = channels.filter((c) => c.group === 'hosted');
export const localChannels = channels.filter((c) => c.group === 'local');

export function channelBySlug(slug: string) {
  return channels.find((c) => c.slug === slug);
}

/** Map an API platform name (e.g. "LinkedIn") to its directory entry. */
export function channelByPlatform(platform: string) {
  const key = platform.toLowerCase().replace(/\s+/g, '-');
  return channels.find((c) => c.slug === key || c.name.toLowerCase() === platform.toLowerCase());
}
