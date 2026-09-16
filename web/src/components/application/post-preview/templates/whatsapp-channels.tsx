'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, formatClock, formatTime, MediaFill, mediaHeight, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

// web.whatsapp.com tokens, shared with iOS (light theme).
const WALLPAPER = '#f5f1eb';
const DOODLE = '#eae0d3';
const INK = '#0a0a0a';
const MUTED = 'rgba(0,0,0,0.6)';
const LINK = '#1b8755';

/**
 * A WhatsApp channel as a follower sees it: glass back and more buttons around the channel name, the beige doodle
 * wallpaper, a "Today" chip and the update in a white bubble with its time inside. Followers have no composer.
 */
export default function WhatsAppChannelsTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind !== 'file');
  const time = formatTime(post, 'en-US', { hour: 'numeric', minute: '2-digit' });

  return (
    <PhoneFrame scale={scale} background={WALLPAPER} tone='dark' label={`WhatsApp channel preview of the update from ${names.display}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col' style={{ color: INK }}>
        <div
          aria-hidden
          className='absolute inset-0'
          style={{
            backgroundImage: `radial-gradient(circle at 12px 14px, ${DOODLE} 3px, transparent 3.5px), radial-gradient(circle at 36px 34px, ${DOODLE} 2px, transparent 2.5px)`,
            backgroundSize: '48px 48px'
          }}
        />
        <StatusBarSpace />
        <header className='relative z-10 flex h-[56px] shrink-0 items-center gap-2.5 px-3'>
          <span className='flex size-[40px] items-center justify-center rounded-full bg-white/75 shadow-[0_1px_4px_rgb(0_0_0/0.12)] backdrop-blur'>
            <AppIcons.back size={24} stroke={2.2} />
          </span>
          <Monogram name={names.display} size={36} />
          <div className='min-w-0 flex-1 leading-tight'>
            <p className='truncate text-[16px] font-semibold'>{names.display}</p>
            <p className='text-[13px]' style={{ color: MUTED }}>
              Channel
            </p>
          </div>
          <span className='flex size-[40px] items-center justify-center rounded-full bg-white/75 shadow-[0_1px_4px_rgb(0_0_0/0.12)] backdrop-blur'>
            <AppIcons.dots size={22} stroke={2.2} />
          </span>
        </header>

        <div className='relative z-10 flex min-h-0 flex-1 flex-col items-center gap-2.5 overflow-hidden px-3 pt-2'>
          <span className='rounded-full bg-white/90 px-3 py-1 text-[13px] font-medium shadow-[0_1px_1px_rgb(0_0_0/0.08)]' style={{ color: MUTED }}>
            Today
          </span>
          <div className='w-[340px] self-start overflow-hidden rounded-[18px] bg-white p-[3px] shadow-[0_1px_1px_rgb(0_0_0/0.1)]'>
            {image && <MediaFill media={image} rounded={15} className='w-full' style={{ height: mediaHeight(image, 334, { min: 0.5, max: 1.25, fallback: 1 }) }} />}
            <p className='px-2.5 pt-1.5 pb-1.5 text-[17px] leading-[22px]'>
              <RichText text={post.text} accent={LINK} className='[&>span]:underline' />
              <span className='float-right mt-2 ml-3 text-[12px]' style={{ color: MUTED }}>
                {time}
              </span>
            </p>
          </div>
        </div>
        <div className='h-[34px] shrink-0' />
      </div>
    </PhoneFrame>
  );
}
