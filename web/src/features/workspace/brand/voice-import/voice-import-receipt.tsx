'use client';

import { useId, useState } from 'react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { ApiError } from '@/lib/api/client';
import { accountLines, COVERAGE_STATES, coverageStates } from '@/lib/voice-import/coverage';
import type { AccountReceipt, CoverageStatus } from '@/lib/voice-import/coverage';
import { platformName } from '@/lib/voice-import/labels';
import type { CoverageStateId, VoiceCoverage, VoiceImport } from '@/lib/voice-import/types';
import { Band, StatusChip } from '../../rafii-parts';
import type { BrainTranslate } from '../brain-types';
import { EvidenceBrowser } from './voice-import-evidence';
import { useInvalidateVoiceImports, useVoiceImportApi } from './use-voice-import';

const STATE_ICON: Record<CoverageStatus, keyof typeof Icons> = { done: 'check', partial: 'info', pending: 'clock', none: 'circleDashed' };

/**
 * Connected, retrieved, processed, profile proposed, profile approved: each with a word and an icon, never colour
 * alone, and each straight from the workspace's own coverage.
 */
export function CoverageStates({ coverage, t }: { coverage: VoiceCoverage | undefined; t: BrainTranslate }) {
  const names: Record<CoverageStateId, string> = {
    connected: t('Connected', '已連接', '已连接'),
    retrieved: t('Retrieved', '已取得', '已获取'),
    processed: t('Processed', '已處理', '已处理'),
    proposed: t('Profile proposed', '已提出風格檔案', '已提出风格档案'),
    approved: t('Profile approved', '已批准風格檔案', '已批准风格档案')
  };
  const words: Record<CoverageStatus, string> = { done: t('done', '完成', '完成'), partial: t('partly', '部分完成', '部分完成'), pending: t('in progress', '進行中', '进行中'), none: t('not yet', '尚未', '尚未') };
  const states = coverageStates(coverage);
  return (
    <ol className='flex flex-wrap gap-2' aria-label={t('Import progress', '匯入進度', '导入进度')} data-testid='voice-import-states'>
      {COVERAGE_STATES.map((id) => {
        const status = states.find((state) => state.id === id)?.status ?? 'none';
        return (
          <li key={id}>
            <StatusChip icon={STATE_ICON[status]} tone={status === 'done' ? 'attention' : 'neutral'} className='h-auto min-h-7 py-1 whitespace-normal' data-state={status}>
              {names[id]} · {words[status]}
            </StatusChip>
          </li>
        );
      })}
    </ol>
  );
}

function runStatus(run: VoiceImport, t: BrainTranslate): string {
  switch (run.status) {
    case 'pending':
      return t('Waiting to start', '等待開始', '等待开始');
    case 'receiving':
      return t('Receiving posts from your file', '正在接收檔案中的貼文', '正在接收文件中的帖子');
    case 'running':
      return t('Reading posts', '正在讀取貼文', '正在读取帖子');
    case 'done':
      return t('Finished', '已完成', '已完成');
    case 'failed':
      return t('Stopped before the end', '未完成便已停止', '未完成便已停止');
    default:
      return t('Cancelled', '已取消', '已取消');
  }
}

