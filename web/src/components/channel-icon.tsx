import type { CSSProperties } from 'react';
import {
  siBilibili,
  siBluesky,
  siDiscord,
  siFacebook,
  siGoogle,
  siInstagram,
  siKakaotalk,
  siKuaishou,
  siLine,
  siMastodon,
  siNaver,
  siNote,
  siPinterest,
  siPixelfed,
  siQq,
  siReddit,
  siSinaweibo,
  siSnapchat,
  siTelegram,
  siThreads,
  siTiktok,
  siWhatsapp,
  siWechat,
  siX,
  siXiaohongshu,
  siYoutube,
  siZhihu
} from 'simple-icons';
import { channelByPlatform } from '@/config/channels';
import { cn } from '@/lib/utils';

/**
 * Brand marks for every channel in `src/config/channels.ts`. Ported from the
 * founder alpha (`studio/web/src/channelIcons.ts`): simple-icons where the set
 * has the brand, hand-drawn paths or monogram marks where it does not
 * (LinkedIn is not in simple-icons; Douyin shares TikTok's mark).
 */
interface IconDefinition {
  path?: string;
  mark?: string;
  color: string;
  /** Solid background for brands whose mark is dark on a colour (Snapchat, Kakao, Moj). */
  background?: string;
}

const LINKEDIN_PATH =
  'M20.45 20.45h-3.56v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.34V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.32 7.43a2.07 2.07 0 1 1 0-4.14 2.07 2.07 0 0 1 0 4.14zM7.1 20.45H3.54V9H7.1v11.45z';
const SHARE_PATH =
  'M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.03-.47-.09-.7l7.05-4.11A2.99 2.99 0 1 0 15 5c0 .24.03.47.09.7L8.04 9.81A3 3 0 1 0 8.04 14l7.12 4.16c-.04.2-.07.41-.07.63A2.91 2.91 0 1 0 18 16.08z';

const brand = (icon: { path: string; hex: string }, background?: string): IconDefinition => ({
  path: icon.path,
  color: `#${icon.hex}`,
  background
});

export const CHANNEL_ICONS: Record<string, IconDefinition> = {
  linkedin: { path: LINKEDIN_PATH, color: '#0A66C2' },
  threads: brand(siThreads),
  instagram: brand(siInstagram),
  xiaohongshu: brand(siXiaohongshu),
  bilibili: brand(siBilibili),
  zhihu: brand(siZhihu),
  weibo: brand(siSinaweibo),
  douyin: brand(siTiktok),
  kuaishou: brand(siKuaishou),
  'wechat-channels': brand(siWechat),
  'tencent-qq': brand(siQq),
  'feishu-lark': { mark: '✦', color: '#3370FF' },
  dcard: { mark: 'D', color: '#006AA6' },
  'line-official-account': brand(siLine),
  'note-jp': brand(siNote),
  'naver-blog': brand(siNaver),
  'kakaotalk-channel': brand(siKakaotalk, '#FFCD00'),
  sharechat: { path: SHARE_PATH, color: '#EF4136' },
  moj: { mark: 'M', color: '#111111', background: '#FFD800' },
  x: brand(siX),
  facebook: brand(siFacebook),
  youtube: brand(siYoutube),
  tiktok: brand(siTiktok),
  pinterest: brand(siPinterest),
  reddit: brand(siReddit),
  bluesky: brand(siBluesky),
  mastodon: brand(siMastodon),
  pixelfed: brand(siPixelfed),
  telegram: brand(siTelegram),
  discord: brand(siDiscord),
  'whatsapp-channels': brand(siWhatsapp),
  snapchat: brand(siSnapchat, '#FFFC00'),
  'google-business-profile': brand(siGoogle)
};

const SIZES = {
  xs: 'size-4 rounded',
  sm: 'size-6 rounded-md',
  md: 'size-8 rounded-lg',
  lg: 'size-12 rounded-xl'
} as const;

interface ChannelIconProps {
  /** Directory slug (preferred). */
  slug?: string;
  /** API platform name (e.g. "LinkedIn") or provider id ("threads"); resolved to a slug. */
  platform?: string;
  /** Used for the monogram fallback. */
  name?: string;
  size?: keyof typeof SIZES;
  className?: string;
}

export function resolveChannelSlug(slug?: string, platform?: string) {
  if (slug) return slug;
  if (!platform) return '';
  return channelByPlatform(platform)?.slug ?? platform.toLowerCase().replace(/\s+/g, '-');
}

/** Decorative brand mark; always paired with the visible channel name. */
export function ChannelIcon({ slug, platform, name, size = 'sm', className }: ChannelIconProps) {
  const key = resolveChannelSlug(slug, platform);
  const definition = CHANNEL_ICONS[key];
  const color = definition?.color ?? 'var(--muted-foreground)';
  const foreground = definition?.background ? '#171717' : color;
  const style: CSSProperties = {
    color: foreground,
    backgroundColor: definition?.background ?? (definition ? `${definition.color}1f` : 'var(--muted)')
  };
  const mark = definition?.mark ?? (name || platform || key || '?').slice(0, 1).toUpperCase();
  return (
    <span aria-hidden className={cn('inline-flex shrink-0 items-center justify-center', SIZES[size], className)} style={style}>
      {definition?.path ? (
        <svg viewBox='0 0 24 24' focusable='false' className='size-[62%]'>
          <path d={definition.path} fill='currentColor' />
        </svg>
      ) : (
        <span className='text-[0.55em] leading-none font-semibold'>{mark}</span>
      )}
    </span>
  );
}
