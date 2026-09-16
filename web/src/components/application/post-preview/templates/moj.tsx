'use client';

import { AppIcons } from '../app-icons';
import { accountNames, Monogram, TabItem } from '../parts';
import type { TemplateProps } from '../types';
import { RailItem, VerticalFeed } from './vertical-feed';

const YELLOW = '#ffcd0a';
const FOLLOW = '#ffaa00';

/**
 * Moj Home feed (Moj: Short Drama & Reels, 2026): full-screen video, avatar with the white badge and orange "+",
 * heart / comment / share and the audio disc, @username with a one-line caption and "...see more", the sound
 * line, and the Home / Series / Create / Live / Profile bar.
 */
export default function MojTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);

  return (
    <VerticalFeed
      post={post}
      scale={scale}
      lang='hi'
      label={`Moj preview of the video by ${names.display}`}
      tabs={[{ label: 'Following' }, { label: 'For You', active: true }]}
      topRight={<AppIcons.search size={25} stroke={2.2} />}
      rail={
        <>
          <span className='relative mb-2'>
            <Monogram name={names.display} size={48} style={{ boxShadow: '0 0 0 1px #fff' }} />
            <span className='absolute -bottom-2 left-1/2 flex size-[18px] -translate-x-1/2 items-center justify-center rounded-full bg-white' style={{ color: FOLLOW }}>
              <AppIcons.plus size={13} stroke={3.2} />
            </span>
          </span>
          <RailItem icon={<AppIcons.heart size={34} stroke={2} />} label='0' />
          <RailItem icon={<AppIcons.commentRound size={33} stroke={2} />} label='0' />
          <RailItem icon={<AppIcons.forward size={34} stroke={2} />} label='Share' />
          <span className='mt-1 flex size-[42px] items-center justify-center rounded-full bg-[#222] ring-[7px] ring-[#161616]'>
            <Monogram name={names.display} size={20} />
          </span>
        </>
      }
      creator={
        <p className='flex items-center gap-1 text-[14px] font-extrabold' style={{ fontFamily: 'Nunito, -apple-system, sans-serif' }}>
          @{names.handle}
        </p>
      }
      moreLabel='...see more'
      captionChars={34}
      footnote={
        <>
          <AppIcons.music size={15} stroke={2} />
          <span className='truncate'>Original Sound - by {names.handle}</span>
        </>
      }
      missingMedia='Moj needs a vertical video.'
      progressColor={YELLOW}
      tabBar={
        <>
          <TabItem color='#ffffff' icon={<AppIcons.homeFilled size={26} />} />
          <span className='relative mt-[1px] text-white/75'>
            <AppIcons.movie size={26} stroke={1.8} />
            <span className='absolute -top-1 -right-5 rounded-[3px] bg-[#ff3b30] px-1 text-[8px] leading-[12px] font-black text-white'>SERIES</span>
          </span>
          <span className='mt-[1px] flex size-[28px] items-center justify-center rounded-[7px] border-2 border-white/80 text-white'>
            <AppIcons.plus size={18} stroke={2.6} />
          </span>
          <TabItem color='rgba(255,255,255,0.75)' icon={<AppIcons.broadcast size={26} stroke={1.8} />} />
          <TabItem color='rgba(255,255,255,0.75)' icon={<Monogram name={names.display} size={26} />} />
        </>
      }
    />
  );
}
