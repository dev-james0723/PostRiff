'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, formatClock, formatTime, MediaFill, mediaHeight, Monogram, RichText } from '../parts';
import type { TemplateProps } from '../types';

// LINE 26.15 official-account talk room (LY Corporation release images and guides).
const CHAT_BG = '#8cabd8';
const INK = '#000000';
const NAME = '#363f4d';
const TIME = '#404e62';
const STATUS = '#797979';

/**
 * A LINE Official Account broadcast in the follower's talk room: white header with the account name and its
 * automated-reply status, sky-blue background, round avatar with the name above white bubbles, times beside
 * them, and the message input.
 */
export default function LineOfficialAccountTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const image = post.media.find((item) => item.kind === 'image');
  const time = formatTime(post, 'ja-JP', { hour: '2-digit', minute: '2-digit', hour12: false });

  return (
    <PhoneFrame scale={scale} background={CHAT_BG} tone='dark' lang='ja' label={`LINE公式アカウントのプレビュー：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <StatusBarSpace />
          <header className='flex h-[52px] items-center gap-1 px-2'>
            <AppIcons.back size={28} stroke={2.2} color='#111111' />
            <span className='min-w-0 flex-1 leading-tight'>
              <span className='block truncate text-[17px] font-bold text-[#111111]'>{names.display}</span>
              <span className='block truncate text-[11px]' style={{ color: STATUS }}>
                自動で送信しています
              </span>
            </span>
            <span className='flex items-center gap-4 pr-2 text-[#111111]'>
              <AppIcons.search size={23} stroke={2} />
              <AppIcons.phone size={23} stroke={2} />
              <AppIcons.menu size={24} stroke={2} />
            </span>
          </header>
        </div>

        <div className='flex min-h-0 flex-1 flex-col gap-2 overflow-hidden px-3 pt-3'>
          <span className='self-center rounded-full bg-black/15 px-3 py-0.5 text-[12px] text-white'>今日</span>
          <div className='flex gap-2'>
            <Monogram name={names.display} size={30} />
            <div className='flex min-w-0 flex-col gap-1.5'>
              <p className='text-[12px]' style={{ color: NAME }}>
                {names.display}
              </p>
              <div className='flex items-end gap-1.5'>
                <p className='max-w-[260px] rounded-[12px] rounded-tl-[4px] bg-white px-3 py-2 text-[16px] leading-[23px]'>
                  <RichText text={post.text} accent='#2d6be4' />
                </p>
                <span className='shrink-0 text-[11px]' style={{ color: TIME }}>
                  {time}
                </span>
              </div>
              {image && (
                <div className='flex items-end gap-1.5'>
                  <MediaFill media={image} rounded={12} className='w-[240px]' style={{ height: mediaHeight(image, 240, { min: 0.5, max: 1.4, fallback: 1 }) }} />
                  <span className='shrink-0 text-[11px]' style={{ color: TIME }}>
                    {time}
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className='flex h-[88px] shrink-0 items-start gap-3 bg-white px-3 pt-2.5 text-[#8e8e93]'>
          <AppIcons.chevronRight size={26} stroke={2} />
          <span className='flex h-[36px] flex-1 items-center justify-between rounded-full px-3 text-[15px]' style={{ background: '#f5f5f6' }}>
            メッセージを入力
            <AppIcons.smile size={21} stroke={1.8} />
          </span>
          <AppIcons.mic size={25} stroke={1.8} />
        </div>
      </div>
    </PhoneFrame>
  );
}
