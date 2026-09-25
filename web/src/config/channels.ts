/**
 * Channel directory. Hosted connectors come from `src/postriff_phase2/providers.py`
 * and the connector audit; desktop-companion (local) channels are the skills
 * that exist under `skills/james-au-channel-*`. Only channels that really
 * exist in the codebase are listed. Capability labels are honest by rule:
 * nothing is "Direct" until the provider review has passed.
 */
import type { CapabilityLevel } from '@/components/marketing/capability-badge';

export type ChannelGroup = 'hosted' | 'local';
export type ChannelCapabilityKey = 'identity' | 'publish' | 'schedule' | 'analytics' | 'comments_read' | 'reply';
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
    notes: [hostedPending, 'Threads limits how often you can post, including posts made outside Rafii.']
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
    description: 'Single-image posts for professional accounts. Publishing needs Instagram’s permission first.',
    formats: ['Single image'],
    region: 'global',
    notes: [hostedPending, 'Instagram allows 100 published posts per 24 hours per account.']
  },

  /* ---- Desktop companion (signs in on your own machine) ---- */
  local('xiaohongshu', 'Xiaohongshu', 'Notes with images or video for China’s discovery-first community.', ['Image note', 'Video note'], { nameZh: '小紅書', region: 'cn' }),
  local('bilibili', 'Bilibili', 'Video uploads with titles, tags and descriptions tuned for Bilibili’s audience.', ['Video', 'Dynamic'], { nameZh: '哔哩哔哩', region: 'cn' }),
  local('zhihu', 'Zhihu', 'Long-form answers and articles for a knowledge-seeking readership.', ['Article', 'Answer'], { nameZh: '知乎', region: 'cn' }),
  local('weibo', 'Weibo', 'Short posts with images for fast-moving public conversation.', ['Text', 'Image'], { nameZh: '微博', region: 'cn' }),
  local('douyin', 'Douyin', 'Short vertical video for China’s largest short-video platform.', ['Video'], { nameZh: '抖音', region: 'cn' }),
  local('kuaishou', 'Kuaishou', 'Short video with a community-first feel.', ['Video'], { nameZh: '快手', region: 'cn' }),
  local('wechat-channels', 'WeChat Channels', 'Short video and image posts inside WeChat.', ['Video', 'Image'], { nameZh: '微信視頻號', region: 'cn' }),
  local('tencent-qq', 'Tencent QQ', 'Posts to Qzone and QQ communities.', ['Text', 'Image'], { nameZh: 'QQ 空間', region: 'cn' }),
  local('feishu-lark', 'Feishu / Lark', 'Announcements and documents to Feishu and Lark workspaces.', ['Message', 'Document'], { nameZh: '飛書', region: 'cn' }),
  local('dcard', 'Dcard', 'Forum posts for Taiwan’s largest student and young-adult community.', ['Text', 'Image'], { region: 'tw' }),
  local('line-official-account', 'LINE Official Account', 'Broadcasts to followers of your LINE Official Account.', ['Text', 'Image'], { region: 'jp' }),
  local('note-jp', 'note', 'Articles for Japan’s creator publishing platform.', ['Article'], { region: 'jp' }),
  local('naver-blog', 'Naver Blog', 'Blog posts for Korea’s largest portal.', ['Article', 'Image'], { region: 'kr' }),
  local('kakaotalk-channel', 'KakaoTalk Channel', 'Messages to subscribers of your KakaoTalk channel.', ['Text', 'Image'], { region: 'kr' }),
  local('sharechat', 'ShareChat', 'Regional-language posts for India.', ['Text', 'Image', 'Video'], { region: 'in' }),
  local('moj', 'Moj', 'Short vertical video for India.', ['Video'], { region: 'in' }),
  local('x', 'X', 'Posts and threads. X bills every API call, so Rafii runs it through the companion instead.', ['Text', 'Image', 'Thread']),
  local('facebook', 'Facebook Pages', 'Page posts with photos and links.', ['Text', 'Image', 'Link']),
  local('youtube', 'YouTube', 'Video uploads with titles, descriptions, tags and scheduling.', ['Video', 'Short']),
  local('tiktok', 'TikTok', 'Short vertical video. TikTok keeps unaudited API posts private, so the companion publishes through your own login.', ['Video', 'Photo']),
  local('pinterest', 'Pinterest', 'Pins with images, titles and destination links.', ['Image pin', 'Video pin']),
  local('reddit', 'Reddit', 'Text and link posts to subreddits you belong to.', ['Text', 'Link', 'Image']),
  local('bluesky', 'Bluesky', 'Text and image posts on the AT Protocol.', ['Text', 'Image']),
  local('mastodon', 'Mastodon', 'Posts to any Mastodon instance.', ['Text', 'Image']),
  local('pixelfed', 'Pixelfed', 'Photo posts on the fediverse.', ['Image']),
  local('telegram', 'Telegram', 'Channel broadcasts with text, images and files.', ['Text', 'Image', 'File']),
  local('discord', 'Discord', 'Announcements to channels in servers you manage.', ['Text', 'Image', 'Embed']),
  local('whatsapp-channels', 'WhatsApp Channels', 'Broadcast updates to channel followers.', ['Text', 'Image']),
  local('snapchat', 'Snapchat', 'Public profile stories and spotlight.', ['Video', 'Image']),
  local('google-business-profile', 'Google Business Profile', 'Updates, offers and events on your business listing.', ['Update', 'Offer', 'Event'])
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
