'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, STATUS_BAR_HEIGHT } from '../phone-frame';
import { accountNames, formatClock, MediaFill, MissingMedia, Monogram, truncateCaption } from '../parts';
import type { TemplateProps } from '../types';

// WeChat's own ad mock of the Channels feed and the Channels helper styles.
const CAPTION = 'rgba(255,255,255,0.8)';

/**
 * WeChat Channels 推荐, opened from 发现 (so no WeChat tab bar): ‹ with 关注 · 朋友♡ · 推荐 and search / my channel,
 * the caption above the author row, the 赞 / 转发 / ♡ / 评论 row beside the name, and a thin progress line.
 */
export default function WeChatChannelsTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const media = post.media.filter((item) => item.kind !== 'file');
  const caption = truncateCaption(post.text, 44);
  const shadow = '[filter:drop-shadow(0_1px_2px_rgb(0_0_0/0.55))]';

  return (
    <PhoneFrame scale={scale} background='#000000' tone='light' lang='zh-CN' label={`微信视频号预览：${names.display}`} clock={formatClock(post)}>
      <div className='relative h-full overflow-hidden text-white'>
        {media[0] ? (
          <MediaFill media={media[0]} className='absolute inset-0' />
        ) : (
          <MissingMedia need='视频号需要视频或图片。' dark className='absolute inset-x-6 top-[160px] bottom-[240px] rounded-2xl' />
        )}
        <div className='absolute inset-x-0 top-0 h-[150px] bg-gradient-to-b from-black/45 to-transparent' />
        <div className='absolute inset-x-0 bottom-0 h-[300px] bg-gradient-to-t from-black/70 to-transparent' />

        <div className={`absolute inset-x-0 flex h-[44px] items-center justify-between px-3 text-[17px] ${shadow}`} style={{ top: STATUS_BAR_HEIGHT }}>
          <AppIcons.back size={28} stroke={2} />
          <span className='flex items-center gap-6'>
            <span className='text-white/70'>关注</span>
            <span className='flex items-center gap-0.5 text-white/70'>
              朋友
              <AppIcons.heart size={15} stroke={2.2} />
            </span>
            <span className='relative font-semibold'>
              推荐
              <span className='absolute -bottom-[7px] left-1/2 h-[2px] w-[34px] -translate-x-1/2 bg-white' />
            </span>
          </span>
          <span className='flex items-center gap-4'>
            <AppIcons.search size={24} stroke={2} />
            <AppIcons.user size={24} stroke={2} />
          </span>
        </div>

        <div className={`absolute inset-x-4 bottom-[48px] ${shadow}`}>
          <p className='text-[15px] leading-[25px]' style={{ color: CAPTION }}>
            {caption.text}
            {caption.cut && <span className='text-white'> 展开</span>}
          </p>
          <div className='mt-3 flex items-center gap-2'>
            <Monogram name={names.display} size={44} />
            <span className='min-w-0 flex-1 truncate text-[16px] font-medium'>{names.display}</span>
            <span className='flex items-start gap-5 text-[12px]'>
              {[
                [AppIcons.thumbUp, '赞'],
                [AppIcons.forward, '转发'],
                [AppIcons.heart, ''],
                [AppIcons.commentRound, '评论']
              ].map(([Glyph, label], index) => {
                const Icon = Glyph as typeof AppIcons.heart;
                return (
                  <span key={index} className='flex w-[32px] flex-col items-center gap-1'>
                    <Icon size={25} stroke={1.8} />
                    {label as string}
                  </span>
                );
              })}
            </span>
          </div>
          {media.length > 1 && (
            <span className='mt-3 flex justify-center gap-1.5'>
              {media.map((item, index) => (
                <span key={item.id} className='size-[5px] rounded-full' style={{ background: index === 0 ? '#ffffff' : 'rgba(255,255,255,0.4)' }} />
              ))}
            </span>
          )}
        </div>
        <div className='absolute inset-x-0 bottom-[30px] h-[2px] bg-white/25'>
          <div className='h-full w-[4%] bg-white' />
        </div>
      </div>
    </PhoneFrame>
  );
}
