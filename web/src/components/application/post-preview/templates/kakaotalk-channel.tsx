'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, formatClock, formatTime, MediaFill, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

// Kakao Business message guides and KakaoTalk 26.8 mockups.
const CHAT_BG = '#abc1d1';
const INK = '#000000';
const NAME = '#535b61';
const BUTTON = '#f5f5f5';

/**
 * A KakaoTalk Channel message in the subscriber's chat room: transparent header with the verified channel name,
 * blue-grey background, rounded-square profile, and the message card (image across the top at 4:3, text, share
 * button) with its time. Broadcast-only channels have no input bar.
 */
export default function KakaoTalkChannelTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind === 'image');
  const time = formatTime(post, 'ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });

  return (
    <PhoneFrame scale={scale} background={CHAT_BG} tone='dark' lang='ko' label={`카카오톡 채널 미리보기: ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='relative flex h-[48px] shrink-0 items-center justify-center px-2'>
          <AppIcons.back size={28} stroke={2.2} color='#111111' className='absolute left-2' />
          <span className='flex max-w-[220px] items-center gap-1 text-[17px] font-bold text-[#111111]'>
            <span className='truncate'>{names.display}</span>
            <span className='flex size-[15px] shrink-0 items-center justify-center rounded-full bg-[#9aa3aa] text-white'>
              <AppIcons.check size={10} stroke={3.4} />
            </span>
          </span>
          <span className='absolute right-3 flex items-center gap-4 text-[#111111]'>
            <AppIcons.search size={23} stroke={2} />
            <AppIcons.menu size={24} stroke={2} />
          </span>
        </header>

        <div className='flex min-h-0 flex-1 flex-col gap-2 overflow-hidden px-3 pt-2'>
          <span className='self-center rounded-full bg-black/15 px-3 py-0.5 text-[12px] text-white'>
            {formatTime(post, 'ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' })}
          </span>
          <div className='flex gap-2'>
            <Monogram name={names.display} size={36} shape='rounded' />
            <div className='flex min-w-0 flex-col gap-1.5'>
              <p className='text-[13px]' style={{ color: NAME }}>
                {names.display}
              </p>
              <div className='relative w-[250px] overflow-hidden rounded-[11px] bg-white'>
                {image && <MediaFill media={image} className='h-[188px] w-full' />}
                <span className='absolute top-2 right-2 flex size-[28px] items-center justify-center rounded-full bg-white shadow-[0_1px_3px_rgb(0_0_0/0.18)]'>
                  <AppIcons.home size={15} stroke={2} />
                </span>
                <p className='px-3 pt-2.5 pb-3 text-[15px] leading-[21px]'>
                  <RichText text={post.text} accent='#1a66d2' />
                </p>
                <div className='px-3 pb-3'>
                  <span className='flex h-[38px] items-center justify-center rounded-[6px] text-[14px] text-[#111111]' style={{ background: BUTTON }}>
                    공유하기
                  </span>
                </div>
              </div>
              <span className='self-end text-[11px]' style={{ color: NAME }}>
                {time}
              </span>
            </div>
          </div>
        </div>
        <div className='h-[34px] shrink-0' />
      </div>
    </PhoneFrame>
  );
}