/** One account's coverage receipt: what was read, what can be used, what was left out and why, and the controls over it. */
export function AccountReceiptCard({ receipt, canManage, canEdit, t }: { receipt: AccountReceipt; canManage: boolean; canEdit: boolean; t: BrainTranslate }) {
  const id = useId();
  const locale = useGenUiLocale();
  const { api, w } = useVoiceImportApi();
  const invalidate = useInvalidateVoiceImports();
  const [working, setWorking] = useState<'' | 'cancel' | 'refresh' | 'delete'>('');
  const [error, setError] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [showPosts, setShowPosts] = useState(false);
  const { latest, active, account } = receipt;
  const name = platformName(receipt.provider);
  const number = (value: number) => locale.formatNumber(value);
  const canRefresh = !active && latest?.route === 'official_api' && ['done', 'failed', 'cancelled'].includes(latest.status);
  const runFacts: [label: string, value: number][] = latest
    ? [
        [t('Retrieved in this run', '此次取得', '此次获取'), latest.counts?.retrieved ?? 0],
        [t('Already stored', '已儲存過', '已保存过'), latest.counts?.duplicates ?? 0],
        [t('Could not be read', '無法讀取', '无法读取'), latest.counts?.unsupported ?? 0],
        [t('Failed', '失敗', '失败'), latest.counts?.failed ?? 0],
        [t('Pages read', '已讀取頁數', '已读取页数'), latest.pages ?? 0]
      ]
    : [];

  async function act(kind: 'cancel' | 'refresh', run: VoiceImport) {
    setWorking(kind);
    setError('');
    try {
      await (kind === 'cancel' ? api.cancel(w, run.id) : api.refresh(w, run.id));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '');
    } finally {
      setWorking('');
      void invalidate();
    }
  }

  async function remove() {
    setConfirming(false);
    setWorking('delete');
    setError('');
    let posts = 0;
    try {
      // Every run of this account, newest first. A run already removed with an earlier one answers 404, which is the wanted end state.
      for (const run of receipt.imports) {
        try {
          posts += (await api.remove(w, run.id)).posts ?? 0;
        } catch (failure) {
          if (!(failure instanceof ApiError && failure.status === 404)) throw failure;
        }
      }
      toast.success(`${t('Import deleted. Posts removed', '匯入已刪除。已移除的貼文', '导入已删除。已移除的帖子')}: ${number(posts)}`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : '');
    } finally {
      setWorking('');
      void invalidate();
    }
  }

  return (
    <Band as='section' aria-labelledby={`${id}-title`} data-testid={`voice-import-receipt-${receipt.provider}`}>
      <header className='flex min-w-0 flex-wrap items-center gap-3'>
        <ChannelIcon platform={receipt.provider} name={name} size='md' />
        <div className='min-w-0 flex-1'>
          <h4 id={`${id}-title`} className='text-foreground text-sm font-medium break-words'>
            {name} · {receipt.label}
          </h4>
          <div className='mt-1 flex flex-wrap gap-1.5'>
            {receipt.routes.includes('official_api') && <StatusChip icon='link'>{t('Connected account', '已連接帳戶', '已连接账户')}</StatusChip>}
            {receipt.routes.includes('platform_export') && <StatusChip icon='page'>{t('Export file', '匯出檔案', '导出文件')}</StatusChip>}
            {receipt.voiceScope && <StatusChip icon={null}>{receipt.voiceScope === 'separate' ? t('Kept separate', '分開保留', '分开保留') : t('Blended into the brand voice', '融入品牌風格', '融入品牌风格')}</StatusChip>}
          </div>
        </div>
      </header>

      <div role='status' aria-live='polite' className='flex min-w-0 flex-col gap-1 text-sm'>
        {latest && (
          <p className='text-foreground flex items-center gap-2 font-medium'>
            {active && <Icons.spinner className='size-4 shrink-0 motion-safe:animate-spin' aria-hidden />}
            {runStatus(latest, t)}
          </p>
        )}
        {latest?.failure && (
          <p>
            {t('Reason', '原因', '原因')}: {latest.failure.replace(/[_-]+/g, ' ')}
            {latest.retryAt && active ? ` · ${t('Rafii tries again at', 'Rafii 將於以下時間再試：', 'Rafii 将于以下时间重试：')} ${locale.formatDateTime(latest.retryAt)}` : ''}
          </p>
        )}
        {latest?.route === 'platform_export' && latest.status === 'receiving' && (
          <p className='text-muted-foreground'>{t('If this upload was interrupted, cancel it and upload the files again.', '如上載曾經中斷，請取消後再上載檔案。', '如上传曾经中断，请取消后重新上传文件。')}</p>
        )}
        {account ? (
          <ul className='text-muted-foreground flex flex-col gap-1'>
            {accountLines(account, locale.language).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className='text-muted-foreground'>{t('No posts stored yet.', '尚未儲存任何貼文。', '尚未保存任何帖子。')}</p>
        )}
        {runFacts.some(([, value]) => value > 0) && (
          <dl className='text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs'>
            {runFacts
              .filter(([, value]) => value > 0)
              .map(([fact, value]) => (
                <div key={fact} className='flex gap-1'>
                  <dt>{fact}:</dt>
                  <dd className='tabular-nums'>{number(value)}</dd>
                </div>
              ))}
          </dl>
        )}
        {latest && (
          <p className='text-muted-foreground text-xs'>
            {latest.lastSyncAt || latest.updatedAt ? `${t('Last updated', '最後更新', '最后更新')}: ${locale.formatDateTime(latest.lastSyncAt ?? latest.updatedAt)}` : ''}
            {latest.requestedSince ? ` · ${t('Asked for posts since', '要求讀取的起始日期', '要求读取的起始日期')}: ${locale.formatDate(latest.requestedSince)}` : ''}
          </p>
        )}
      </div>

      {error && <StateMessage kind='error' layout='inline' title={error} />}

      <div className='flex flex-wrap gap-2'>
        <Button variant='quiet' className='min-h-11' aria-expanded={showPosts} aria-controls={`${id}-posts`} onClick={() => setShowPosts((open) => !open)}>
          {showPosts ? t('Hide posts', '隱藏貼文', '隐藏帖子') : t('Show posts', '顯示貼文', '显示帖子')}
        </Button>
        {canManage && active && (
          <Button variant='glass' className='min-h-11' disabled={Boolean(working)} onClick={() => void act('cancel', active)}>
            {working === 'cancel' ? t('Cancelling…', '正在取消…', '正在取消…') : t('Cancel import', '取消匯入', '取消导入')}
          </Button>
        )}
        {canManage && canRefresh && latest && (
          <Button variant='glass' className='min-h-11' disabled={Boolean(working)} onClick={() => void act('refresh', latest)}>
            <Icons.refresh aria-hidden /> {working === 'refresh' ? t('Starting…', '正在開始…', '正在开始…') : t('Read new posts', '讀取新貼文', '读取新帖子')}
          </Button>
        )}
        {/* Red text on the translucent panel falls below 4.5:1 (axe color-contrast); the confirmation dialog marks the
            danger, so only the decorative icon is red here. */}
        {canManage && receipt.imports.length > 0 && (
          <Button variant='quiet' className='min-h-11' disabled={Boolean(working)} onClick={() => setConfirming(true)}>
            <Icons.trash aria-hidden className='text-destructive' /> {working === 'delete' ? t('Deleting…', '正在刪除…', '正在删除…') : t('Delete import', '刪除匯入', '删除导入')}
          </Button>
        )}
      </div>
      <div id={`${id}-posts`}>{showPosts && <EvidenceBrowser provider={receipt.provider} accountKey={receipt.accountKey} canEdit={canEdit} t={t} />}</div>

      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t('Delete this import?', '刪除此次匯入？', '删除此次导入？')} {name} · {receipt.label}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {t(
                'Rafii removes the posts this account supplied. A voice proposal built from them has to be built again. This cannot be undone.',
                'Rafii 會移除此帳戶提供的貼文。以這些貼文建立的風格提案需要重新建立。此操作無法復原。',
                'Rafii 会移除此账户提供的帖子。以这些帖子建立的风格提案需要重新建立。此操作无法撤销。'
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className='min-h-11'>{t('Keep the import', '保留匯入', '保留导入')}</AlertDialogCancel>
            <Button variant='destructive' className='min-h-11' onClick={() => void remove()}>
              {t('Delete import and posts', '刪除匯入及貼文', '删除导入及帖子')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Band>
  );
}
