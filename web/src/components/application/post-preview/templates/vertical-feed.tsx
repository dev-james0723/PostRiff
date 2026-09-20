'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { COVER_MARK, FOLD_MARK, useCaptionFold, useCoverLegend } from '../guides';
import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { formatClock, MediaCarousel, MissingMedia, truncateCaption } from '../parts';
import { useSlideIndex } from '../playback';
import type { PreviewPost } from '../types';

export interface VerticalFeedProps {
  post: PreviewPost;
  scale: number;
  lang?: string;
  label: string;
  /** Top overlay: left control, feed tabs (one active), right control. */
  topLeft?: ReactNode;
  tabs: { label: string; active?: boolean }[];
  /** Drawn under the active tab instead of the default underline (Douyin's ⇌). */
  activeMark?: ReactNode;
  topRight?: ReactNode;
  /** Right-hand rail, top to bottom. */
  rail: ReactNode;
  /** Creator line above the caption (name, follow button). */
  creator: ReactNode;
  moreLabel: string;
  captionChars?: number;
  /** Sound or music line under the caption. */
  footnote?: ReactNode;
  missingMedia: string;
  /** `missingMedia` in English for the notes under the phone, when it is in the app's language. */
  missingNote?: string;
  progressColor?: string;
  tabBar: ReactNode;
  tabBarBackground?: string;
}

/** Full-screen vertical video or photo post with overlaid tabs, rail and caption, the shape short-video apps share. */
export function VerticalFeed({
  post,
  scale,
  lang,
  label,
  topLeft,
  tabs,
  activeMark,
  topRight,
  rail,
  creator,
  moreLabel,
  captionChars = 60,
  footnote,
  missingMedia,
  missingNote,
  progressColor = 'rgba(255,255,255,0.85)',
  tabBar,
  tabBarBackground = '#000000'
}: VerticalFeedProps) {
  const media = post.media.filter((item) => item.kind !== 'file');
  const caption = truncateCaption(post.text, captionChars);
  const slide = useSlideIndex(media.length);
  useCaptionFold(caption, moreLabel);
  useCoverLegend();

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' lang={lang} label={label} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col text-white'>
        <div className='relative min-h-0 flex-1 overflow-hidden'>
          {media[0] ? (
            <MediaCarousel media={media} className='absolute inset-0' />
          ) : (
            <MissingMedia need={missingMedia} note={missingNote} dark className='absolute inset-x-6 top-[160px] bottom-[220px] rounded-2xl' />
          )}
          <div className='absolute inset-x-0 top-0 h-[150px] bg-gradient-to-b from-black/45 to-transparent' />
          <div className='absolute inset-x-0 bottom-0 h-[280px] bg-gradient-to-t from-black/65 to-transparent' />

          <div
            className={cn('absolute inset-x-0 flex h-[44px] items-center justify-between px-4 text-[17px] drop-shadow-[0_1px_2px_rgb(0_0_0/0.4)]', COVER_MARK)}
            style={{ top: STATUS_BAR_HEIGHT }}
          >
            <span className='flex w-[40px] justify-start'>{topLeft}</span>
            <span className='flex items-center gap-4'>
              {tabs.map((tab) => (
                <span key={tab.label} className={tab.active ? 'relative font-bold' : 'font-medium text-white/70'}>
                  {tab.label}
                  {tab.active &&
                    (activeMark ? (
                      <span className='absolute top-full left-1/2 -translate-x-1/2 text-[11px] leading-none'>{activeMark}</span>
                    ) : (
                      <span className='absolute -bottom-2 left-1/2 h-[3px] w-[22px] -translate-x-1/2 rounded-full bg-white' />
                    ))}
                </span>
              ))}
            </span>
            <span className='flex w-[40px] justify-end'>{topRight}</span>
          </div>

          <div className={cn('absolute right-2 bottom-[18px] flex w-[62px] flex-col items-center gap-[18px] text-[13px] font-semibold [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]', COVER_MARK)}>
            {rail}
          </div>

          <div className={cn('absolute bottom-[18px] left-3 w-[292px] [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]', COVER_MARK)}>
            {media.length > 1 && (
              <span className='mb-2 inline-flex rounded-[4px] bg-black/40 px-1.5 py-0.5 text-[12px] font-semibold'>
                {slide + 1}/{media.length}
              </span>
            )}
            {creator}
            <p className='mt-1 text-[15px] leading-[21px]'>
              {caption.text}
              {caption.cut && (
                <>
                  {' '}
                  <span className={cn('font-semibold', FOLD_MARK)}>{moreLabel}</span>
                </>
              )}
            </p>
            {footnote && <p className='mt-2 flex items-center gap-1.5 text-[14px]'>{footnote}</p>}
          </div>
          <div className='absolute inset-x-0 bottom-0 h-[2px] bg-white/25'>
            <div className='h-full w-[3%]' style={{ background: progressColor }} />
          </div>
        </div>
        <nav className='flex h-[83px] shrink-0 items-start justify-around px-1 pt-[7px]' style={{ background: tabBarBackground }}>
          {tabBar}
        </nav>
      </div>
    </PhoneFrame>
  );
}

export function RailItem({ icon, label }: { icon: ReactNode; label?: string }) {
  return (
    <span className='flex flex-col items-center gap-1'>
      {icon}
      {label && <span className='whitespace-nowrap'>{label}</span>}
    </span>
  );
}
