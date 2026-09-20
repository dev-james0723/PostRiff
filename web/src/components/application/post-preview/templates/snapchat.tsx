'use client';

import { cn } from '@/lib/utils';
import { AppIcons } from '../app-icons';
import { COVER_MARK, FOLD_MARK, useCaptionFold, useCoverLegend } from '../guides';
import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { accountNames, formatClock, MediaFill, MissingMedia, Monogram, truncateCaption } from '../parts';
import type { TemplateProps } from '../types';

const SPOTLIGHT_RED = '#f2405a';
const MUTED = '#d4d5d6';

/**
 * Snapchat Spotlight (2026): avatar and search on the left, "Spotlight" title, add friend; right column of
 * heart / repost / comment / share / more; creator with Follow, caption and sound; the black five-icon bar with
 * Spotlight active in red.
 */
export default function SnapchatTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const caption = truncateCaption(post.text, 58);
  useCaptionFold(caption, 'more');
  useCoverLegend();
  const shadow = '[filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]';

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' label={`Snapchat Spotlight preview of the snap by ${names.display}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col text-white' style={{ fontFamily: '"Avenir Next", -apple-system, sans-serif' }}>
        <div className='relative min-h-0 flex-1 overflow-hidden'>
          {media[0] ? (
            <MediaFill media={media[0]} className='absolute inset-0' />
          ) : (
            <MissingMedia need='Spotlight needs a vertical video or photo.' dark className='absolute inset-x-6 top-[160px] bottom-[220px] rounded-2xl' />
          )}
          <div className='absolute inset-x-0 top-0 h-[140px] bg-gradient-to-b from-black/45 to-transparent' />
          <div className='absolute inset-x-0 bottom-0 h-[260px] bg-gradient-to-t from-black/65 to-transparent' />

          <div className={cn('absolute inset-x-0 flex h-[48px] items-center justify-between px-3', shadow, COVER_MARK)} style={{ top: STATUS_BAR_HEIGHT }}>
            <span className='flex items-center gap-2'>
              <Monogram name={names.display} size={34} />
              <span className='flex size-[34px] items-center justify-center rounded-full bg-white/20'>
                <AppIcons.search size={19} stroke={2.2} />
              </span>
            </span>
            <span className='text-[19px] font-bold'>Spotlight</span>
            <span className='flex size-[34px] items-center justify-center rounded-full bg-white/20'>
              <AppIcons.userPlus size={19} stroke={2.2} />
            </span>
          </div>

          <div className={cn('absolute right-2 bottom-[18px] flex w-[56px] flex-col items-center gap-[20px] text-[12px] font-semibold', shadow, COVER_MARK)}>
            <AppIcons.heart size={32} stroke={2} />
            <AppIcons.repeat size={31} stroke={2} />
            <AppIcons.commentRound size={31} stroke={2} />
            <AppIcons.forward size={32} stroke={2} />
            <AppIcons.dots size={28} stroke={2.2} />
          </div>

          <div className={cn('absolute bottom-[18px] left-3 w-[292px]', shadow, COVER_MARK)}>
            <p className='flex items-center gap-2 text-[15px] font-bold'>
              <Monogram name={names.display} size={28} />
              {names.display}
              <span className='rounded-full bg-white px-3 py-1 text-[13px] font-bold text-black'>Follow</span>
            </p>
            <p className='mt-2 text-[17px] leading-[22px] font-semibold'>
              {caption.text}
              {caption.cut && (
                <>
                  {' '}
                  <span className={cn('font-normal', FOLD_MARK)} style={{ color: MUTED }}>
                    more
                  </span>
                </>
              )}
            </p>
            <p className='mt-2 flex items-center gap-1.5 text-[13px] text-white/80'>
              <AppIcons.music size={14} stroke={2} />
              <span className='truncate'>Original sound · {names.display}</span>
            </p>
          </div>
        </div>
        <nav className='flex h-[83px] shrink-0 items-start justify-around bg-black px-2 pt-[9px] text-white/80'>
          <AppIcons.pin size={27} stroke={1.9} />
          <AppIcons.commentRound size={27} stroke={1.9} />
          <AppIcons.camera size={27} stroke={1.9} />
          <AppIcons.users size={27} stroke={1.9} />
          <span className='flex flex-col items-center gap-1' style={{ color: SPOTLIGHT_RED }}>
            <AppIcons.play size={27} />
            <span className='size-[5px] rounded-full' style={{ background: SPOTLIGHT_RED }} />
          </span>
        </nav>
      </div>
    </PhoneFrame>
  );
}
