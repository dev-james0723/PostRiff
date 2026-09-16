'use client';

import { CHANNEL_ICONS } from '@/components/channel-icon';
import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, BrandGlyph, ClampText, formatClock, MediaGrid, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

const INK = '#0f1419';
const MUTED = '#536471';
const BLUE = '#1d9bf0';
const LINE = '#eff3f4';

/**
 * X For you timeline (2026): avatar / logo header, For you and Following, one post (name, @handle · time, Grok
 * and more menus, text, bordered media grid, reply / repost / like / views with bookmark and share on the right),
 * the blue compose button, and the Home / Search / Grok / Notifications / Chat bar.
 */
export default function XTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const mediaBox = media.length === 1 ? mediaHeight(media[0], 329, { min: 0.5625, max: 1.25, fallback: 0.75 }) : 200;

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`X preview of the post by @${names.handle}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='relative flex h-[44px] shrink-0 items-center justify-center'>
          <Monogram name={names.display} size={32} className='absolute left-4' />
          <BrandGlyph path={CHANNEL_ICONS.x?.path} size={26} color={INK} />
        </header>
        <div className='flex h-[48px] shrink-0 border-b text-[15px]' style={{ borderColor: LINE }}>
          <span className='relative flex flex-1 items-center justify-center font-bold'>
            For you
            <span className='absolute bottom-0 h-[4px] w-[56px] rounded-full' style={{ background: BLUE }} />
          </span>
          <span className='flex flex-1 items-center justify-center font-medium' style={{ color: MUTED }}>
            Following
          </span>
        </div>

        <article className='relative flex min-h-0 flex-1 gap-3 overflow-hidden border-b px-4 pt-3' style={{ borderColor: LINE }}>
          <Monogram name={names.display} size={40} />
          <div className='flex min-w-0 flex-1 flex-col'>
            <div className='flex items-center gap-1 text-[15px] leading-5'>
              <span className='truncate font-bold'>{names.display}</span>
              <span className='shrink-0 truncate' style={{ color: MUTED }}>
                @{names.handle} · now
              </span>
              <span className='ml-auto flex shrink-0 items-center gap-3' style={{ color: MUTED }}>
                <GrokMark size={16} />
                <AppIcons.dots size={18} />
              </span>
            </div>
            <ClampText lines={12} background='#ffffff' className='text-[15px] leading-5' more={<span style={{ color: BLUE }}>Show more</span>}>
              <RichText text={post.text} accent={BLUE} />
            </ClampText>
            {media.length > 0 && <MediaGrid media={media} height={mediaBox} rounded={16} className='mt-3 border' style={{ borderColor: '#cfd9de' }} />}
            <div className='mt-3 flex items-center justify-between pr-1' style={{ color: MUTED }}>
              <AppIcons.comment size={19} stroke={1.6} />
              <AppIcons.repeat size={19} stroke={1.6} />
              <AppIcons.heart size={19} stroke={1.6} />
              <AppIcons.chartBar size={19} stroke={1.6} />
              <span className='flex gap-4'>
                <AppIcons.bookmark size={19} stroke={1.6} />
                <AppIcons.share size={19} stroke={1.6} />
              </span>
            </div>
          </div>
          <span className='absolute right-4 bottom-4 flex size-[53px] items-center justify-center rounded-full text-white shadow-lg' style={{ background: BLUE }}>
            <AppIcons.plus size={28} stroke={2.4} />
          </span>
        </article>

        <TabBar background='#ffffff' border={LINE}>
          <TabItem color={INK} icon={<AppIcons.homeFilled size={27} />} />
          <TabItem color={INK} icon={<AppIcons.search size={26} stroke={1.8} />} />
          <TabItem color={INK} icon={<GrokMark size={24} />} />
          <TabItem color={INK} icon={<AppIcons.bell size={26} stroke={1.8} />} />
          <TabItem color={INK} icon={<AppIcons.commentRound size={26} stroke={1.8} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}

function GrokMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox='0 0 24 24' fill='none' stroke='currentColor' strokeWidth='1.8' aria-hidden>
      <rect x='3' y='3' width='18' height='18' rx='4' />
      <path d='M8 16 16 8' strokeLinecap='round' />
    </svg>
  );
}
