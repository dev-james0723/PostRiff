'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, firstLine, formatClock, formatTime, MediaFill, Monogram, restAfterFirstLine, RichText } from '../parts';
import type { TemplateProps } from '../types';

// note.com article styles, which the iOS app renders.
const INK = '#08131a';
const MUTED = 'rgba(8,19,26,0.66)';
const BORDER = 'rgba(8,19,26,0.14)';

/**
 * A note article page: black wordmark header, 2:1 cover, 20px bold title, スキ count with the creator, date and
 * フォロー, airy body with underlined links, and the app's floating heart.
 */
export default function NoteTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const title = firstLine(post.text);
  const body = restAfterFirstLine(post.text);
  const cover = post.media.find((item) => item.kind === 'image');
  const date = formatTime(post, 'ja-JP', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' lang='ja' label={`noteのプレビュー：${names.display}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[46px] shrink-0 items-center justify-between px-3'>
          <AppIcons.back size={26} stroke={2} />
          <span className='text-[21px] font-bold tracking-tight'>note</span>
          <span className='flex items-center gap-4'>
            <AppIcons.shareNodes size={22} stroke={1.9} />
            <AppIcons.dots size={22} stroke={1.9} />
          </span>
        </header>

        <article className='flex min-h-0 flex-1 flex-col overflow-hidden'>
          {cover && <MediaFill media={cover} className='h-[196px] w-full shrink-0' />}
          <div className='flex flex-col gap-3 px-4 pt-5'>
            <p className='text-[20px] leading-[30px] font-bold tracking-[0.04em]'>{title}</p>
            <div className='flex items-center gap-2 text-[13px]' style={{ color: MUTED }}>
              <span className='flex items-center gap-1'>
                <AppIcons.heart size={16} stroke={1.9} /> 0
              </span>
              <Monogram name={names.display} size={32} />
              <div className='min-w-0 flex-1 leading-tight'>
                <p className='truncate text-[14px] font-semibold' style={{ color: INK }}>
                  {names.display}
                </p>
                <p className='mt-0.5 text-[12px]'>{date}</p>
              </div>
              <span className='rounded-full border px-3 py-1 text-[13px] font-semibold' style={{ color: INK, borderColor: BORDER }}>
                フォロー
              </span>
            </div>
            {body && (
              <p className='text-[16px] leading-[32px]'>
                <RichText text={body} accent={INK} className='[&>span]:underline' />
              </p>
            )}
          </div>
        </article>

        <span className='absolute right-5 bottom-[48px] flex size-[56px] items-center justify-center rounded-full bg-white shadow-[0_2px_12px_rgb(8_19_26/0.18)]' style={{ color: MUTED }}>
          <AppIcons.heart size={28} stroke={1.8} />
        </span>
        <div className='h-[34px] shrink-0' />
      </div>
    </PhoneFrame>
  );
}
