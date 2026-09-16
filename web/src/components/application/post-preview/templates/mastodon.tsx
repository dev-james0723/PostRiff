'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, formatClock, MediaFill, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { PreviewMedia, TemplateProps } from '../types';

// Values from mastodon/mastodon-ios at tag 2026.07 (the App Store build).
const INK = '#000000';
const MUTED = 'rgba(60,60,67,0.6)';
const ACCENT = '#6145e6';
const TAB_TINT = '#552cfb';
const LINE = '#e5e5ea';

/**
 * Mastodon for iOS (2025 timeline design): "Following" timeline menu with the gear, a row with a rounded-square
 * avatar, name over "now · @user@server", full text, proportional media, Reply / Boost / Favourite / Bookmark /
 * more, and the icon tab bar.
 */
export default function MastodonTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  // The server is shown only when the account names it; PostRiff never guesses an instance.
  const full = names.handle;
  const media = post.media.filter((item) => item.kind !== 'file').slice(0, 4);

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' label={`Mastodon preview of the post by @${full}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[48px] shrink-0 items-center justify-between px-4'>
          <span className='flex items-center gap-1 text-[20px] font-semibold'>
            Following <AppIcons.chevronDown size={18} stroke={2.4} color={ACCENT} />
          </span>
          <AppIcons.settings size={24} stroke={1.8} color={ACCENT} />
        </header>

        <article className='flex min-h-0 flex-1 gap-2 overflow-hidden border-t px-4 pt-3' style={{ borderColor: LINE }}>
          <Monogram name={names.display} size={44} shape='rounded' style={{ borderRadius: 8 }} />
          <div className='flex min-w-0 flex-1 flex-col'>
            <p className='truncate text-[15px] leading-5 font-semibold'>{names.display}</p>
            <p className='truncate text-[15px] leading-5' style={{ color: MUTED }}>
              now · @{full}
            </p>
            <p className='mt-1.5 text-[17px] leading-[23px]'>
              <RichText text={post.text} accent={ACCENT} />
            </p>
            {media.length > 0 && <ProportionalMedia media={media} />}
            <div className='mt-3 flex items-center justify-between pr-2' style={{ color: MUTED }}>
              <AppIcons.reply size={21} stroke={1.8} />
              <AppIcons.repeat size={21} stroke={1.8} />
              <AppIcons.star size={21} stroke={1.8} />
              <AppIcons.bookmark size={21} stroke={1.8} />
              <AppIcons.dots size={21} stroke={1.8} />
            </div>
          </div>
        </article>

        <TabBar background='#f9f9f9' border={LINE}>
          <TabItem color={TAB_TINT} icon={<AppIcons.homeFilled size={27} />} />
          <TabItem color={MUTED} icon={<AppIcons.search size={26} stroke={1.9} />} />
          <TabItem color={MUTED} icon={<AppIcons.pencil size={26} stroke={1.9} />} />
          <TabItem color={MUTED} icon={<AppIcons.bell size={26} stroke={1.9} />} />
          <TabItem color={MUTED} icon={<Monogram name={names.display} size={25} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}

/** Rows of up to two images whose widths follow their ratios, so nothing is cropped. */
function ProportionalMedia({ media }: { media: PreviewMedia[] }) {
  const width = 325;
  const rows = media.length <= 2 ? [media] : [media.slice(0, 2), media.slice(2)];
  if (media.length === 1) {
    return <MediaFill media={media[0]} rounded={8} className='mt-2.5 w-full shrink-0' style={{ height: mediaHeight(media[0], width, { min: 0.4, max: 1.2, fallback: 0.5625 }) }} />;
  }
  return (
    <div className='mt-2.5 flex shrink-0 flex-col gap-px'>
      {rows.map((row, index) => {
        const ratios = row.map((item) => (item.width && item.height ? item.width / item.height : 1));
        const height = (width - (row.length - 1)) / ratios.reduce((sum, ratio) => sum + ratio, 0);
        return (
          <div key={index} className='flex gap-px' style={{ height }}>
            {row.map((item, column) => (
              <MediaFill key={item.id} media={item} rounded={8} style={{ width: height * ratios[column] }} className='h-full' />
            ))}
          </div>
        );
      })}
    </div>
  );
}
