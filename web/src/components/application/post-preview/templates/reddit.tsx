'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { accountNames, ClampText, firstLine, formatClock, MediaFill, mediaHeight, Monogram, restAfterFirstLine, RichText } from '../parts';
import type { TemplateProps } from '../types';

// Reddit web tokens and App Store pixels (light).
const INK = '#0f1a1c';
const BODY = '#2a3c42';
const MUTED = '#576f76';
const LINK = '#0045ac';
const GLASS = 'rgba(255,255,255,0.72)';

/**
 * Reddit Home feed in the iOS 26 glass design (May 2026): floating menu / Search Reddit / create controls, a card
 * headed by its community, bold title, text or media, the outlined vote and comment pills, and the floating
 * Home / Inbox / You bar.
 */
export default function RedditTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const community = /^r\//i.test(post.account.trim()) ? post.account.trim() : `u/${names.handle}`;
  const title = firstLine(post.text);
  const body = restAfterFirstLine(post.text);
  const image = post.media.find((item) => item.kind !== 'file');
  const glass = 'border border-black/5 shadow-[0_2px_10px_rgb(0_0_0/0.12)] backdrop-blur-md';

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Reddit preview of the post in ${community}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col' style={{ color: INK }}>
        <div className='absolute inset-x-0 z-10 flex h-[52px] items-center gap-2 px-3' style={{ top: STATUS_BAR_HEIGHT }}>
          <span className={`flex size-[44px] items-center justify-center rounded-full ${glass}`} style={{ background: GLASS }}>
            <AppIcons.menu size={22} stroke={2} />
          </span>
          <span className={`flex h-[44px] flex-1 items-center gap-2 rounded-full px-3 text-[15px] ${glass}`} style={{ background: GLASS, color: MUTED }}>
            <span className='flex size-[24px] items-center justify-center rounded-full bg-[#ff4500] text-white'>
              <AppIcons.smile size={16} stroke={2.2} />
            </span>
            Search Reddit
          </span>
          <span className={`flex size-[44px] items-center justify-center rounded-full ${glass}`} style={{ background: GLASS }}>
            <AppIcons.plus size={22} stroke={2.2} />
          </span>
        </div>

        <article className='flex min-h-0 flex-1 flex-col gap-2 overflow-hidden px-4' style={{ paddingTop: STATUS_BAR_HEIGHT + 64 }}>
          <p className='flex items-center gap-2 text-[13px]'>
            <Monogram name={community} size={24} />
            <span className='font-semibold'>{community}</span>
            <span style={{ color: MUTED }}>now</span>
            <AppIcons.dots size={20} className='ml-auto' color={MUTED} />
          </p>
          <p className='text-[17px] leading-[22px] font-medium'>{title}</p>
          {image ? (
            <MediaFill media={image} rounded={12} className='w-full shrink-0' style={{ height: mediaHeight(image, 361, { min: 0.56, max: 1.2, fallback: 1 }) }} />
          ) : (
            body && (
              <ClampText lines={3} background='#ffffff' className='text-[14px] leading-5' style={{ color: BODY }}>
                <RichText text={body} accent={LINK} />
              </ClampText>
            )
          )}
          <div className='mt-1 flex items-center gap-2 text-[13px] font-semibold' style={{ color: INK }}>
            <span className='flex h-[34px] items-center gap-1.5 rounded-full border border-black/10 px-2.5'>
              <AppIcons.upvote size={19} stroke={1.8} />
              Vote
              <AppIcons.downvote size={19} stroke={1.8} />
            </span>
            <span className='flex h-[34px] items-center gap-1.5 rounded-full border border-black/10 px-3'>
              <AppIcons.comment size={19} stroke={1.8} />
              Comment
            </span>
            <span className='ml-auto flex size-[34px] items-center justify-center rounded-full border border-black/10'>
              <AppIcons.forward size={19} stroke={1.8} />
            </span>
          </div>
        </article>

        <div className='flex h-[92px] shrink-0 items-start justify-center pt-1'>
          <span className={`flex h-[58px] items-center gap-1 rounded-full p-1 ${glass}`} style={{ background: GLASS }}>
            <span className='flex h-full flex-col items-center justify-center gap-0.5 rounded-full bg-black/[0.06] px-5 text-[10px] font-semibold'>
              <AppIcons.homeFilled size={23} />
              Home
            </span>
            <span className='flex h-full flex-col items-center justify-center gap-0.5 px-5 text-[10px] font-semibold' style={{ color: MUTED }}>
              <AppIcons.bell size={23} stroke={1.8} />
              Inbox
            </span>
            <span className='flex h-full flex-col items-center justify-center gap-0.5 px-5 text-[10px] font-semibold' style={{ color: MUTED }}>
              <Monogram name={names.display} size={23} />
              You
            </span>
          </span>
        </div>
      </div>
    </PhoneFrame>
  );
}
