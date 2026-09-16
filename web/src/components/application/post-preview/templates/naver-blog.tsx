'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, firstLine, formatClock, formatTime, MediaFill, mediaHeight, Monogram, restAfterFirstLine, RichText } from '../parts';
import type { TemplateProps } from '../types';

// m.blog.naver.com post styles, which the app renders.
const INK = '#000000';
const NICK = '#555555';
const DATE = '#8c8c8c';
const GREEN = '#03c75a';
const LINK = '#608cba';

/**
 * A Naver Blog post page: blog header, 26px title, author row (avatar, nickname, dotted date, 이웃추가), body with
 * full-width images and underlined links, and the 공감 / 댓글 / share row.
 */
export default function NaverBlogTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const title = firstLine(post.text);
  const body = restAfterFirstLine(post.text);
  const image = post.media.find((item) => item.kind === 'image');
  const date = formatTime(post, 'ko-KR', { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' lang='ko' label={`네이버 블로그 미리보기: ${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[46px] shrink-0 items-center gap-2 border-b border-[#eeeeee] px-3'>
          <AppIcons.back size={26} stroke={2} />
          <span className='flex min-w-0 flex-1 items-center gap-1.5 text-[16px] font-semibold'>
            <span className='text-[17px] font-black' style={{ color: GREEN }}>
              blog
            </span>
            <span className='truncate'>{names.display}</span>
          </span>
          <AppIcons.search size={22} stroke={2} />
          <AppIcons.menu size={22} stroke={2} />
        </header>

        <article className='flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-4 pt-4' style={{ fontFamily: '"Nanum Gothic", "Apple SD Gothic Neo", -apple-system, sans-serif' }}>
          <p className='text-[26px] leading-[37px]'>{title}</p>
          <div className='flex items-center gap-2 border-b border-[#eeeeee] pb-3'>
            <Monogram name={names.display} size={36} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[14px]' style={{ color: NICK }}>
                {names.display}
              </p>
              <p className='mt-0.5 text-[12px]' style={{ color: DATE }}>
                {date}
              </p>
            </div>
            <span className='flex h-[28px] items-center rounded-full border px-2.5 text-[12px]' style={{ color: GREEN, borderColor: GREEN }}>
              + 이웃추가
            </span>
            <AppIcons.dots size={20} color={DATE} />
          </div>
          {image && <MediaFill media={image} className='w-full shrink-0' style={{ height: mediaHeight(image, 361, { min: 0.5, max: 1.25, fallback: 0.75 }) }} />}
          {body && (
            <p className='text-[16px] leading-[28px]'>
              <RichText text={body} accent={LINK} className='[&>span]:underline' />
            </p>
          )}
        </article>

        <div className='flex h-[84px] shrink-0 items-start justify-between border-t border-[#eeeeee] px-5 pt-3 text-[13px]' style={{ color: '#676767' }}>
          <span className='flex items-center gap-5'>
            <span className='flex items-center gap-1.5'>
              <AppIcons.heart size={22} stroke={1.8} /> 공감
            </span>
            <span className='flex items-center gap-1.5'>
              <AppIcons.commentRound size={22} stroke={1.8} /> 댓글
            </span>
          </span>
          <AppIcons.shareNodes size={22} stroke={1.8} />
        </div>
      </div>
    </PhoneFrame>
  );
}
