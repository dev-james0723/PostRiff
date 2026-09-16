'use client';

import { CHANNEL_ICONS } from '@/components/channel-icon';
import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, BrandGlyph, ClampText, formatClock, MediaFill, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { PreviewMedia, TemplateProps } from '../types';

// Values from bluesky-social/social-app (v1.133) and its ALF palette.
const INK = '#000000';
const MUTED = '#405168';
const ICON = '#667b99';
const BLUE = '#006aff';
const LINE = '#dce2ea';

/**
 * Bluesky Home: menu / butterfly / feeds header over Discover and Following, one feed item (42pt avatar, name,
 * @handle · time, text, image layout by count), Reply / Repost / Like with Bookmark / Share / more on the right,
 * the blue compose button and the icon tab bar ending in your avatar.
 */
export default function BlueskyTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  // Shown as the account names it; a domain is never guessed.
  const handle = names.handle;
  const media = post.media.filter((item) => item.kind !== 'file').slice(0, 4);

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Bluesky preview of the post by @${handle}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK, fontFamily: 'Inter, -apple-system, sans-serif' }}>
        <StatusBarSpace />
        <header className='relative flex h-[44px] shrink-0 items-center justify-center'>
          <AppIcons.menu size={26} stroke={1.8} color={ICON} className='absolute left-4' />
          <BrandGlyph path={CHANNEL_ICONS.bluesky?.path} size={30} color={BLUE} />
          <AppIcons.hash size={24} stroke={1.8} color={ICON} className='absolute right-4' />
        </header>
        <div className='flex h-[44px] shrink-0 gap-6 border-b px-4 text-[15px] font-semibold' style={{ borderColor: LINE }}>
          <span className='flex items-center' style={{ color: MUTED }}>
            Discover
          </span>
          <span className='relative flex items-center'>
            Following
            <span className='absolute inset-x-0 bottom-0 h-[2px]' style={{ background: BLUE }} />
          </span>
        </div>

        <article className='relative flex min-h-0 flex-1 gap-2.5 overflow-hidden px-3 pt-3'>
          <Monogram name={names.display} size={42} />
          <div className='flex min-w-0 flex-1 flex-col'>
            <p className='flex items-center gap-1 text-[15px] leading-5'>
              <span className='truncate font-semibold'>{names.display}</span>
              <span className='truncate' style={{ color: MUTED }}>
                @{handle} · now
              </span>
            </p>
            <ClampText lines={25} background='#ffffff' className='mt-0.5 text-[15px] leading-5'>
              <RichText text={post.text} accent={BLUE} />
            </ClampText>
            {media.length > 0 && <BlueskyImages media={media} />}
            <div className='mt-3 flex items-center pr-1' style={{ color: ICON }}>
              <span className='flex flex-1 items-center justify-between pr-8'>
                <AppIcons.comment size={18} stroke={1.8} />
                <AppIcons.repeat size={18} stroke={1.8} />
                <AppIcons.heart size={18} stroke={1.8} />
              </span>
              <span className='flex items-center gap-5'>
                <AppIcons.bookmark size={18} stroke={1.8} />
                <AppIcons.share size={18} stroke={1.8} />
                <AppIcons.dots size={18} stroke={1.8} />
              </span>
            </div>
          </div>
          <span className='absolute right-6 bottom-4 flex size-[56px] items-center justify-center rounded-full text-white shadow-lg' style={{ background: BLUE }}>
            <AppIcons.pencil size={24} stroke={2} />
          </span>
        </article>

        <TabBar background='#ffffff' border={LINE}>
          <TabItem color={INK} icon={<AppIcons.homeFilled size={28} />} />
          <TabItem color={ICON} icon={<AppIcons.search size={28} stroke={1.8} />} />
          <TabItem color={ICON} icon={<AppIcons.commentRound size={28} stroke={1.8} />} />
          <TabItem color={ICON} icon={<AppIcons.bell size={28} stroke={1.8} />} />
          <TabItem color={ICON} icon={<Monogram name={names.display} size={28} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}

/** The app's image layouts: one at its ratio, two squares, a square beside two stacked, or a 2x2 grid of 3:2 cells. */
function BlueskyImages({ media }: { media: PreviewMedia[] }) {
  const width = 321;
  if (media.length === 1) {
    return <MediaFill media={media[0]} rounded={12} className='mt-2 w-full shrink-0' style={{ height: mediaHeight(media[0], width, { min: 0.5, max: 1.78, fallback: 0.75 }) }} />;
  }
  if (media.length === 2) {
    return (
      <div className='mt-2 grid shrink-0 grid-cols-2 gap-1'>
        {media.map((item) => (
          <MediaFill key={item.id} media={item} rounded={12} className='aspect-square w-full' />
        ))}
      </div>
    );
  }
  if (media.length === 3) {
    return (
      <div className='mt-2 grid shrink-0 grid-cols-2 grid-rows-2 gap-1' style={{ height: (width - 4) / 2 }}>
        <MediaFill media={media[0]} rounded={12} className='row-span-2 size-full' />
        <MediaFill media={media[1]} rounded={12} className='size-full' />
        <MediaFill media={media[2]} rounded={12} className='size-full' />
      </div>
    );
  }
  return (
    <div className='mt-2 grid shrink-0 grid-cols-2 gap-1'>
      {media.map((item) => (
        <MediaFill key={item.id} media={item} rounded={12} className='aspect-[3/2] w-full' />
      ))}
    </div>
  );
}
