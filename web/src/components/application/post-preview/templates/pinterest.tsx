'use client';

import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, mediaHeight, MissingMedia } from '../parts';
import type { TemplateProps } from '../types';

/** Rafii's own approval card. It does not imitate Pinterest's layout or interaction controls. */
export default function PinterestTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind === 'image');
  const height = Math.min(mediaHeight(image, 385, { min: 0.6, max: 1.5, fallback: 1.5 }), 380);
  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Pinterest preview of the pin by ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col gap-4 overflow-hidden px-4 text-[#20201e]' style={{ paddingTop: STATUS_BAR_HEIGHT + 16 }}>
        <div className='flex flex-col gap-1 border-b pb-3'>
          <p className='text-[11px] font-medium uppercase tracking-[0.08em] text-[#696961]'>Rafii review</p>
          <p className='text-[17px] font-medium'>Pinterest image Pin draft</p>
          <p className='text-[12px] text-[#696961]'>{names.display}</p>
        </div>
        <div className='shrink-0 overflow-hidden rounded-[10px]' style={{ height }}>
          {image ? <MediaFill media={image} rounded={10} className='size-full' /> : <MissingMedia need='This Pin needs one image.' className='size-full' />}
        </div>
        <div className='flex flex-col gap-2'>
          {post.pinterestTitle && <p className='text-[23px] leading-[28px] font-medium'>{post.pinterestTitle}</p>}
          {post.text && <ClampText lines={3} background='#ffffff' className='text-[15px] leading-5 text-[#696961]'>{post.text}</ClampText>}
          {post.pinterestBoardId && <p className='text-[11px] text-[#696961]'>Rafii draft · Board ID {post.pinterestBoardId}</p>}
          {post.pinterestSectionId && <p className='text-[11px] text-[#696961]'>Section ID {post.pinterestSectionId}</p>}
          {post.pinterestLink && <div className='rounded-[8px] border p-2'>
            <span className='text-[11px] font-medium'>Destination link</span>
            <p className='mt-1 break-all text-[11px] text-[#696961]'>{post.pinterestLink}</p>
          </div>}
          <p className='text-[10px] text-[#696961]'>Draft preview. Publishing and public visibility require separate confirmation.</p>
        </div>
      </div>
    </PhoneFrame>
  );
}
