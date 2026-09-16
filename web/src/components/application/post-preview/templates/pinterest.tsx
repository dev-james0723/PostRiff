'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { accountNames, ClampText, firstLine, formatClock, MediaFill, mediaHeight, MissingMedia, Monogram, restAfterFirstLine } from '../parts';
import type { TemplateProps } from '../types';

// Pinterest Gestalt tokens (light).
const INK = '#000000';
const SUBTLE = '#636361';
const RED = '#e60023';

/**
 * Pinterest pin close-up (no top or tab bar): rounded hero image with back and visual-search buttons, heart /
 * comment / share / more beside the red Save, the creator, title, description with "See more", and a Visit site
 * bar when the pin carries a link.
 */
export default function PinterestTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind !== 'file');
  const height = Math.min(mediaHeight(image, 385, { min: 0.6, max: 1.5, fallback: 1.5 }), 500);
  const title = firstLine(post.text);
  const description = restAfterFirstLine(post.text);
  const link = /https?:\/\//.test(post.text);

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Pinterest preview of the pin by ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col overflow-hidden px-1' style={{ color: INK, paddingTop: STATUS_BAR_HEIGHT }}>
        <div className='relative shrink-0' style={{ height }}>
          {image ? <MediaFill media={image} rounded={16} className='size-full' /> : <MissingMedia need='Pins need an image or video.' className='size-full rounded-[16px]' />}
          <span className='absolute top-3 left-3 flex size-[40px] items-center justify-center rounded-[12px] bg-white'>
            <AppIcons.back size={24} stroke={2.4} />
          </span>
          <span className='absolute right-3 bottom-3 flex size-[40px] items-center justify-center rounded-[12px] bg-white'>
            <AppIcons.search size={21} stroke={2.4} />
          </span>
        </div>
        <div className='flex h-[64px] shrink-0 items-center gap-5 px-3'>
          <AppIcons.heart size={27} stroke={1.9} />
          <AppIcons.commentRound size={27} stroke={1.9} />
          <AppIcons.forward size={27} stroke={1.9} />
          <AppIcons.dots size={27} stroke={1.9} />
          <span className='ml-auto flex h-[48px] items-center rounded-[16px] px-5 text-[16px] font-semibold text-white' style={{ background: RED }}>
            Save
          </span>
        </div>
        <div className='flex flex-col gap-2 px-3'>
          <p className='flex items-center gap-2 text-[16px] font-medium'>
            <Monogram name={names.display} size={20} />
            {names.display}
          </p>
          {title && <p className='text-[23px] leading-[28px] font-medium'>{title}</p>}
          {description && (
            <ClampText lines={2} background='#ffffff' className='text-[15px] leading-5' style={{ color: SUBTLE }} more={<span className='font-semibold text-black'>See more</span>}>
              {description}
            </ClampText>
          )}
          {link && <span className='mt-1 flex h-[48px] items-center justify-center rounded-[16px] bg-[#e8e7e1] text-[16px] font-semibold'>Visit site</span>}
        </div>
      </div>
    </PhoneFrame>
  );
}
