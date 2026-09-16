'use client';

import { CHANNEL_ICONS } from '@/components/channel-icon';
import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, BrandGlyph, formatClock, MediaFill, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// Measured from threads.com, which shares the iOS app's tokens (light theme).
const INK = '#000000';
const MUTED = '#999999';
const ICON = '#424242';
const LINK = '#0095f6';
const LINE = 'rgba(0,0,0,0.15)';
const INACTIVE = '#b8b8b8';

/**
 * Threads For you feed (2026): menu / logo / search header over For you and Following, a post with the text
 * indented beside a 36pt avatar and shown in full, media in the content column, four quiet actions, and the
 * Home / Messages / Create / Activity / Profile bar.
 */
export default function ThreadsTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Threads preview of the post by ${names.handle}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='relative flex h-[44px] shrink-0 items-center justify-center'>
          <AppIcons.menu size={25} stroke={1.9} className='absolute left-4' />
          <BrandGlyph path={CHANNEL_ICONS.threads?.path} size={30} color={INK} />
          <AppIcons.search size={24} stroke={2} className='absolute right-4' />
        </header>
        <div className='flex h-[42px] shrink-0 items-center gap-6 border-b px-4 text-[15px] font-semibold' style={{ borderColor: LINE }}>
          <span className='relative flex h-full items-center'>
            For you
            <span className='absolute inset-x-0 bottom-0 h-[1.5px] bg-black' />
          </span>
          <span style={{ color: MUTED }}>Following</span>
        </div>

        <article className='flex min-h-0 flex-1 gap-3 overflow-hidden px-3 pt-3'>
          <Monogram name={names.display} size={36} />
          <div className='flex min-w-0 flex-1 flex-col pb-3'>
            <div className='flex items-center gap-1.5 text-[15px] leading-5'>
              <span className='truncate font-semibold'>{names.handle}</span>
              <span style={{ color: MUTED }}>now</span>
              <AppIcons.dots size={20} className='ml-auto shrink-0' color={ICON} />
            </div>
            <p className='mt-0.5 text-[15px] leading-[21px]'>
              <RichText text={post.text} accent={LINK} />
            </p>
            {media.length === 1 && (
              <MediaFill
                media={media[0]}
                rounded={8}
                className='mt-2.5 w-full shrink-0 ring-[0.5px] ring-black/15'
                style={{ height: mediaHeight(media[0], 318, { min: 0.5, max: 1.34, fallback: 1.33 }) }}
              />
            )}
            {media.length > 1 && (
              <div className='mt-2.5 -mr-3 flex shrink-0 gap-1.5 overflow-hidden'>
                {media.slice(0, 3).map((item) => (
                  <MediaFill key={item.id} media={item} rounded={8} className='h-[250px] w-[188px] shrink-0 ring-[0.5px] ring-black/15' />
                ))}
              </div>
            )}
            <div className='mt-3 flex items-center gap-[20px]' style={{ color: ICON }}>
              <AppIcons.heart size={19} stroke={1.8} />
              <AppIcons.comment size={19} stroke={1.8} className='-scale-x-100' />
              <AppIcons.repeat size={19} stroke={1.8} />
              <AppIcons.send size={19} stroke={1.8} />
            </div>
          </div>
        </article>

        <TabBar background='#ffffff'>
          <TabItem color={INK} icon={<AppIcons.homeFilled size={27} />} />
          <TabItem color={INACTIVE} icon={<AppIcons.send size={26} stroke={2.1} />} />
          <TabItem
            color={INACTIVE}
            icon={
              <span className='flex h-[34px] w-[46px] items-center justify-center rounded-[10px] bg-[#f5f5f5]'>
                <AppIcons.plus size={24} stroke={2.4} />
              </span>
            }
          />
          <TabItem color={INACTIVE} icon={<AppIcons.heart size={27} stroke={2.1} />} />
          <TabItem color={INACTIVE} icon={<AppIcons.user size={27} stroke={2.1} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
