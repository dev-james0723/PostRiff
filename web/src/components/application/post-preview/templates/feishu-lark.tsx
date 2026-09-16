'use client';

import { AppIcons } from '../app-icons';
import { PhoneFrame, StatusBarSpace } from '../phone-frame';
import { accountNames, firstLine, formatClock, MediaFill, Monogram, restAfterFirstLine, RichText } from '../parts';
import type { TemplateProps } from '../types';

// Feishu 8.0 chat, with card values from the open platform's message card design spec.
const INK = '#1f2329';
const MUTED = '#646a73';
const FAINT = '#8f959e';
const LINE = '#dee0e3';
const BLUE = '#1456f0';

/** A Feishu group chat with the announcement as a bot message card: tinted header, body, optional image. */
export default function FeishuLarkTemplate({ post, scale }: TemplateProps) {
  const names = accountNames(post.account);
  const title = firstLine(post.text);
  const body = restAfterFirstLine(post.text);
  const image = post.media.find((item) => item.kind === 'image');
  const file = post.media.find((item) => item.kind === 'file');

  return (
    <PhoneFrame scale={scale} background='#ffffff' tone='dark' lang='zh-CN' label={`飞书消息卡片预览：${names.display}`} clock={formatClock(post)}>
      <div className='flex h-full flex-col' style={{ color: INK }}>
        <StatusBarSpace />
        <header className='relative flex h-[44px] shrink-0 items-center justify-center text-[17px] font-semibold'>
          <AppIcons.back size={26} stroke={2} className='absolute left-2' />
          <span className='max-w-[220px] truncate'>{names.display}</span>
          <span className='absolute right-3 flex items-center gap-4'>
            <AppIcons.video size={23} stroke={1.8} />
            <AppIcons.dots size={23} stroke={1.8} />
          </span>
        </header>
        <div className='flex h-[40px] shrink-0 items-center gap-2 border-b px-3 text-[13px]' style={{ borderColor: LINE }}>
          <span className='rounded-[6px] px-2.5 py-1 font-medium' style={{ background: '#e1eaff', color: BLUE }}>
            消息
          </span>
          <span className='flex items-center gap-1 px-1.5' style={{ color: MUTED }}>
            <AppIcons.speakerphone size={15} stroke={2} color='#ff811a' /> 群公告
          </span>
          <span className='flex items-center gap-1 px-1.5' style={{ color: MUTED }}>
            <AppIcons.file size={15} stroke={2} color='#f5b400' /> 文档
          </span>
        </div>

        <div className='flex min-h-0 flex-1 flex-col justify-end overflow-hidden px-3 pb-3'>
          <p className='mb-3 text-center text-[12px]' style={{ color: FAINT }}>
            今天
          </p>
          <div className='flex gap-2'>
            <Monogram name={names.display} size={36} />
            <div className='min-w-0'>
              <p className='mb-1 flex items-center gap-1.5 text-[12px]' style={{ color: FAINT }}>
                {names.display}
                <span className='rounded-[4px] px-1 text-[10px] font-medium' style={{ background: '#fdf4d3', color: '#8a5d00' }}>
                  机器人
                </span>
              </p>
              <div className='w-[302px] overflow-hidden rounded-[8px] border bg-white' style={{ borderColor: LINE }}>
                <div className='px-3 py-2.5' style={{ background: 'linear-gradient(90deg, #e4ecff, #f0f4ff)' }}>
                  <p className='text-[16px] leading-[22px] font-medium' style={{ color: BLUE }}>
                    {title || names.display}
                  </p>
                </div>
                <div className='flex flex-col gap-3 p-3'>
                  {body && (
                    <p className='text-[14px] leading-[22px]'>
                      <RichText text={body} accent={BLUE} />
                    </p>
                  )}
                  {image && <MediaFill media={image} rounded={6} className='h-[155px] w-full' />}
                  {file && (
                    <p className='flex items-center gap-2 rounded-[6px] border px-2.5 py-2 text-[14px]' style={{ borderColor: LINE, color: BLUE }}>
                      <AppIcons.fileText size={20} stroke={1.8} />
                      <span className='truncate'>{file.alt || '文档'}</span>
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className='flex h-[90px] shrink-0 flex-col gap-2 border-t px-3 pt-2' style={{ borderColor: LINE }}>
          <span className='flex h-[36px] items-center rounded-[8px] bg-[#f5f6f7] px-3 text-[15px]' style={{ color: FAINT }}>
            发送给 {names.display}
          </span>
          <span className='flex items-center gap-6 px-1' style={{ color: MUTED }}>
            <AppIcons.smile size={21} stroke={1.8} />
            <span className='text-[17px] font-medium'>@</span>
            <AppIcons.mic size={21} stroke={1.8} />
            <AppIcons.photo size={21} stroke={1.8} />
            <AppIcons.circlePlus size={21} stroke={1.8} className='ml-auto' />
          </span>
        </div>
      </div>
    </PhoneFrame>
  );
}
