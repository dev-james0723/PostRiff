'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, formatTime, MediaCarousel, mediaHeight, MissingMedia, Monogram, RichText, TabBar, TabItem } from '../parts';
import { useSlideIndex } from '../playback';
import type { TemplateProps } from '../types';

// Measured from Instagram's shared colour tokens (light theme).
const TEXT = '#0c1014';
const MUTED = '#6a717a';
const LINK = '#00376b';
const LINE = '#dbdbdb';
const ACTIVE_DOT = '#0095f6';

/**
 * Instagram Home feed post (2025–26 layout): "+" / wordmark / heart header, username-only post header,
 * edge-to-edge media at the first item's ratio (1.91:1 to 4:5), heart / comment / repost / share with the
 * bookmark far right, caption cut at two lines, date, and the Home / Reels / Messages / Search / Profile bar.
 */
export default function InstagramTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const visual = post.media.filter((item) => item.kind !== 'file');
  const first = visual[0];
  // Every slide takes the first item's ratio, as Instagram's carousels do.
  const height = mediaHeight(first, 393, { min: 1 / 1.91, max: 1.25, fallback: 1.25 });
  const slide = useSlideIndex(visual.length);

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Instagram preview of the post by ${names.handle}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: TEXT }}>
        <StatusBarSpace />
        <header className='flex h-[44px] shrink-0 items-center justify-between px-4'>
          <AppIcons.plus size={27} stroke={1.9} />
          <span className='text-[29px] leading-none tracking-tight' style={{ fontFamily: '"Snell Roundhand", "Brush Script MT", "Segoe Script", cursive', fontWeight: 700 }}>
            Instagram
          </span>
          <AppIcons.heart size={26} stroke={1.9} />
        </header>

        <article className='flex min-h-0 flex-1 flex-col overflow-hidden'>
          <div className='flex h-[54px] shrink-0 items-center gap-2.5 px-3'>
            <Monogram name={names.display} size={32} />
            <span className='min-w-0 flex-1 truncate text-[14px] font-semibold'>{names.handle}</span>
            <AppIcons.dots size={22} stroke={2} />
          </div>

          <div className='relative shrink-0' style={{ height }}>
            {first ? (
              <MediaCarousel media={visual} crop className='size-full' />
            ) : (
              <MissingMedia need='Instagram posts need a photo or video.' className='size-full' />
            )}
            {visual[slide]?.kind === 'video' && (
              <span className='absolute right-3 bottom-3 flex size-7 items-center justify-center rounded-full bg-black/50 text-white'>
                <AppIcons.volume size={15} stroke={2} />
              </span>
            )}
          </div>

          <div className='relative flex h-[46px] shrink-0 items-center gap-[14px] px-3'>
            <AppIcons.heart size={25} stroke={1.8} />
            <AppIcons.comment size={25} stroke={1.8} className='-scale-x-100' />
            <AppIcons.repeat size={24} stroke={1.8} />
            <AppIcons.send size={24} stroke={1.8} />
            {visual.length > 1 && (
              <span className='absolute top-1/2 left-1/2 flex -translate-x-1/2 -translate-y-1/2 gap-1'>
                {visual.slice(0, 10).map((item, index) => (
                  <span key={item.id} className='size-[6px] rounded-full' style={{ background: index === slide ? ACTIVE_DOT : LINE }} />
                ))}
              </span>
            )}
            <AppIcons.bookmark size={25} stroke={1.8} className='ml-auto' />
          </div>

          <div className='px-3 text-[14px] leading-[18px]'>
            <ClampText lines={2} background='#ffffff' more={<span style={{ color: MUTED }}>… more</span>}>
              <span className='font-semibold'>{names.handle}</span> <RichText text={post.text} accent={LINK} />
            </ClampText>
            <p className='mt-1.5 text-[12px]' style={{ color: MUTED }}>
              {formatTime(post, 'en-US', { month: 'long', day: 'numeric' })}
            </p>
          </div>
        </article>

        <TabBar background='#ffffff' border={LINE}>
          <TabItem color={TEXT} icon={<AppIcons.homeFilled size={27} />} />
          <TabItem color={TEXT} icon={<AppIcons.movie size={27} stroke={1.8} />} />
          <TabItem color={TEXT} icon={<AppIcons.send size={26} stroke={1.8} />} />
          <TabItem color={TEXT} icon={<AppIcons.search size={26} stroke={2} />} />
          <TabItem color={TEXT} icon={<Monogram name={names.display} size={27} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
