'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// sharechat.com tokens; the iPhone card layout follows the App Store listing.
const INK = '#0f172a';
const ICON = '#374151';
const MUTED = '#6b7280';
const LINK = '#2563eb';
const WHATSAPP = '#40c351';
const ACTIVE = '#557efc';

/**
 * ShareChat Home feed in Hindi: striped top edge, logo with language chip, Trending tab, a card with the creator
 * and अभी, caption above the media, and WhatsApp leading the action row.
 */
export default function ShareChatTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.find((item) => item.kind !== 'file');

  return (
    <PhoneFrame scale={scale} background='#f1f1f3' tone='dark' lang='hi' label={`ShareChat preview of the post by ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <div className='h-[3px]' style={{ background: 'linear-gradient(90deg, #ff5a5a, #ffb000, #3ec46d, #4d8dff, #a45cff)' }} />
          <StatusBarSpace />
          <header className='flex h-[46px] items-center gap-3 px-4'>
            <span className='text-[20px] font-extrabold tracking-tight'>ShareChat</span>
            <span className='rounded-full border border-[#e2e8f0] px-2 py-0.5 text-[12px] font-semibold'>文A Hindi</span>
            <span className='ml-auto flex items-center gap-4' style={{ color: ICON }}>
              <AppIcons.search size={23} stroke={2} />
              <AppIcons.coin size={23} stroke={1.8} />
            </span>
          </header>
          <div className='flex h-[38px] items-center gap-5 px-4 text-[15px]'>
            <span className='relative flex h-full items-center font-bold'>
              Trending
              <span className='absolute inset-x-0 bottom-0 h-[3px] rounded-full' style={{ background: INK }} />
            </span>
          </div>
        </div>

        <article className='mx-2 mt-2 flex min-h-0 flex-col gap-2.5 overflow-hidden rounded-[8px] border border-[#e2e8f0] bg-white pt-3'>
          <div className='flex items-center gap-2.5 px-3'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[16px] font-semibold'>{names.display}</p>
              <p className='mt-0.5 text-[12px]' style={{ color: MUTED }}>
                अभी
              </p>
            </div>
            <AppIcons.dotsVertical size={20} stroke={1.8} color={ICON} />
          </div>
          <div className='px-3'>
            <ClampText lines={3} background='#ffffff' className='text-[14px] leading-[22px]'>
              <RichText text={post.text} accent={LINK} className='[&>span]:font-medium' />
            </ClampText>
          </div>
          {media && (
            <div className='shrink-0 bg-[#f1f5f9]'>
              <MediaFill media={media} className='w-full' style={{ height: mediaHeight(media, 377, { min: 0.56, max: 1.25, fallback: 1 }) }} />
            </div>
          )}
          <div className='flex h-[48px] shrink-0 items-center justify-around' style={{ color: ICON }}>
            <AppIcons.whatsapp size={27} stroke={1.8} color={WHATSAPP} />
            <AppIcons.heart size={25} stroke={1.8} />
            <AppIcons.commentRound size={25} stroke={1.8} />
            <AppIcons.download size={25} stroke={1.8} />
          </div>
        </article>
        <div aria-hidden className='min-h-0 flex-1' />

        <TabBar background='#ffffff' border='#e2e8f0'>
          <TabItem color={ACTIVE} icon={<AppIcons.homeFilled size={26} />} />
          <TabItem color={ICON} icon={<AppIcons.search size={26} stroke={2} />} />
          <TabItem color={ICON} icon={<AppIcons.circlePlus size={28} stroke={1.8} />} />
          <TabItem color={ICON} icon={<AppIcons.commentRound size={26} stroke={1.8} />} />
          <TabItem color={ICON} icon={<AppIcons.user size={26} stroke={1.8} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
