'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, firstLine, formatClock, MediaFill, MediaStrip, Monogram, restAfterFirstLine, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// Dcard App Store and help-centre screenshots, 2026 (light).
const INK = 'rgba(0,0,0,0.85)';
const MUTED = 'rgba(0,0,0,0.5)';
const BLUE = '#3397cf';
const PAGE = '#f2f2f2';

/** Dcard 推薦 feed card: board avatar with the anonymous author badge, 板 · 追蹤, one-line title and excerpt, image strip, reactions. */
export default function DcardTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const title = firstLine(post.text);
  const excerpt = restAfterFirstLine(post.text).replace(/\s*\n+\s*/g, ' ');
  const images = post.media.filter((item) => item.kind === 'image');

  return (
    <PhoneFrame scale={scale} background={PAGE} tone='dark' lang='zh-TW' label={`Dcard 預覽：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <StatusBarSpace />
          <header className='flex h-[46px] items-center gap-3 px-4'>
            <AppIcons.menu size={24} stroke={2} />
            <span className='text-[23px] font-bold tracking-tight' style={{ color: BLUE }}>
              Dcard
            </span>
            <span className='ml-auto flex items-center gap-4' style={{ color: MUTED }}>
              <AppIcons.award size={23} stroke={1.8} color='#fbbc18' />
              <AppIcons.commentRound size={23} stroke={1.8} />
              <AppIcons.bell size={23} stroke={1.8} />
            </span>
          </header>
          <div className='flex h-[40px] items-center gap-6 px-4 text-[15px]'>
            <span className='relative flex h-full items-center font-semibold' style={{ color: BLUE }}>
              推薦
              <span className='absolute inset-x-0 bottom-0 h-[2px]' style={{ background: BLUE }} />
            </span>
            <span style={{ color: MUTED }}>全部</span>
            <span style={{ color: MUTED }}>小卡</span>
          </div>
        </div>

        <article className='mt-2 flex min-h-0 flex-col gap-2 overflow-hidden bg-white px-4 pt-3 pb-3'>
          <div className='flex items-center gap-3'>
            <span className='relative'>
              <Monogram name={names.display} size={40} shape='rounded' />
              <span className='absolute -right-1 -bottom-1 flex size-[18px] items-center justify-center rounded-full border-2 border-white bg-[#bdbdbd] text-white'>
                <AppIcons.user size={11} stroke={2.4} />
              </span>
            </span>
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[14px]'>
                {names.display} · <span style={{ color: BLUE }}>追蹤</span>
              </p>
              <p className='mt-1 text-[13px]' style={{ color: MUTED }}>
                匿名 · 剛才
              </p>
            </div>
            <AppIcons.dots size={20} color={MUTED} />
          </div>
          <p className='truncate text-[16px] leading-6 font-semibold'>{title}</p>
          {excerpt && (
            <p className='truncate text-[15px]' style={{ color: MUTED }}>
              {excerpt}
            </p>
          )}
          {images.length > 0 && (
            <MediaStrip className='-mr-4 shrink-0 gap-2 pr-4'>
              {images.map((item) => (
                <MediaFill key={item.id} media={item} rounded={8} className='h-[210px] w-[280px] shrink-0 snap-start' />
              ))}
            </MediaStrip>
          )}
          <div className='mt-1 flex items-center gap-5 text-[13px]' style={{ color: MUTED }}>
            <span className='flex items-center gap-1'>
              <AppIcons.heart size={18} stroke={1.8} /> 愛心
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.commentRound size={18} stroke={1.8} /> 留言
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.bookmark size={18} stroke={1.8} /> 收藏
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.forward size={18} stroke={1.8} /> 分享
            </span>
          </div>
        </article>
        <div aria-hidden className='min-h-0 flex-1' />

        <div className='relative shrink-0'>
          <span className='absolute right-4 bottom-[96px] flex size-[52px] items-center justify-center rounded-[16px] text-white shadow-lg' style={{ background: BLUE }}>
            <AppIcons.plus size={26} stroke={2.4} />
          </span>
          <TabBar background='#ffffff' border='#e6e6e6'>
            <TabItem color={BLUE} icon={<AppIcons.homeFilled size={26} />} />
            <TabItem color={MUTED} icon={<AppIcons.grid size={26} stroke={1.8} />} />
            <TabItem color={MUTED} icon={<AppIcons.tag size={26} stroke={1.8} />} />
            <TabItem color={MUTED} icon={<AppIcons.search size={26} stroke={2} />} />
            <TabItem color={MUTED} icon={<AppIcons.user size={26} stroke={1.8} />} />
          </TabBar>
        </div>
      </div>
    </PhoneFrame>
  );
}
