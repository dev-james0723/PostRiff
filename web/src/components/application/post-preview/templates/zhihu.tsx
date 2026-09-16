'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, firstLine, formatClock, MediaFill, Monogram, restAfterFirstLine, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// Zhihu 11.x (since 7 Aug 2026), sampled from App Store screenshots.
const INK = '#191b1f';
const MUTED = '#545862';
const FAINT = '#9196a0';
const LINE = '#eef0f2';
const BLUE = '#056de8';

/** Zhihu 推荐 feed card for an article: author and action line, bold title, two-line excerpt with thumbnail, 赞同 / 收藏 / 评论. */
export default function ZhihuTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const title = firstLine(post.text);
  const excerpt = restAfterFirstLine(post.text) || title;
  const thumbnail = post.media.find((item) => item.kind === 'image');

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' lang='zh-CN' label={`知乎预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[46px] shrink-0 items-center gap-5 px-4 text-[16px]'>
          <span style={{ color: MUTED }}>关注</span>
          <span className='relative font-semibold'>
            <span className='absolute inset-x-[-2px] bottom-[1px] h-[7px] rounded-full' style={{ background: `${BLUE}2e` }} />
            <span className='relative'>推荐</span>
          </span>
          <span style={{ color: MUTED }}>热榜</span>
          <span style={{ color: MUTED }}>故事</span>
          <AppIcons.search size={23} stroke={2} className='ml-auto' color={MUTED} />
        </header>

        <article className='flex min-h-0 flex-1 flex-col gap-2 overflow-hidden border-t px-4 pt-3' style={{ borderColor: LINE }}>
          <p className='flex items-center gap-2 text-[13px]' style={{ color: FAINT }}>
            <Monogram name={names.display} size={24} />
            <span className='font-semibold' style={{ color: INK }}>
              {names.display}
            </span>
            刚刚 · 发布了文章
          </p>
          <p className='text-[17px] leading-6 font-semibold'>{title}</p>
          <div className='flex gap-3'>
            <ClampText lines={3} background='#ffffff' className='flex-1 text-[15px] leading-[23px]' style={{ color: MUTED }}>
              文章：{excerpt}
            </ClampText>
            {thumbnail && <MediaFill media={thumbnail} rounded={6} className='h-[64px] w-[88px] shrink-0' />}
          </div>
          <div className='mt-1 flex items-center gap-6 text-[13px]' style={{ color: FAINT }}>
            <span className='flex items-center gap-1'>
              <AppIcons.upvote size={18} stroke={1.8} /> 赞同
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.star size={18} stroke={1.8} /> 收藏
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.commentRound size={18} stroke={1.8} /> 评论
            </span>
            <AppIcons.dots size={18} stroke={1.8} className='ml-auto' />
          </div>
        </article>

        <TabBar background='#ffffff' border={LINE}>
          <TabItem color={INK} label='首页' icon={<AppIcons.homeFilled size={25} />} />
          <TabItem color={FAINT} label='看山' icon={<AppIcons.compass size={25} stroke={1.7} />} />
          <span className='mt-[4px] flex h-[32px] w-[52px] items-center justify-center rounded-full text-white' style={{ background: '#1a87f8' }}>
            <AppIcons.plus size={22} stroke={2.6} />
          </span>
          <TabItem color={FAINT} label='消息' icon={<AppIcons.bell size={25} stroke={1.7} />} />
          <TabItem color={FAINT} label='我的' icon={<Monogram name={names.display} size={25} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
