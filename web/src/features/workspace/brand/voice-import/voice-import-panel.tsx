'use client';

import { useId, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { useChannels } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { accountReceipts, coverageLines, coverageStates, coverageTotals, MIN_ELIGIBLE, voiceGroups } from '@/lib/voice-import/coverage';
import type { VoiceImportsView } from '@/lib/voice-import/types';
import { SelectField } from '../../rafii-parts';
import { useBrainCopy } from '../brain-copy';
import type { BrainAction, BrainTranslate } from '../brain-types';
import { MANUAL_SETUP_HREF, REVIEW_HREF } from './deep-link';
import { PlatformRow } from './voice-import-platform';
import { AccountReceiptCard, CoverageStates } from './voice-import-receipt';
import { useVoiceImports, useWorkspaceAction } from './use-voice-import';

export interface VoiceImportPanelProps {
  /** Brand Brain passes its own fenced action runner and busy flag; anywhere else the panel runs the action itself. */
  run?: BrainAction;
  busy?: boolean;
  /** Opened from one account's card: that platform comes first, with its flow open on that account. */
  focus?: { provider: string; connectionId?: string };
  /** Inside Brand Brain the review and the no-samples setup are steps on the same page; elsewhere they are links. */
  onReview?: () => void;
  onManualSetup?: () => void;
  /** Inside a sheet, the sheet is the surface. */
  bare?: boolean;
}

/**
 * Import of a person's own posts, with its coverage receipt. The list route is the server gate: while voice import
 * is switched off (404) or its answer has not arrived, nothing is rendered, so the page looks exactly as it did.
 */
export function VoiceImportPanel(props: VoiceImportPanelProps) {
  const t = useBrainCopy();
  const { query, view, unavailable } = useVoiceImports({ poll: true });
  if (unavailable || query.isPending) return null;
  if (!view) {
    return (
      <StateMessage
        kind='error'
        layout='inline'
        title={t('The import receipt could not be loaded.', '未能載入匯入收據。', '无法加载导入回执。')}
        action={
          <Button variant='glass' className='min-h-11' onClick={() => void query.refetch()}>
            <Icons.refresh aria-hidden /> {t('Retry', '重試', '重试')}
          </Button>
        }
      />
    );
  }
  return <PanelBody {...props} view={view} stale={query.isError} t={t} />;
}

function ManualSetup({ onManualSetup, t }: { onManualSetup?: () => void; t: BrainTranslate }) {
  const label = t('Answer three short questions', '回答三條簡短問題', '回答三个简短问题');
  return (
    <div className='flex min-w-0 flex-col gap-2 text-sm'>
      <ol className='text-muted-foreground list-decimal space-y-1 ps-5'>
        <li>{t('What are you building?', '你想建立甚麼？', '你想建立什么？')}</li>
        <li>{t('Who is it for, and why?', '為誰而寫，目的是甚麼？', '为谁而写，目的是什么？')}</li>
        <li>{t('How should it sound?', '應該是甚麼語氣？', '应该是什么语气？')}</li>
      </ol>
      <div>
        {onManualSetup ? (
          <Button variant='glass' className='min-h-11' onClick={onManualSetup}>
            {label}
          </Button>
        ) : (
          <Link href={MANUAL_SETUP_HREF} className='rafii-focus text-foreground inline-flex min-h-11 items-center rounded-sm underline underline-offset-4'>
            {label}
          </Link>
        )}
      </div>
    </div>
  );
}

function PanelBody({ view, stale, run: outerRun, busy: outerBusy, focus, onReview, onManualSetup, bare, t }: VoiceImportPanelProps & { view: VoiceImportsView; stale: boolean; t: BrainTranslate }) {
  const headingId = useId();
  const locale = useGenUiLocale();
  const access = useWorkspaceAccess();
  const canManage = checkAccess(access, { permission: 'manage_connections' });
  const canEdit = checkAccess(access, { permission: 'edit' });
  const channels = useChannels();
  const own = useWorkspaceAction();
  const run = outerRun ?? own.run;
  const busy = outerBusy ?? own.busy;
  const [building, setBuilding] = useState(false);
  const [groupKey, setGroupKey] = useState('');
  const [built, setBuilt] = useState(false);

  const receipts = accountReceipts(view);
  const totals = coverageTotals(view.coverage);
  const proposed = coverageStates(view.coverage).find((state) => state.id === 'proposed')?.status ?? 'none';
  const groups = voiceGroups(view);
  const group = groups.find((item) => item.key === groupKey) ?? groups[0];
  const eligible = group?.eligible ?? 0;
  const rows = focus ? view.routes.toSorted((a, b) => Number(b.provider === focus.provider) - Number(a.provider === focus.provider)) : view.routes;
  const number = (value: number) => locale.formatNumber(value);
  const reviewLabel = t('Review the proposed voice', '審閱風格提案', '审阅风格提案');
  const analysis = view.analysis;
  const analysisWord: Record<string, string> = {
    queued: t('waiting to start', '等待開始', '等待开始'),
    running: t('in progress', '進行中', '进行中'),
    done: t('finished', '已完成', '已完成'),
    failed: t('stopped with an error', '因錯誤而停止', '因错误而停止'),
    cancelled: t('cancelled', '已取消', '已取消'),
    blocked: t('paused: the spending limit was reached', '已暫停：已達支出上限', '已暂停：已达支出上限')
  };

  async function build() {
    if (!group || building) return;
    setBuilding(true);
    const ok = await run('brand_brain_import_propose', group.key === 'brand' ? {} : { groupKey: group.key });
    setBuilding(false);
    if (!ok) return;
    setBuilt(true);
    toast.success(t('Proposal built. Nothing changes until it is reviewed and approved.', '提案已建立，經審閱及批准前不會有任何改變。', '提案已建立，经审阅及批准前不会有任何改变。'));
    onReview?.();
  }

  const body = (
    <>
      <div className='flex min-w-0 flex-col gap-2'>
        {/* In a sheet the sheet's own title is the visible heading; this one still names the section. */}
        <h2 id={headingId} className={bare ? 'sr-only' : 'text-foreground text-lg font-semibold tracking-tight'}>
          {t('Learn from your posts', '從你的貼文學習', '从你的帖子学习')}
        </h2>
        <p className='text-muted-foreground max-w-prose text-sm leading-relaxed'>
          {t(
            'Bring in an account’s posts once, with one consent for the whole account. Rafii shows what it read, what it left out and why, and proposes a voice you review before anything uses it.',
            '一次過匯入帳戶的貼文，整個帳戶只需同意一次。Rafii 會顯示讀取了甚麼、沒有採用甚麼及原因，並提出風格提案，經你審閱後才會使用。',
            '一次性导入账户的帖子，整个账户只需同意一次。Rafii 会显示读取了什么、没有采用什么及原因，并提出风格提案，经你审阅后才会使用。'
          )}
        </p>
      </div>

      {stale && <StateMessage kind='stale' layout='inline' title={t('This receipt may be out of date: the latest refresh did not arrive.', '此收據可能並非最新：最近一次更新未能送達。', '此回执可能并非最新：最近一次更新未能送达。')} />}

      <CoverageStates coverage={view.coverage} t={t} />
      <div role='status' aria-live='polite' data-testid='voice-import-summary'>
        <ul className='text-foreground flex min-w-0 flex-col gap-1 text-sm'>
          {coverageLines(view.coverage, locale.language).map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
      {!canManage && (
        <p className='text-muted-foreground text-xs'>
          {t('You can read this receipt. Starting, cancelling or deleting an import needs a member who can manage connections.', '你可查看此收據。開始、取消或刪除匯入需要由可管理連接的成員操作。', '你可查看此回执。开始、取消或删除导入需要由可管理连接的成员操作。')}
        </p>
      )}

      {receipts.length > 0 ? (
        <section className='flex min-w-0 flex-col gap-3' aria-labelledby={`${headingId}-read`}>
          <h3 id={`${headingId}-read`} className='text-foreground text-base font-medium'>
            {t('What Rafii has read', 'Rafii 已讀取的內容', 'Rafii 已读取的内容')}
          </h3>
          {receipts.map((receipt) => (
            <AccountReceiptCard key={receipt.key} receipt={receipt} canManage={canManage} canEdit={canEdit} t={t} />
          ))}
        </section>
      ) : (
        <section className='flex min-w-0 flex-col gap-3' aria-labelledby={`${headingId}-empty`}>
          <h3 id={`${headingId}-empty`} className='text-foreground text-base font-medium'>
            {t('No posts yet', '尚未有貼文', '尚无帖子')}
          </h3>
          <p className='text-muted-foreground text-sm'>
            {t(
              'Connect an account or upload an export below. If you have no posts to learn from, you can set the voice yourself:',
              '請在下方連接帳戶或上載匯出檔。如你沒有貼文可供學習，亦可自行設定風格：',
              '请在下方连接账户或上传导出文件。如你没有帖子可供学习，也可自行设置风格：'
            )}
          </p>
          <ManualSetup onManualSetup={onManualSetup} t={t} />
        </section>
      )}

      {totals.retrieved > 0 && (
        <section className='flex min-w-0 flex-col gap-3' aria-labelledby={`${headingId}-proposal`} data-testid='voice-import-proposal'>
          <h3 id={`${headingId}-proposal`} className='text-foreground text-base font-medium'>
            {t('Voice proposal', '風格提案', '风格提案')}
          </h3>
          {groups.length > 1 && (
            <SelectField label={t('Voice to build', '要建立的風格', '要建立的风格')} value={group?.key ?? ''} onChange={(event) => setGroupKey(event.target.value)} className='sm:max-w-md'>
              {groups.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.key === 'brand' ? t('This brand’s voice', '此品牌的風格', '此品牌的风格') : `${item.label ?? item.key} · ${t('kept separate', '分開保留', '分开保留')}`} ({number(item.eligible ?? 0)})
                </option>
              ))}
            </SelectField>
          )}
          {eligible < MIN_ELIGIBLE ? (
            <div className='flex min-w-0 flex-col gap-3' data-testid='voice-import-sparse'>
              <StateMessage
                kind='partial'
                layout='inline'
                title={t('Not enough writing yet', '文字尚未足夠', '文字尚不足够')}
                description={`${t('Posts that can be used', '可使用的貼文', '可使用的帖子')}: ${number(eligible)}. ${t('Rafii needs at least 3 to describe a voice.', 'Rafii 最少需要 3 篇才可描述風格。', 'Rafii 至少需要 3 篇才能描述风格。')}`}
              />
              <ul className='text-muted-foreground list-disc space-y-1 ps-5 text-sm'>
                {totals.waiting > 0 && (
                  <li>
                    {t('Posts waiting for an author', '等待確認作者的貼文', '等待确认作者的帖子')}: {number(totals.waiting)}. {t('Open “Show posts” on the account and mark the ones you wrote.', '請在帳戶上開啟「顯示貼文」，標記由你撰寫的貼文。', '请在账户上打开“显示帖子”，标记由你撰写的帖子。')}
                  </li>
                )}
                <li>{t('Bring in another account, or upload an export, from the list below.', '在下方清單匯入另一個帳戶，或上載匯出檔。', '在下方列表导入另一个账户，或上传导出文件。')}</li>
                <li>{t('Or set the voice yourself with three short questions:', '或回答三條簡短問題，自行設定風格：', '或回答三个简短问题，自行设置风格：')}</li>
              </ul>
              <ManualSetup onManualSetup={onManualSetup} t={t} />
            </div>
          ) : (
            <div className='flex min-w-0 flex-col gap-3'>
              <p className='text-sm leading-relaxed'>
                {t('Posts this proposal would be built from', '用來建立此提案的貼文', '用来建立此提案的帖子')}: <span className='font-medium tabular-nums'>{number(eligible)}</span>.{' '}
                {t(
                  'Building it writes a proposal only. The approved voice stays as it is until an owner approves the proposal.',
                  '建立提案只會寫入一份提案；在擁有者批准之前，已批准的風格保持不變。',
                  '建立提案只会写入一份提案；在所有者批准之前，已批准的风格保持不变。'
                )}
              </p>
              <div role='status' aria-live='polite' className='text-sm'>
                {proposed === 'done' && <p>{t('A proposal built from your posts is waiting for review.', '以你的貼文建立的提案正等待審閱。', '以你的帖子建立的提案正等待审阅。')}</p>}
                {proposed === 'partial' && <p>{t('The proposal is out of date because the posts behind it changed. Build it again.', '提案背後的貼文已有變更，提案已過時，請重新建立。', '提案背后的帖子已有变更，提案已过时，请重新建立。')}</p>}
              </div>
              <div className='flex flex-wrap items-center gap-2'>
                <Button variant='action' className='min-h-11' data-testid='voice-import-build' disabled={!canEdit || busy || building} onClick={() => void build()}>
                  {building ? (
                    <>
                      <Icons.spinner className='motion-safe:animate-spin' aria-hidden /> {t('Building…', '正在建立…', '正在建立…')}
                    </>
                  ) : proposed === 'none' ? (
                    t('Build voice proposal', '建立風格提案', '建立风格提案')
                  ) : (
                    t('Build the proposal again', '重新建立提案', '重新建立提案')
                  )}
                </Button>
                {(proposed !== 'none' || built) &&
                  (onReview ? (
                    <Button variant='glass' className='min-h-11' onClick={onReview}>
                      {reviewLabel}
                    </Button>
                  ) : (
                    <Link href={REVIEW_HREF} className='rafii-focus text-foreground inline-flex min-h-11 items-center rounded-sm underline underline-offset-4'>
                      {reviewLabel}
                    </Link>
                  ))}
              </div>
              {!canEdit && <p className='text-muted-foreground text-xs'>{t('Building a proposal needs edit access.', '建立提案需要編輯權限。', '建立提案需要编辑权限。')}</p>}
              {!outerRun && own.error && <StateMessage kind='error' layout='inline' title={own.error} />}
            </div>
          )}
          {analysis?.status && (
            <p className='text-muted-foreground text-xs'>
              {t('AI reading of your posts', 'AI 解讀你的貼文', 'AI 解读你的帖子')}: {analysisWord[analysis.status] ?? analysis.status.replace(/_/g, ' ')}
              {typeof analysis.analysed === 'number' && typeof analysis.eligible === 'number' ? ` · ${t('Posts read', '已讀取的貼文', '已读取的帖子')}: ${number(analysis.analysed)} / ${number(analysis.eligible)}` : ''}
            </p>
          )}
        </section>
      )}

      <section className='flex min-w-0 flex-col gap-3' aria-labelledby={`${headingId}-add`}>
        <h3 id={`${headingId}-add`} className='text-foreground text-base font-medium'>
          {t('Add posts from a platform', '從平台加入貼文', '从平台添加帖子')}
        </h3>
        {rows.length ? (
          <ul className='flex min-w-0 flex-col gap-3'>
            {rows.map((row) => (
              <PlatformRow key={row.provider} row={row} channels={channels.data?.channels ?? []} providers={channels.data?.providers ?? []} receipts={receipts} canManage={canManage} t={t} focus={focus?.provider === row.provider ? { connectionId: focus.connectionId } : undefined} />
            ))}
          </ul>
        ) : (
          <StateMessage kind='unsupported' layout='inline' title={t('No platform can be imported in this workspace right now.', '此工作區現時未有可匯入的平台。', '此工作区目前没有可导入的平台。')} />
        )}
      </section>
    </>
  );

  if (bare)
    return (
      <section aria-labelledby={headingId} className='flex min-w-0 flex-col gap-5' data-testid='voice-import-panel'>
        {body}
      </section>
    );
  return (
    <Surface as='section' material='quiet' aria-labelledby={headingId} className='flex min-w-0 flex-col gap-5' data-testid='voice-import-panel'>
      {body}
    </Surface>
  );
}
