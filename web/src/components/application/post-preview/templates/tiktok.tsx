'use client';

import type { ReactNode } from 'react';
import { AppIcons } from '../app-icons';
import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { accountNames, formatClock, MediaFill, MissingMedia, Monogram, RichText, TabItem, truncateCaption } from '../parts';
import type { TemplateProps } from '../types';

const PINK = '#fe2c55';
const CYAN = '#25f4ee';

/** TikTok For You: full-screen video or photo post, right-hand rail, caption and sound line, black tab bar. */
export default function TikTokTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const photos = media.length > 1 || media[0]?.kind === 'image';
  const caption = truncateCaption(post.text, 62);

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' label={`TikTok preview of the post by @${names.handle}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col text-white'>
        <div className='relative min-h-0 flex-1 overflow-hidden'>
          {media[0] ? (
            <MediaFill media={media[0]} className='absolute inset-0' />
          ) : (
            <MissingMedia need='TikTok posts need a video or photos.' dark className='absolute inset-x-6 top-[160px] bottom-[220px] rounded-2xl' />
          )}
          <div className='absolute inset-x-0 top-0 h-[150px] bg-gradient-to-b from-black/45 to-transparent' />
          <div className='absolute inset-x-0 bottom-0 h-[260px] bg-gradient-to-t from-black/60 to-transparent' />

          <div className='absolute inset-x-0 flex h-[44px] items-center justify-between px-4 text-[17px]' style={{ top: STATUS_BAR_HEIGHT }}>
            <AppIcons.video size={26} stroke={1.8} />
            <span className='flex items-center gap-5'>
              <span className='font-semibold text-white/70'>Following</span>
              <span className='relative font-bold'>
                For You
                <span className='absolute -bottom-2 left-1/2 h-[3px] w-[30px] -translate-x-1/2 rounded-full bg-white' />
              </span>
            </span>
            <AppIcons.search size={26} stroke={2} />
          </div>

          <div className='absolute right-2 bottom-[18px] flex w-[62px] flex-col items-center gap-[18px] text-[13px] font-semibold [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]'>
            <span className='relative mb-2'>
              <Monogram name={names.display} size={48} style={{ boxShadow: '0 0 0 1.5px #fff' }} />
              <span className='absolute -bottom-2.5 left-1/2 flex size-[22px] -translate-x-1/2 items-center justify-center rounded-full' style={{ background: PINK }}>
                <AppIcons.plus size={15} stroke={3} />
              </span>
            </span>
            <RailButton icon={<AppIcons.heartFilled size={38} />} label='0' />
            <RailButton icon={<AppIcons.commentRound size={36} stroke={1.6} className='-scale-x-100' />} label='0' />
            <RailButton icon={<AppIcons.bookmark size={35} stroke={1.8} />} label='0' />
            <RailButton icon={<AppIcons.forward size={36} stroke={1.8} />} label='Share' />
            <span className='mt-1 flex size-[48px] items-center justify-center rounded-full bg-[#2b2b2b] ring-[9px] ring-[#161616]'>
              <Monogram name={names.display} size={24} />
            </span>
          </div>

          <div className='absolute bottom-[18px] left-3 w-[296px] [filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.6))_drop-shadow(0_0_10px_rgb(0_0_0/0.35))]'>
            {photos && media.length > 1 && (
              <span className='mb-3 flex w-[369px] justify-center gap-1.5'>
                {media.map((item, index) => (
                  <span key={item.id} className='size-[6px] rounded-full' style={{ background: index === 0 ? '#ffffff' : 'rgba(255,255,255,0.45)' }} />
                ))}
              </span>
            )}
            <p className='text-[17px] font-semibold'>{names.display}</p>
            <p className='mt-1 text-[15px] leading-5'>
              <RichText text={caption.text} accent='#ffffff' className='[&>span]:font-semibold' />
              {caption.cut && <span className='font-semibold'> more</span>}
            </p>
            <p className='mt-2 flex items-center gap-1.5 text-[14px]'>
              <AppIcons.music size={15} stroke={2} />
              <span className='truncate'>original sound - {names.handle}</span>
            </p>
          </div>
          <div className='absolute inset-x-0 bottom-0 h-[2px] bg-white/25'>
            <div className='h-full w-[3%] bg-white/80' />
          </div>
        </div>

        <nav className='flex h-[83px] shrink-0 items-start justify-around bg-black px-2 pt-[7px]'>
          <TabItem color='#ffffff' label='Home' icon={<AppIcons.homeFilled size={26} />} />
          <TabItem color='rgba(255,255,255,0.72)' label='Friends' icon={<AppIcons.users size={26} stroke={1.8} />} />
          <span className='relative mt-[3px] h-[30px] w-[46px]'>
            <span className='absolute inset-y-0 left-0 w-[40px] rounded-[9px]' style={{ background: CYAN }} />
            <span className='absolute inset-y-0 right-0 w-[40px] rounded-[9px]' style={{ background: PINK }} />
            <span className='absolute inset-y-0 left-[3px] flex w-[40px] items-center justify-center rounded-[9px] bg-white text-black'>
              <AppIcons.plus size={20} stroke={3} />
            </span>
          </span>
          <TabItem color='rgba(255,255,255,0.72)' label='Inbox' icon={<AppIcons.inbox size={26} stroke={1.8} />} />
          <TabItem color='rgba(255,255,255,0.72)' label='Profile' icon={<AppIcons.user size={26} stroke={1.8} />} />
        </nav>
      </div>
    </PhoneFrame>
  );
}

function RailButton({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className='flex flex-col items-center gap-1'>
      {icon}
      <span>{label}</span>
    </span>
  );
}
