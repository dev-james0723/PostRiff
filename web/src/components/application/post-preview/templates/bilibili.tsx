'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, firstLine, formatClock, MediaFill, MediaGrid, mediaHeight, Monogram, restAfterFirstLine, RichText, TabBar, TabItem } from '../parts';
import type { TemplateProps } from '../types';

// Sampled from the iOS 9.12 App Store screenshots and bilibili's web tokens.
const INK = '#18191c';
const MUTED = '#61666d';
const FAINT = '#9499a0';
const PINK = '#fb7299';
const LINK = '#008ac5';
const FEED = '#f1f2f3';

/** Bilibili: a video upload opens on its video page; a post without video is a 动态 card. */
export default function BilibiliTemplate(props: TemplateProps) {
  const video = props.post.media.find((item) => item.kind === 'video');
  return video ? <VideoPage {...props} /> : <DynamicCard {...props} />;
}

function VideoPage({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const video = post.media.find((item) => item.kind === 'video');
  const title = firstLine(post.text) || '未命名视频';
  const description = restAfterFirstLine(post.text);

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' lang='zh-CN' label={`哔哩哔哩视频预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col bg-white' style={{ color: INK }}>
        <div className='shrink-0 bg-black'>
          <StatusBarSpace />
          <div className='relative h-[221px]'>
            {video && <MediaFill media={video} className='size-full' />}
            <span className='absolute top-3 left-3 text-white'>
              <AppIcons.back size={26} stroke={2.2} />
            </span>
          </div>
        </div>
        <div className='flex h-[44px] shrink-0 items-center gap-6 border-b border-[#e3e5e7] px-4 text-[15px]'>
          <span className='relative font-medium' style={{ color: PINK }}>
            简介
            <span className='absolute -bottom-[11px] left-1/2 h-[2px] w-[22px] -translate-x-1/2 rounded-full' style={{ background: PINK }} />
          </span>
          <span style={{ color: MUTED }}>评论</span>
          <span className='ml-auto flex items-center gap-2'>
            <span className='rounded-full bg-[#f1f2f3] px-3 py-1 text-[13px]' style={{ color: FAINT }}>
              点我发弹幕
            </span>
            <span className='flex size-[26px] items-center justify-center rounded-[6px] border text-[12px]' style={{ borderColor: FAINT, color: MUTED }}>
              弹
            </span>
          </span>
        </div>
        <article className='flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-4 pt-3'>
          <div className='flex items-center gap-2.5'>
            <Monogram name={names.display} size={36} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[14px] font-medium' style={{ color: PINK }}>
                {names.display}
              </p>
              <p className='mt-0.5 text-[11px]' style={{ color: FAINT }}>
                UP主
              </p>
            </div>
            <span className='flex h-[28px] items-center rounded-full px-3 text-[13px] font-medium text-white' style={{ background: PINK }}>
              + 关注
            </span>
          </div>
          <p className='text-[16px] leading-[22px] font-medium'>{title}</p>
          <p className='text-[12px]' style={{ color: FAINT }}>
            0播放 · 刚刚
          </p>
          {description && (
            <ClampText lines={2} background='#ffffff' className='text-[13px] leading-5' style={{ color: MUTED }}>
              {description}
            </ClampText>
          )}
          <div className='flex justify-between px-2 pt-1 text-[12px]' style={{ color: MUTED }}>
            {[
              [AppIcons.thumbUp, '点赞'],
              [AppIcons.thumbDown, '不喜欢'],
              [AppIcons.coin, '投币'],
              [AppIcons.star, '收藏'],
              [AppIcons.forward, '分享']
            ].map(([Glyph, label]) => {
              const Icon = Glyph as typeof AppIcons.star;
              return (
                <span key={label as string} className='flex flex-col items-center gap-1'>
                  <Icon size={27} stroke={1.6} />
                  {label as string}
                </span>
              );
            })}
          </div>
        </article>
        <div className='h-[34px] shrink-0' />
      </div>
    </PhoneFrame>
  );
}

function DynamicCard({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind === 'image');
  const height = media.length === 1 ? mediaHeight(media[0], 250, { min: 0.75, max: 1.33, fallback: 1 }) : media.length > 2 ? 240 : 170;

  return (
    <PhoneFrame scale={scale} background={FEED} tone='dark' lang='zh-CN' label={`哔哩哔哩动态预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <StatusBarSpace />
          <header className='flex h-[44px] items-center justify-center gap-7 text-[16px]'>
            <span className='relative font-medium' style={{ color: PINK }}>
              综合
              <span className='absolute -bottom-[9px] left-1/2 h-[3px] w-[18px] -translate-x-1/2 rounded-full' style={{ background: PINK }} />
            </span>
            <span style={{ color: MUTED }}>视频</span>
          </header>
        </div>
        <article className='mt-2 flex min-h-0 flex-col gap-2.5 overflow-hidden bg-white px-4 pt-3'>
          <div className='flex items-center gap-2.5'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[15px] font-medium' style={{ color: PINK }}>
                {names.display}
              </p>
              <p className='mt-1 text-[12px]' style={{ color: FAINT }}>
                刚刚
              </p>
            </div>
            <AppIcons.dotsVertical size={20} stroke={1.8} color={FAINT} />
          </div>
          <ClampText lines={6} background='#ffffff' className='text-[15px] leading-[23px]' more={<span style={{ color: LINK }}>展开</span>}>
            <RichText text={post.text} accent={LINK} />
          </ClampText>
          {media.length === 1 && <MediaFill media={media[0]} rounded={6} className='w-[250px] shrink-0' style={{ height }} />}
          {media.length > 1 && <MediaGrid media={media} height={height} gap={4} rounded={6} />}
          <div className='mt-1 flex h-[40px] shrink-0 items-center justify-around text-[13px]' style={{ color: MUTED }}>
            {[
              [AppIcons.forward, '转发'],
              [AppIcons.commentRound, '评论'],
              [AppIcons.thumbUp, '点赞']
            ].map(([Glyph, label]) => {
              const Icon = Glyph as typeof AppIcons.forward;
              return (
                <span key={label as string} className='flex items-center gap-1.5'>
                  <Icon size={19} stroke={1.7} />
                  {label as string}
                </span>
              );
            })}
          </div>
        </article>
        <div aria-hidden className='min-h-0 flex-1' />
        <TabBar background='#ffffff' border='#e3e5e7'>
          <TabItem color={MUTED} label='首页' icon={<AppIcons.home size={25} stroke={1.7} />} />
          <TabItem color={PINK} label='动态' icon={<AppIcons.compass size={25} stroke={1.9} />} />
          <span className='mt-[3px] flex h-[34px] w-[48px] items-center justify-center rounded-[12px] text-white' style={{ background: PINK }}>
            <AppIcons.plus size={22} stroke={2.6} />
          </span>
          <TabItem color={MUTED} label='会员购' icon={<AppIcons.bag size={25} stroke={1.7} />} />
          <TabItem color={MUTED} label='我的' icon={<AppIcons.user size={25} stroke={1.7} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}
