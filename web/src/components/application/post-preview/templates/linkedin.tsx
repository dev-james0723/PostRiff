'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, MediaGrid, mediaHeight, Monogram, RichText, TabBar } from '../parts';
import type { TemplateProps } from '../types';

// App Store pixels and LinkedIn's web tokens (light).
const INK = 'rgba(0,0,0,0.9)';
const MUTED = '#666666';
const LINK = '#0a66c2';
const FEED = '#eae6df';
const DIVIDER = 'rgba(0,0,0,0.08)';

/**
 * LinkedIn Home feed: avatar / Search pill / messaging header, a white card on the beige feed (name, time and
 * globe, text cut at three lines with "…more", media up to 4:5), the Like / Comment / Repost / Send bar, and the
 * labelled tab bar with the active tab marked on its top edge.
 */
export default function LinkedInTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const single = media.length === 1 ? mediaHeight(media[0], 393, { min: 0.5, max: 1.25, fallback: 1 }) : 0;

  return (
    <PhoneFrame scale={scale} background={FEED} tone='dark' label={`LinkedIn preview of the post by ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <StatusBarSpace />
          <header className='flex h-[50px] items-center gap-3 px-3'>
            <Monogram name={names.display} size={32} />
            <span className='flex h-[34px] flex-1 items-center gap-2 rounded-full border border-[#8c8c8c] px-3 text-[15px]' style={{ color: MUTED }}>
              <AppIcons.search size={18} stroke={2} />
              Search
            </span>
            <AppIcons.messages size={26} stroke={1.7} color={MUTED} />
          </header>
        </div>

        <article className='mt-2 flex min-h-0 flex-col overflow-hidden bg-white'>
          <div className='flex gap-2 px-3 pt-3'>
            <Monogram name={names.display} size={48} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[15px] font-semibold'>{names.display}</p>
              <p className='mt-1 flex items-center gap-1 text-[12px]' style={{ color: MUTED }}>
                Now • <AppIcons.globe size={13} stroke={1.8} />
              </p>
            </div>
            <AppIcons.dots size={22} color={MUTED} />
          </div>
          <div className='px-3 pt-2'>
            <ClampText lines={3} background='#ffffff' className='text-[14px] leading-5' more={<span style={{ color: MUTED }}>…more</span>}>
              <RichText text={post.text} accent={LINK} />
            </ClampText>
          </div>
          {media.length === 1 && <MediaFill media={media[0]} className='mt-2 w-full shrink-0' style={{ height: single }} />}
          {media.length > 1 && <MediaGrid media={media} height={393} gap={3} className='mt-2' />}
          <div className='mx-3 flex h-[64px] shrink-0 items-center justify-around border-t' style={{ color: MUTED, borderColor: DIVIDER }}>
            {[
              [AppIcons.thumbUp, 'Like'],
              [AppIcons.comment, 'Comment'],
              [AppIcons.repeat, 'Repost'],
              [AppIcons.send, 'Send']
            ].map(([Glyph, label]) => {
              const Icon = Glyph as typeof AppIcons.send;
              return (
                <span key={label as string} className='flex flex-col items-center gap-1 text-[12px] font-semibold'>
                  <Icon size={22} stroke={1.7} className={label === 'Comment' ? '-scale-x-100' : undefined} />
                  {label as string}
                </span>
              );
            })}
          </div>
        </article>
        <div aria-hidden className='min-h-0 flex-1' />

        <TabBar background='#ffffff' border={DIVIDER} className='px-0 pt-0'>
          {[
            [AppIcons.homeFilled, 'Home', true],
            [AppIcons.video, 'Video', false],
            [AppIcons.users, 'My Network', false],
            [AppIcons.bell, 'Notifications', false],
            [AppIcons.briefcase, 'Jobs', false]
          ].map(([Glyph, label, active]) => {
            const Icon = Glyph as typeof AppIcons.bell;
            return (
              <span
                key={label as string}
                className='flex min-w-0 flex-1 flex-col items-center gap-[3px] border-t-2 pt-[6px] text-[10px] font-medium'
                style={{ color: active ? '#000000' : MUTED, borderColor: active ? '#000000' : 'transparent' }}
              >
                <Icon size={24} stroke={active ? 2 : 1.7} />
                {label as string}
              </span>
            );
          })}
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
