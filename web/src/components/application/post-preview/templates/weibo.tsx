'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, ClampText, formatClock, MediaFill, mediaHeight, Monogram, RichText, TabBar, TabItem } from '../parts';
import type { PreviewMedia, TemplateProps } from '../types';

// Weibo 16.9 App Store screenshots (sampled).
const INK = '#1a1a1a';
const MUTED = '#939393';
const LINK = '#4e7cb5';
const ORANGE = '#ff8200';
const UNDERLINE = '#ffa500';
const GAP = '#f0f0f0';

/**
 * Weibo home feed, 关注 version: calendar icon, 关注▾ · 推荐 with the orange-yellow underline and the orange +,
 * a card (40pt avatar, name, 刚刚, ∨ menu, text with blue #话题# and ...全文, image grid), the 转发 / 评论 / 赞 row,
 * and the 首页 / 视频 / 发现 / 消息 / 我 bar.
 */
export default function WeiboTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind === 'image').slice(0, 9);

  return (
    <PhoneFrame scale={scale} background={GAP} tone='dark' lang='zh-CN' label={`微博预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <div className='shrink-0 bg-white'>
          <StatusBarSpace />
          <header className='relative flex h-[46px] items-center justify-between px-4'>
            <AppIcons.calendarEvent size={25} stroke={1.8} />
            <span className='absolute left-1/2 flex -translate-x-1/2 items-center gap-6 text-[17px]'>
              <span className='relative flex items-center gap-0.5 font-semibold'>
                关注
                <AppIcons.chevronDown size={14} stroke={2.6} />
                <span className='absolute -bottom-[8px] left-[5px] h-[3px] w-[20px] rounded-full' style={{ background: UNDERLINE }} />
              </span>
              <span style={{ color: MUTED }}>推荐</span>
            </span>
            <span className='flex size-[26px] items-center justify-center rounded-full text-white' style={{ background: ORANGE }}>
              <AppIcons.plus size={17} stroke={2.8} />
            </span>
          </header>
        </div>

        <article className='mt-2 flex min-h-0 flex-col overflow-hidden bg-white'>
          <div className='flex items-center gap-2.5 px-3 pt-3'>
            <Monogram name={names.display} size={40} />
            <div className='min-w-0 flex-1 leading-tight'>
              <p className='truncate text-[16px] font-medium'>{names.display}</p>
              <p className='mt-1 text-[12px]' style={{ color: MUTED }}>
                刚刚
              </p>
            </div>
            <AppIcons.chevronDown size={20} stroke={1.8} color={MUTED} />
          </div>
          <div className='px-3 pt-2'>
            <ClampText lines={6} background='#ffffff' className='text-[16px] leading-[24px]' more={<span style={{ color: LINK }}>...全文</span>}>
              <RichText text={post.text} accent={LINK} />
            </ClampText>
          </div>
          {media.length > 0 && <WeiboImages media={media} />}
          <div className='mt-3 flex h-[42px] shrink-0 items-center border-t border-[#eeeeee] text-[13px]' style={{ color: '#636363' }}>
            {[
              [AppIcons.forward, '转发'],
              [AppIcons.commentRound, '评论'],
              [AppIcons.thumbUp, '赞']
            ].map(([Glyph, label]) => {
              const Icon = Glyph as typeof AppIcons.forward;
              return (
                <span key={label as string} className='flex flex-1 items-center justify-center gap-1.5'>
                  <Icon size={19} stroke={1.7} />
                  {label as string}
                </span>
              );
            })}
          </div>
        </article>
        <div aria-hidden className='min-h-0 flex-1' />

        <TabBar background='#ffffff' border='#e6e6e6'>
          <TabItem color={INK} label='首页' icon={<AppIcons.homeFilled size={25} />} />
          <TabItem color={MUTED} label='视频' icon={<AppIcons.video size={25} stroke={1.7} />} />
          <TabItem color={MUTED} label='发现' icon={<AppIcons.search size={25} stroke={1.9} />} />
          <TabItem color={MUTED} label='消息' icon={<AppIcons.mail size={25} stroke={1.7} />} />
          <TabItem color={MUTED} label='我' icon={<AppIcons.user size={25} stroke={1.7} />} />
        </TabBar>
      </div>
    </PhoneFrame>
  );
}

/** One image keeps its shape; two or three are squares in a three-column row; four make 2x2; up to nine fill the grid. */
function WeiboImages({ media }: { media: PreviewMedia[] }) {
  if (media.length === 1) {
    return <MediaFill media={media[0]} className='mx-3 mt-2 w-[250px] shrink-0' style={{ height: mediaHeight(media[0], 250, { min: 0.56, max: 1.33, fallback: 1 }) }} />;
  }
  const columns = media.length === 4 ? 2 : 3;
  return (
    <div className='mx-3 mt-2 grid shrink-0 gap-[3px]' style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`, width: columns === 2 ? 246 : 369 }}>
      {media.map((item) => (
        <MediaFill key={item.id} media={item} className='aspect-square w-full' />
      ))}
    </div>
  );
}
