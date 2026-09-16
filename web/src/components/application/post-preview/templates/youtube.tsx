'use client';

import { CHANNEL_ICONS } from '@/components/channel-icon';
import { AppIcons } from '../app-icons';
import { PhoneFrame, STATUS_BAR_HEIGHT, StatusBarSpace } from '../phone-frame';
import { accountNames, BrandGlyph, ClampText, firstLine, formatClock, MediaFill, MissingMedia, Monogram, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

const INK = '#0f0f0f';
const MUTED = '#606060';
const LOGO_RED = '#ff0000';
const RED = '#ff0033';

/** YouTube: a vertical video plays as a Short; anything else is a Home feed item with its 16:9 thumbnail. */
export default function YouTubeTemplate(props: TemplateProps) {
  const video = props.post.media.find((item) => item.kind !== 'file');
  const vertical = Boolean(video?.width && video?.height && video.height > video.width);
  return vertical ? <ShortTemplate {...props} /> : <HomeTemplate {...props} />;
}

/** Home feed (2026): logo with cast / bell / search, topic chips, edge-to-edge thumbnail, 40pt avatar beside a two-line title. */
function HomeTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const video = post.media.find((item) => item.kind !== 'file');
  const title = firstLine(post.text) || 'Untitled video';

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`YouTube preview of the video by ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[48px] shrink-0 items-center justify-between px-3'>
          <span className='flex items-center gap-1'>
            <BrandGlyph path={CHANNEL_ICONS.youtube?.path} size={30} color={LOGO_RED} />
            <span className='text-[21px] font-bold tracking-[-1px]' style={{ fontFamily: 'Roboto, Arial, Helvetica, sans-serif' }}>
              YouTube
            </span>
          </span>
          <span className='flex items-center gap-5'>
            <AppIcons.broadcast size={24} stroke={1.8} />
            <AppIcons.bell size={24} stroke={1.8} />
            <AppIcons.search size={24} stroke={2} />
          </span>
        </header>
        <div className='flex h-[46px] shrink-0 items-center gap-2 px-3 text-[14px] font-medium'>
          <span className='flex h-[32px] items-center rounded-[8px] bg-[#0f0f0f] px-3 text-white'>All</span>
          <span className='flex h-[32px] items-center rounded-[8px] bg-[#f2f2f2] px-3'>New to you</span>
          <span className='flex h-[32px] items-center rounded-[8px] bg-[#f2f2f2] px-3'>Recently uploaded</span>
        </div>

        <article className='flex min-h-0 flex-1 flex-col overflow-hidden'>
          <div className='relative h-[221px] w-full shrink-0 bg-black'>
            {video ? <MediaFill media={video} className='size-full' /> : <MissingMedia need='YouTube uploads need a video.' className='size-full' />}
          </div>
          <div className='flex gap-3 px-3 pt-3'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1'>
              <ClampText lines={2} background='#ffffff' className='text-[16px] leading-[22px] font-semibold'>
                {title}
              </ClampText>
              <p className='mt-1 text-[12px]' style={{ color: MUTED }}>
                {names.display} · No views · Just now
              </p>
            </div>
            <AppIcons.dotsVertical size={20} stroke={1.8} />
          </div>
        </article>

        <TabBar background='#ffffff' border='#e5e5e5'>
          <TabItem color={INK} label='Home' icon={<AppIcons.homeFilled size={25} />} />
          <TabItem color={INK} label='Shorts' icon={<ShortsMark />} />
          <span className='mt-[2px] flex size-[40px] items-center justify-center rounded-full bg-[#f2f2f2]'>
            <AppIcons.plus size={26} stroke={2} />
          </span>
          <TabItem color={INK} label='Subscriptions' icon={<AppIcons.movie size={25} stroke={1.7} />} />
          <TabItem color={INK} label='You' icon={<Monogram name={names.display} size={25} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}

/** Shorts player (heart version, rolling out since June 2026): heart / comments / Share / Remix and the sound tile, @handle with Subscribe. */
function ShortTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const video = post.media.find((item) => item.kind !== 'file');
  const title = firstLine(post.text);

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' label={`YouTube Shorts preview of the video by ${names.display}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col text-white'>
        <div className='relative min-h-0 flex-1 overflow-hidden'>
          {video && <MediaFill media={video} className='absolute inset-0' />}
          <div className='absolute inset-x-0 bottom-0 h-[240px] bg-gradient-to-t from-black/60 to-transparent' />
          <div className='absolute inset-x-0 flex h-[44px] items-center justify-end gap-5 px-4' style={{ top: STATUS_BAR_HEIGHT }}>
            <AppIcons.search size={25} stroke={2} />
            <AppIcons.dotsVertical size={25} stroke={2} />
          </div>
          <div className='absolute right-2 bottom-[20px] flex w-[58px] flex-col items-center gap-5 text-[13px] font-medium [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]'>
            {[
              [AppIcons.heartFilled, ''],
              [AppIcons.commentRound, ''],
              [AppIcons.forward, 'Share'],
              [AppIcons.repeat, 'Remix']
            ].map(([Glyph, label], index) => {
              const Icon = Glyph as typeof AppIcons.forward;
              return (
                <span key={index} className='flex flex-col items-center gap-1'>
                  <span className='flex size-[48px] items-center justify-center rounded-full bg-black/25'>
                    <Icon size={28} stroke={1.8} />
                  </span>
                  {label as string}
                </span>
              );
            })}
            <Monogram name={names.display} size={38} shape='rounded' style={{ boxShadow: '0 0 0 2px #fff' }} />
          </div>
          <div className='absolute bottom-[20px] left-3 w-[300px] [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]'>
            <p className='flex items-center gap-2 text-[15px] font-semibold'>
              <Monogram name={names.display} size={32} />@{names.handle}
              <span className='ml-1 rounded-full bg-white px-3 py-1.5 text-[13px] text-black'>Subscribe</span>
            </p>
            <p className='mt-2 truncate text-[15px]'>{title}</p>
            <span className='mt-2 inline-flex max-w-full items-center gap-1.5 rounded-full bg-black/35 px-2.5 py-1 text-[13px]'>
              <AppIcons.music size={14} stroke={2} />
              <span className='truncate'>Original sound · {names.display}</span>
            </span>
          </div>
          <div className='absolute inset-x-0 bottom-0 h-[2px] bg-white/30'>
            <div className='h-full w-[3%]' style={{ background: RED }} />
          </div>
        </div>
        <nav className='flex h-[83px] shrink-0 items-start justify-around bg-[#0f0f0f] px-1 pt-[7px]'>
          <TabItem color='#f1f1f1' label='Home' icon={<AppIcons.home size={25} stroke={1.7} />} />
          <TabItem color='#f1f1f1' label='Shorts' icon={<ShortsMark filled />} />
          <span className='mt-[2px] flex size-[40px] items-center justify-center rounded-full bg-[#272727]'>
            <AppIcons.plus size={26} stroke={2} />
          </span>
          <TabItem color='#f1f1f1' label='Subscriptions' icon={<AppIcons.movie size={25} stroke={1.7} />} />
          <TabItem color='#f1f1f1' label='You' icon={<Monogram name={names.display} size={25} />} />
        </nav>
      </div>
    </PhoneFrame>
  );
}

function ShortsMark({ filled = false }: { filled?: boolean }) {
  return (
    <svg width='25' height='25' viewBox='0 0 24 24' aria-hidden>
      <rect x='6.5' y='2.5' width='11' height='19' rx='5.5' transform='rotate(-28 12 12)' fill={filled ? 'currentColor' : 'none'} stroke='currentColor' strokeWidth='1.6' />
      <path d='M10.4 9.1v5.8l4.8-2.9-4.8-2.9Z' fill={filled ? '#000000' : 'currentColor'} />
    </svg>
  );
}
