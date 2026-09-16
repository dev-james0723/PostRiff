'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, formatClock, formatTime, MediaFill, mediaHeight, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

// Discord's live style sheets; mobile themes match desktop since the August 2026 refresh (Dark theme).
const BG = '#1a1a1e';
const TEXT = '#efeff1';
const NAME = '#fbfbfb';
const MUTED = '#96979e';
const LINK = '#4d96ee';
const FIELD = '#222327';

/** A Discord announcement channel on iPhone (dark): megaphone channel header, the message with its time and image, the composer. */
export default function DiscordTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind !== 'file');
  const time = formatTime(post, 'en-US', { hour: 'numeric', minute: '2-digit' });

  return (
    <PhoneFrame scale={scale} background={BG} tone='light' label={`Discord preview of the message from ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: TEXT }}>
        <StatusBarSpace />
        <header className='flex h-[48px] shrink-0 items-center gap-2 border-b border-white/5 px-3'>
          <AppIcons.arrowLeft size={24} stroke={2} color={MUTED} />
          <span className='flex min-w-0 flex-1 items-center gap-1 text-[17px] font-bold text-white'>
            <AppIcons.speakerphone size={20} stroke={2} color={MUTED} />
            <span className='truncate'>announcements</span>
          </span>
          <AppIcons.users size={24} stroke={1.8} color={MUTED} />
          <AppIcons.search size={23} stroke={2} color={MUTED} />
        </header>

        <div className='flex min-h-0 flex-1 flex-col justify-end overflow-hidden pb-2'>
          <div className='flex gap-3 px-3 py-2'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1'>
              <p className='flex items-baseline gap-2'>
                <span className='truncate text-[16px] font-semibold' style={{ color: NAME }}>
                  {names.display}
                </span>
                <span className='shrink-0 text-[12px]' style={{ color: MUTED }}>
                  Today at {time}
                </span>
              </p>
              <p className='text-[16px] leading-[22px]'>
                <RichText text={post.text} accent={LINK} />
              </p>
              {image && (
                <MediaFill
                  media={image}
                  rounded={8}
                  className='mt-2 w-[290px]'
                  style={{ height: mediaHeight(image, 290, { min: 0.5, max: 1.2, fallback: 0.75 }) }}
                />
              )}
            </div>
          </div>
        </div>

        <div className='flex h-[92px] shrink-0 items-start gap-2 px-3 pt-2'>
          <span className='flex size-[40px] items-center justify-center rounded-[12px]' style={{ color: MUTED, background: FIELD }}>
            <AppIcons.plus size={22} stroke={2} />
          </span>
          <span className='flex h-[40px] flex-1 items-center justify-between rounded-[12px] px-3 text-[15px]' style={{ color: MUTED, background: FIELD }}>
            Message #announcements
            <span className='flex items-center gap-2.5'>
              <AppIcons.smile size={21} stroke={1.8} />
              <AppIcons.gift size={21} stroke={1.8} />
            </span>
          </span>
          <span className='flex size-[40px] items-center justify-center rounded-[12px]' style={{ color: MUTED, background: FIELD }}>
            <AppIcons.mic size={21} stroke={1.8} />
          </span>
        </div>
      </div>
    </PhoneFrame>
  );
}
