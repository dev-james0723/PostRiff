'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, MediaGrid, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// Facebook web tokens, which the iOS app shares (light theme).
const INK = '#080809';
const MUTED = '#65686c';
const LINE = '#d0d3d7';
const LINK = '#0064d1';
const BLUE = '#0866ff';
const FEED = '#f2f4f7';

/**
 * Facebook Home feed after the December 2025 redesign: menu and blue wordmark with create / search / Messenger,
 * a Page post (name, "Just now · globe", text with "See more", edge-to-edge media), like / comment / share icons
 * that carry counts instead of labels, and the labelled six-tab bar.
 */
export default function FacebookTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const single = media.length === 1 ? mediaHeight(media[0], 393, { min: 0.5, max: 1.25, fallback: 1 }) : 0;

  return (
    <PhoneFrame scale={scale} background={FEED} tone='dark' label={`Facebook preview of the post by ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <StatusBarSpace />
          <header className='flex h-[48px] items-center gap-2 px-3'>
            <AppIcons.menu size={26} stroke={2} />
            <span className='text-[30px] font-bold tracking-[-1.2px]' style={{ color: BLUE, fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif' }}>
              facebook
            </span>
            <span className='ml-auto flex items-center gap-4'>
              <span className='flex size-[26px] items-center justify-center rounded-[7px] border-2 border-current'>
                <AppIcons.plus size={16} stroke={2.6} />
              </span>
              <AppIcons.search size={25} stroke={2.2} />
              <AppIcons.messenger size={26} stroke={2} />
            </span>
          </header>
        </div>

        <article className='mt-2 flex min-h-0 flex-col overflow-hidden bg-white'>
          <div className='flex items-center gap-2 px-3 pt-3'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[15px] font-semibold'>{names.display}</p>
              <p className='mt-0.5 flex items-center gap-1 text-[13px]' style={{ color: MUTED }}>
                Just now · <AppIcons.globe size={12} stroke={2} />
              </p>
            </div>
            <span className='flex gap-4' style={{ color: MUTED }}>
              <AppIcons.dots size={22} />
              <AppIcons.close size={22} />
            </span>
          </div>
          <div className='px-3 pt-2 pb-2.5'>
            <ClampText lines={5} background='#ffffff' className='text-[15px] leading-5' more={<span style={{ color: MUTED }}>… See more</span>}>
              <RichText text={post.text} accent={LINK} />
            </ClampText>
          </div>
          {media.length === 1 && <MediaFill media={media[0]} crop='tall' className='w-full shrink-0' style={{ height: single }} />}
          {media.length > 1 && <MediaGrid media={media} height={393} gap={2} />}
          <div className='flex h-[46px] shrink-0 items-center gap-7 px-4' style={{ color: MUTED }}>
            <AppIcons.thumbUp size={22} stroke={1.8} />
            <AppIcons.comment size={22} stroke={1.8} />
            <AppIcons.forward size={22} stroke={1.8} />
          </div>
        </article>
        <div aria-hidden className='min-h-0 flex-1' />

        <TabBar background='#ffffff' border={LINE} className='px-0'>
          <TabItem className='min-w-0 flex-1' color={BLUE} label='Home' icon={<AppIcons.homeFilled size={25} />} />
          <TabItem className='min-w-0 flex-1' color={MUTED} label='Friends' icon={<AppIcons.users size={25} stroke={1.8} />} />
          <TabItem className='min-w-0 flex-1' color={MUTED} label='Reels' icon={<AppIcons.movie size={25} stroke={1.8} />} />
          <TabItem className='min-w-0 flex-1' color={MUTED} label='Marketplace' icon={<AppIcons.store size={25} stroke={1.8} />} />
          <TabItem className='min-w-0 flex-1' color={MUTED} label='Notifications' icon={<AppIcons.bell size={25} stroke={1.8} />} />
          <TabItem className='min-w-0 flex-1' color={MUTED} label='Profile' icon={<Monogram name={names.display} size={25} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
