'use client';

import { CHANNEL_ICONS } from '@/components/channel-icon';
import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, BrandGlyph, ClampText, formatClock, MediaFill, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

/** For channels without their own template: a plain feed card under the channel's mark. */
export default function GenericTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const brand = CHANNEL_ICONS[post.channel];

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`${post.channelName} post preview`} clock={formatClock(post)}>
      <div className='flex h-full flex-col text-[#1c1c1e]'>
        <StatusBarSpace />
        <div className='flex h-[48px] items-center justify-between border-b border-[#e5e5ea] px-4'>
          <AppIcons.back size={26} stroke={2} />
          <span className='flex items-center gap-2 text-[17px] font-semibold'>
            <BrandGlyph path={brand?.path} size={20} color={brand?.color ?? '#1c1c1e'} />
            {post.channelName}
          </span>
          <AppIcons.dots size={24} stroke={2} />
        </div>
        <article className='flex flex-col gap-3 px-4 pt-4'>
          <div className='flex items-center gap-3'>
            <Monogram name={names.display} size={42} />
            <div className='min-w-0'>
              <p className='truncate text-[16px] font-semibold'>{names.display}</p>
              <p className='text-[13px] text-[#8e8e93]'>Just now</p>
            </div>
          </div>
          <ClampText lines={8} background='#ffffff' className='text-[16px] leading-[22px]' more={<span className='text-[16px] text-[#8e8e93]'>… more</span>}>
            <RichText text={post.text} accent='#007aff' />
          </ClampText>
          {post.media[0] && <MediaFill media={post.media[0]} rounded={12} className='h-[300px] w-full' />}
        </article>
      </div>
    </PhoneFrame>
  );
}
