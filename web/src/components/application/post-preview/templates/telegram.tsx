'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, formatClock, formatTime, MediaGrid, mediaHeight, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

// Values from TelegramMessenger/Telegram-iOS (Classic day theme, glass redesign of October 2025).
const ACCENT = '#0088ff';
const LINK = '#004bad';
const NAME = '#368ad1';
const FOOTER = 'rgba(82,82,82,0.6)';
const GLASS = 'rgba(255,255,255,0.7)';

/**
 * A Telegram channel as a subscriber sees it: glass header capsule with the channel avatar, the doodle gradient
 * wallpaper, the post in a white bubble (name on text-first posts, photo on top otherwise, time bottom-right),
 * the round share button, and the floating Mute bar.
 */
export default function TelegramTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const files = post.media.filter((item) => item.kind === 'file');
  const time = formatTime(post, 'en-US', { hour: 'numeric', minute: '2-digit' });
  const imageHeight = media.length === 1 ? mediaHeight(media[0], 330, { min: 0.5, max: 1.3, fallback: 1 }) : 330;
  const glass = 'shadow-[0_1px_6px_rgb(0_0_0/0.12)] backdrop-blur-md';

  return (
    <PhoneFrame
      scale={scale}
      background='linear-gradient(155deg, #dbddbb 0%, #88b884 38%, #d5d88d 70%, #6ba587 100%)'
      tone='dark'
      label={`Telegram channel preview of the post by ${names.display}`}
      clock={formatClock(post)}
    >
      <div className='relative flex h-full flex-col text-black'>
        <div
          aria-hidden
          className='absolute inset-0 opacity-[0.16]'
          style={{
            backgroundImage:
              'radial-gradient(circle at 10px 12px, #2d4a2a 1.6px, transparent 2px), radial-gradient(circle at 34px 30px, #2d4a2a 1.2px, transparent 1.7px)',
            backgroundSize: '44px 44px'
          }}
        />
        <StatusBarSpace />
        <header className='relative z-10 flex h-[54px] shrink-0 items-center gap-2 px-2'>
          <span className={`flex size-[44px] items-center justify-center rounded-full ${glass}`} style={{ background: GLASS }}>
            <AppIcons.back size={26} stroke={2.2} />
          </span>
          <span className='flex flex-1 justify-center'>
            <span className={`max-w-[220px] truncate rounded-full px-4 py-2 text-[17px] font-semibold ${glass}`} style={{ background: GLASS }}>
              {names.display}
            </span>
          </span>
          <Monogram name={names.display} size={44} />
        </header>

        <div className='relative z-10 flex min-h-0 flex-1 flex-col items-center gap-2 overflow-hidden px-2 pt-2'>
          <span className='rounded-full px-2.5 py-[3px] text-[13px] font-medium text-white' style={{ background: 'rgba(147,159,171,0.5)' }}>
            {formatTime(post, 'en-US', { month: 'long', day: 'numeric' })}
          </span>
          <div className='flex w-full items-end gap-1.5 self-start'>
            <div className='w-[330px] overflow-hidden rounded-[16px] rounded-bl-[6px] bg-white shadow-[0_1px_1px_rgb(0_0_0/0.1)]'>
              {media.length > 0 && <MediaGrid media={media} height={imageHeight} gap={2} />}
              <div className='px-3 pt-1.5 pb-1.5'>
                {media.length === 0 && (
                  <p className='text-[14px] font-semibold' style={{ color: NAME }}>
                    {names.display}
                  </p>
                )}
                {files.map((file) => (
                  <p key={file.id} className='my-1 flex items-center gap-2.5'>
                    <span className='flex size-[44px] shrink-0 items-center justify-center rounded-full text-white' style={{ background: ACCENT }}>
                      <AppIcons.file size={22} stroke={1.8} />
                    </span>
                    <span className='truncate text-[16px]' style={{ color: '#0b8bed' }}>
                      {file.alt || 'File'}
                    </span>
                  </p>
                ))}
                <p className='text-[17px] leading-[22px]'>
                  <RichText text={post.text} accent={LINK} />
                  <span className='float-right mt-2 ml-3 text-[11px]' style={{ color: FOOTER }}>
                    {time}
                  </span>
                </p>
              </div>
            </div>
            <span className='mb-1 flex size-[30px] shrink-0 items-center justify-center rounded-full bg-black/20 text-white'>
              <AppIcons.forward size={18} stroke={2.2} />
            </span>
          </div>
        </div>

        <div className='relative z-10 flex h-[84px] shrink-0 items-start gap-2 px-2 pt-2'>
          <span className={`flex size-[40px] items-center justify-center rounded-full ${glass}`} style={{ background: GLASS, color: ACCENT }}>
            <AppIcons.gift size={21} stroke={1.9} />
          </span>
          <span className={`flex h-[40px] flex-1 items-center justify-center rounded-full text-[17px] ${glass}`} style={{ background: GLASS, color: ACCENT }}>
            Mute
          </span>
          <span className={`flex size-[40px] items-center justify-center rounded-full ${glass}`} style={{ background: GLASS, color: ACCENT }}>
            <AppIcons.search size={20} stroke={2.2} />
          </span>
        </div>
      </div>
    </PhoneFrame>
  );
}
