'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, STATUS_BAR_HEIGHT, StatusBarSpace } from '../phone-frame';
import { accountNames, firstLine, formatClock, MediaFill, mediaHeight, MissingMedia, Monogram, restAfterFirstLine, RichText, truncateCaption } from '../parts';
import type { TemplateProps } from '../types';

// Xiaohongshu's own publish-preview styles and images (tokens) plus App Store 9.47 screenshots.
const INK = '#333333';
const TERTIARY = '#858585';
const RED = '#ff2442';
const TOPIC = '#13386c';
const DIVIDER = '#ebebeb';

/** Xiaohongshu note page: image notes open the 笔记详情 page; video notes open the full-screen player. */
export default function XiaohongshuTemplate(props: TemplateProps) {
  return props.post.media[0]?.kind === 'video' ? <VideoNote {...props} /> : <ImageNote {...props} />;
}

/**
 * 图文笔记: ‹ with 36pt avatar, nickname, 关注 outline pill and share; full-width carousel (16:9 to 3:4) with the 1/N
 * pill and red dots; 18pt title, 16pt body with navy #tags, 刚刚; the 说点什么... bar with 点赞 / 收藏 / 评论.
 */
function ImageNote({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind === 'image');
  const first = media[0];
  const height = mediaHeight(first, 393, { min: 0.5625, max: 1.3334, fallback: 1.3334 });
  const title = firstLine(post.text);
  const body = restAfterFirstLine(post.text);

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' lang='zh-CN' label={`小红书笔记预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='flex h-[56px] shrink-0 items-center gap-2 px-2'>
          <AppIcons.back size={28} stroke={2} color={INK} />
          <Monogram name={names.display} size={36} />
          <span className='min-w-0 flex-1 truncate text-[14px] font-medium'>{names.display}</span>
          <span className='flex h-[28px] w-[56px] items-center justify-center rounded-full border text-[14px] font-medium' style={{ color: RED, borderColor: RED }}>
            关注
          </span>
          <AppIcons.forward size={24} stroke={1.8} color={INK} className='mx-2' />
        </header>

        <article className='flex min-h-0 flex-1 flex-col overflow-hidden'>
          <div className='relative shrink-0' style={{ height }}>
            {first ? <MediaFill media={first} className='size-full' /> : <MissingMedia need='小红书笔记需要图片或视频。' className='size-full' />}
            {media.length > 1 && (
              <span className='absolute top-3 right-3 rounded-full px-2 py-0.5 text-[12px] text-white' style={{ background: 'rgba(51,51,51,0.5)' }}>
                1/{media.length}
              </span>
            )}
          </div>
          {media.length > 1 && (
            <div className='flex h-[38px] shrink-0 items-center justify-center gap-[8px]'>
              {media.slice(0, 18).map((item, index) => (
                <span key={item.id} className='size-[5px] rounded-full' style={{ background: index === 0 ? RED : '#e5e5e5' }} />
              ))}
            </div>
          )}
          <div className='flex flex-col gap-2 px-[15px] pt-3'>
            {title && <p className='text-[18px] leading-[26px] font-semibold'>{title}</p>}
            {body && (
              <p className='text-[16px] leading-[26px]'>
                <RichText text={body} accent={TOPIC} />
              </p>
            )}
            <p className='text-[13px]' style={{ color: TERTIARY }}>
              刚刚
            </p>
          </div>
        </article>

        <footer className='flex h-[84px] shrink-0 items-start gap-3 border-t px-4 pt-[7px]' style={{ borderColor: DIVIDER }}>
          <span className='flex h-[36px] w-[139px] items-center gap-1.5 rounded-full bg-[#f5f5f5] px-3 text-[14px]' style={{ color: TERTIARY }}>
            <AppIcons.pencil size={16} stroke={1.8} />
            说点什么...
          </span>
          <span className='ml-auto flex h-[36px] items-center gap-4 text-[15px]'>
            {[
              [AppIcons.heart, '点赞'],
              [AppIcons.star, '收藏'],
              [AppIcons.commentRound, '评论']
            ].map(([Glyph, label]) => {
              const Icon = Glyph as typeof AppIcons.heart;
              return (
                <span key={label as string} className='flex items-center gap-1'>
                  <Icon size={24} stroke={1.7} />
                  {label as string}
                </span>
              );
            })}
          </span>
        </footer>
      </div>
    </PhoneFrame>
  );
}

/** 视频笔记: black player with ‹ and 🔍, avatar, name and a filled red 关注, one-line caption with 展开, the dark comment bar. */
function VideoNote({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const video = post.media[0];
  const caption = truncateCaption(post.text, 20);

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' lang='zh-CN' label={`小红书视频笔记预览：${names.display}`} clock={formatClock(post)}>
      <div className='relative flex h-full flex-col text-white'>
        <div className='relative min-h-0 flex-1 overflow-hidden'>
          {video && <MediaFill media={video} className='absolute inset-0' />}
          <div className='absolute inset-x-0 bottom-0 h-[220px] bg-gradient-to-t from-black/60 to-transparent' />
          <div className='absolute inset-x-0 flex h-[44px] items-center justify-between px-3' style={{ top: STATUS_BAR_HEIGHT }}>
            <AppIcons.back size={28} stroke={2} />
            <AppIcons.search size={24} stroke={2} />
          </div>
          <div className='absolute inset-x-4 bottom-4'>
            <p className='flex items-center gap-2 text-[16px]'>
              <Monogram name={names.display} size={36} />
              {names.display}
              <span className='flex h-[26px] items-center rounded-full px-3 text-[13px] font-medium' style={{ background: RED }}>
                关注
              </span>
            </p>
            <p className='mt-2 flex text-[14px]'>
              <span className='truncate'>{caption.text}</span>
              {caption.cut && <span className='shrink-0 pl-1 text-white/55'>展开</span>}
            </p>
          </div>
        </div>
        <div className='h-px shrink-0 bg-white/30'>
          <div className='h-full w-[4%] bg-white' />
        </div>
        <div className='flex h-[84px] shrink-0 items-start gap-3 bg-black px-4 pt-[9px] text-[14px]'>
          <span className='flex h-[36px] w-[139px] items-center gap-1.5 rounded-full bg-[#141414] px-3 text-white/60'>
            <AppIcons.pencil size={16} stroke={1.8} />
            说点什么...
          </span>
          <span className='ml-auto flex h-[36px] items-center gap-4'>
            <span className='flex items-center gap-1'>
              <AppIcons.heart size={23} stroke={1.8} /> 点赞
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.star size={23} stroke={1.8} /> 收藏
            </span>
            <span className='flex items-center gap-1'>
              <AppIcons.commentRound size={23} stroke={1.8} /> 评论
            </span>
          </span>
        </div>
      </div>
    </PhoneFrame>
  );
}
