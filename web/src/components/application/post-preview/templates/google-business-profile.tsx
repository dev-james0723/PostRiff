'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

// Sampled from 2026 Google Maps screenshots (light).
const INK = '#1f1f1f';
const MUTED = '#5a5a5a';
const TEAL = '#03798d';

/**
 * The business's place sheet in Google Maps, Updates tab: name with Save / Share / close, the tab row with Updates
 * active, By owner and By visitors chips, and the owner's post card (logo, name, time, image, text with "more").
 */
export default function GoogleBusinessProfileTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind === 'image');

  return (
    <PhoneFrame scale={scale} background='#d9dde1' tone='dark' label={`Google Maps preview of the update from ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK, fontFamily: 'Roboto, -apple-system, "Helvetica Neue", Arial, sans-serif' }}>
        <div aria-hidden className='h-[118px] shrink-0' style={{ background: 'linear-gradient(135deg, #e8eaed 25%, #dfe3e7 25%, #dfe3e7 50%, #e8eaed 50%, #e8eaed 75%, #dfe3e7 75%)', backgroundSize: '56px 56px' }} />
        <section className='flex min-h-0 flex-1 flex-col overflow-hidden rounded-t-[28px] bg-white shadow-[0_-2px_12px_rgb(0_0_0/0.15)]'>
          <span className='mx-auto mt-2 h-[4px] w-[36px] shrink-0 rounded-full bg-[#c4c7c5]' />
          <div className='flex items-start gap-2 px-4 pt-3'>
            <p className='min-w-0 flex-1 text-[26px] leading-8'>{names.display}</p>
            {[AppIcons.bookmark, AppIcons.share, AppIcons.close].map((Icon, index) => (
              <span key={index} className='flex size-[38px] shrink-0 items-center justify-center rounded-full bg-[#f0f2f3]'>
                <Icon size={19} stroke={2} />
              </span>
            ))}
          </div>
          <div className='mt-3 flex h-[46px] shrink-0 gap-5 overflow-hidden border-b border-[#e3e3e3] px-4 text-[14px] font-medium whitespace-nowrap' style={{ color: MUTED }}>
            <span className='flex items-center'>Overview</span>
            <span className='flex items-center'>Menu</span>
            <span className='flex items-center'>Reviews</span>
            <span className='flex items-center'>Photos</span>
            <span className='relative flex items-center' style={{ color: TEAL }}>
              Updates
              <span className='absolute inset-x-0 bottom-0 h-[3px] rounded-t-full' style={{ background: TEAL }} />
            </span>
            <span className='flex items-center'>About</span>
          </div>
          <div className='flex gap-2 px-4 pt-3 text-[14px] font-medium'>
            <span className='rounded-[8px] bg-[#e8eaed] px-3 py-1.5'>By owner</span>
            <span className='rounded-[8px] border border-[#c7c7c7] px-3 py-1.5' style={{ color: MUTED }}>
              By visitors
            </span>
          </div>

          <article className='flex min-h-0 flex-1 flex-col gap-3 overflow-hidden pt-4'>
            <div className='flex items-center gap-3 px-4'>
              <Monogram name={names.display} size={40} />
              <div className='min-w-0 flex-1 leading-tight'>
                <p className='truncate text-[16px] font-medium'>{names.display}</p>
                <p className='text-[14px]' style={{ color: MUTED }}>
                  Just now
                </p>
              </div>
              <AppIcons.share size={21} stroke={1.9} color={MUTED} />
              <AppIcons.dotsVertical size={21} stroke={1.9} color={MUTED} />
            </div>
            {image && <MediaFill media={image} className='h-[262px] w-full shrink-0' />}
            <div className='px-4'>
              <ClampText lines={2} background='#ffffff' className='text-[14px] leading-5' more={<span className='underline' style={{ color: TEAL }}>… more</span>}>
                <RichText text={post.text} accent={TEAL} />
              </ClampText>
            </div>
          </article>
        </section>
      </div>
    </PhoneFrame>
  );
}
