'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, mediaHeight, MissingMedia, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// Values from pixelfed/pixelfed-rn at tag v1.8.0.
const INK = '#000000';
const MUTED = '#555555';
const BORDER = '#e0e0e0';
const LINK = '#2b7fff';
const ACTIVE = '#007aff';

/**
 * Pixelfed for iOS: "Pixelfed" wordmark with globe / mail / search, a post header (45pt avatar, username over
 * display name), edge-to-edge media with album dots, heart and comment with boost and bookmark on the right,
 * caption cut at three lines with "View More", "Public · Just now".
 */
export default function PixelfedTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const first = media[0];
  const height = mediaHeight(first, 393, { min: 0.5, max: 1.25, fallback: 1 });

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Pixelfed preview of the post by ${names.handle}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[48px] shrink-0 items-center justify-between px-4'>
          <span className='text-[25px] font-bold tracking-tight'>Pixelfed</span>
          <span className='flex items-center gap-4'>
            <AppIcons.globe size={26} stroke={1.7} />
            <AppIcons.mail size={26} stroke={1.7} />
            <AppIcons.search size={26} stroke={1.9} />
          </span>
        </header>

        <article className='flex min-h-0 flex-1 flex-col overflow-hidden border-t' style={{ borderColor: BORDER }}>
          <div className='flex h-[62px] shrink-0 items-center gap-2.5 px-3'>
            <Monogram name={names.display} size={45} style={{ boxShadow: `0 0 0 1px ${BORDER}` }} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[16px] font-bold'>{names.handle}</p>
              <p className='truncate text-[13px] font-light' style={{ color: MUTED }}>
                {names.display}
              </p>
            </div>
            <AppIcons.dots size={22} stroke={2} />
          </div>
          <div className='relative shrink-0 bg-black' style={{ height }}>
            {first ? <MediaFill media={first} className='size-full' /> : <MissingMedia need='Pixelfed posts need a photo.' className='size-full' />}
          </div>
          {media.length > 1 && (
            <div className='flex h-[18px] shrink-0 items-center justify-center gap-1.5'>
              {media.map((item, index) => (
                <span key={item.id} className='size-[7px] rounded-full' style={{ background: index === 0 ? '#408df6' : '#d0d0d0' }} />
              ))}
            </div>
          )}
          <div className='flex h-[44px] shrink-0 items-center gap-4 px-3'>
            <AppIcons.heart size={26} stroke={1.8} />
            <AppIcons.commentRound size={26} stroke={1.8} />
            <span className='ml-auto flex items-center gap-4'>
              <AppIcons.repeat size={26} stroke={1.8} />
              <AppIcons.bookmark size={26} stroke={1.8} />
            </span>
          </div>
          <div className='px-3 text-[16px] leading-[22px]'>
            <ClampText lines={3} background='#ffffff'>
              <span className='font-bold'>{names.handle}</span> <RichText text={post.text} accent={LINK} />
            </ClampText>
            <p className='mt-1.5 text-[13px]' style={{ color: MUTED }}>
              Public · Just now
            </p>
          </div>
        </article>

        <TabBar background='#ffffff' border={BORDER}>
          <TabItem color={ACTIVE} icon={<AppIcons.homeFilled size={27} />} />
          <TabItem color={INK} icon={<AppIcons.compass size={27} stroke={1.8} />} />
          <TabItem color={INK} icon={<AppIcons.camera size={27} stroke={1.8} />} />
          <TabItem color={INK} icon={<AppIcons.bell size={27} stroke={1.8} />} />
          <TabItem color={INK} icon={<AppIcons.user size={27} stroke={1.8} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
