'use client';

import { useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';
import { ApiError } from '@/lib/api/client';
import { MIN_ELIGIBLE } from '@/lib/voice-import/coverage';
import type { VoiceAnalysis, VoiceAnalysisOption, VoiceAnalysisQuote } from '@/lib/voice-import/types';
import { AdvancedProvider, AnalysisQualitySlider, type QualityStopView } from '../analysis-quality-slider';
import { initialQuality, makerLabel, makerOf, quoteCredits, quoteLive, quoteUsd, type QualityId } from '../analysis-quality';
import type { BrainTranslate } from '../brain-types';
import { useInvalidateVoiceImports, useVoiceImportApi } from './use-voice-import';

const RUNNING = new Set(['queued', 'running']);

/**
 * The AI reading of imported posts: the owner picks a quality on the slider, sees that stop's own quote (credits, or
 * US$ and writing batches before credit billing), approves it, and the cron worker reads the posts. Moving the slider
 * never spends anything; only the approved start does, up to the quoted limit. The measured proposal never waits.
 */
export function VoiceImportAnalysis({
  groupKey,
  eligible,
  isOwner,
  analysis,
  t
}: {
  groupKey: string;
  eligible: number;
  isOwner: boolean;
  analysis?: VoiceAnalysis | null;
  t: BrainTranslate;
}) {
  const headingId = useId();
  const locale = useGenUiLocale();
  const { api, w, enabled } = useVoiceImportApi();
  const client = useQueryClient();
  const invalidate = useInvalidateVoiceImports();
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<QualityId | null>(null);
  const [approvedFor, setApprovedFor] = useState('');
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState('');
  const group = groupKey === 'brand' ? undefined : groupKey;
  const running = RUNNING.has(analysis?.status ?? '');
  // Its own key, outside the receipt's: refreshing the receipt (after a start, say) must never re-ask for quotes.
  const optionsKey = ['voice-import-analysis-options', w, groupKey] as const;
  const options = useQuery({
    queryKey: optionsKey,
    queryFn: () => api.analysisOptions(w, group),
    enabled: enabled && open && isOwner && !running,
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false
  });

  const rows: VoiceAnalysisOption[] = options.data?.options ?? [];
  const quality = chosen && rows.some((row) => row.id === chosen && row.available && row.quote) ? chosen : initialQuality(stopsOf(rows), options.data?.defaultQuality);
  const selected = rows.find((row) => row.id === quality) ?? null;
  // "Advanced · choose AI provider": a provider's own quote, asked for only when one is picked for this quality.
  const [provider, setProvider] = useState<{ quality: QualityId; model: string } | null>(null);
  const picked = provider && provider.quality === quality && selected?.choices?.some((choice) => choice.model === provider.model && choice.available) ? provider.model : null;
  const providerQuote = useQuery({
    queryKey: ['voice-import-analysis-quote', w, groupKey, quality, picked],
    queryFn: () => api.analysisQuote(w, group, quality, picked ?? undefined),
    enabled: enabled && open && isOwner && !running && Boolean(picked) && Boolean(quality),
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false
  });
  const quote = picked ? (providerQuote.data?.quote ?? null) : (selected?.quote ?? null);
  const approved = Boolean(quote) && approvedFor === quote?.id;
  const live = quoteLive(quote);

  function costLine(item: VoiceAnalysisQuote | null): string | null {
    if (!item) return null;
    const credits = quoteCredits(item);
    if (credits !== null) return `${t('about', '約', '约')} ${locale.formatNumber(credits)} ${t('credits', '點數', '点数')}`;
    const usd = quoteUsd(item);
    return usd === null ? null : `US$${usd < 0.01 ? usd.toFixed(4) : usd.toFixed(2)}`;
  }

  function stopsOf(items: VoiceAnalysisOption[]): QualityStopView[] {
    return items.map((item) => ({
      id: item.id,
      model: item.model,
      available: item.available && Boolean(item.quote),
      cost: costLine(item.quote),
      note:
        item.reason === 'credit_limit'
          ? t('Not enough credits', '點數不足', '点数不足')
          : item.reason === 'not_offered' || !item.available
            ? t('Not offered here', '此處未有提供', '此处未提供')
            : null
    }));
  }

  async function start() {
    if (!quote || !quality || !approved || starting) return;
    setStarting(true);
    setProblem('');
    try {
      await api.analysisStart(w, quote.id, group, quality, picked ?? undefined);
      toast.success(t('The AI reading has started. Your current voice stays as it is.', 'AI 解讀已開始，目前的風格保持不變。', 'AI 解读已开始，目前的风格保持不变。'));
      setOpen(false);
      setApprovedFor('');
      setProvider(null);
      client.removeQueries({ queryKey: optionsKey });   // used quotes; the next reading asks afresh
      client.removeQueries({ queryKey: ['voice-import-analysis-quote', w] });
      await invalidate();
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'voice_analysis_quote_stale') {
        setProblem(t('This quote is no longer current. Check the new cost and approve again.', '此報價已不是最新，請查看新費用後再次批准。', '此报价已不是最新，请查看新费用后再次批准。'));
        setApprovedFor('');
        await (picked ? providerQuote.refetch() : options.refetch());
      } else {
        setProblem(failure instanceof Error ? failure.message : t('The AI reading could not start.', '未能開始 AI 解讀。', '无法开始 AI 解读。'));
      }
    } finally {
      setStarting(false);
    }
  }

  if (running) return null; // the panel's status line shows the reading in progress
  if (!isOwner) {
    return <p className='text-muted-foreground text-xs'>{t('Only an owner can approve an AI reading, because it uses credits.', '只有擁有者可批准 AI 解讀，因為會用到點數。', '仅所有者可批准 AI 解读，因为会用到点数。')}</p>;
  }

  return (
    <section className='flex min-w-0 flex-col gap-3 border-t pt-4' aria-labelledby={headingId} data-testid='voice-import-ai'>
      <h4 id={headingId} className='text-foreground text-sm font-medium'>
        {t('Read your posts with AI', '用 AI 解讀你的貼文', '用 AI 解读你的帖子')}
      </h4>
      <p className='text-muted-foreground text-sm leading-relaxed'>
        {t(
          'Optional. An AI model reads the posts above and adds observations to the proposal. Higher quality reads more carefully and uses more credits. Nothing becomes active until you approve the proposal.',
          '可選。AI 模型會閱讀上面的貼文，並在提案中加入觀察。質素越高，解讀越仔細，用的點數亦越多。在你批准提案之前，不會有任何改變。',
          '可选。AI 模型会阅读上面的帖子，并在提案中加入观察。质量越高，解读越仔细，用的点数也越多。在你批准提案之前，不会有任何改变。'
        )}
      </p>
      {!open ? (
        <div>
          <Button variant='glass' className='min-h-11' data-testid='voice-import-ai-open' disabled={eligible < MIN_ELIGIBLE} onClick={() => setOpen(true)}>
            {t('Choose quality and see the cost', '選擇質素並查看費用', '选择质量并查看费用')}
          </Button>
        </div>
      ) : options.isPending ? (
        <p role='status' className='text-muted-foreground flex items-center gap-2 text-sm'>
          <Icons.spinner className='motion-safe:animate-spin' aria-hidden /> {t('Working out the cost of each quality…', '正在計算每種質素的費用…', '正在计算每种质量的费用…')}
        </p>
      ) : options.isError ? (
        <StateMessage kind='error' layout='inline' title={explain(options.error, t)} />
      ) : (
        <div className='flex min-w-0 flex-col gap-4'>
          <AnalysisQualitySlider
            stops={stopsOf(rows)}
            value={quality}
            onChange={(next) => {
              setChosen(next);
              setApprovedFor('');
            }}
            disabled={starting}
            t={t}
          />
          <AdvancedProvider
            choices={selected?.choices}
            value={picked}
            onChange={(model) => {
              setProvider(model && quality ? { quality, model } : null);
              setApprovedFor('');
            }}
            disabled={starting}
            t={t}
          />
          {picked && providerQuote.isPending && (
            <p role='status' className='text-muted-foreground text-sm'>
              {t('Working out this provider’s cost…', '正在計算此供應商的費用…', '正在计算此供应商的费用…')}
            </p>
          )}
          {picked && providerQuote.isError && <StateMessage kind='error' layout='inline' title={explain(providerQuote.error, t)} />}
          {quote && (
            <dl className='grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm' data-testid='voice-import-ai-quote'>
              <dt className='text-muted-foreground'>{t('Posts it reads', '會閱讀的貼文', '会阅读的帖子')}</dt>
              <dd className='tabular-nums'>{locale.formatNumber(quote.posts)}</dd>
              <dt className='text-muted-foreground'>{t('Most it can cost', '最高費用', '最高费用')}</dt>
              <dd className='tabular-nums' data-testid='voice-import-ai-cost'>
                {costLine(quote)}
                {quoteCredits(quote) === null && quote.writingBatches > 0 ? ` · ${locale.formatNumber(quote.writingBatches)} ${t('writing batches of your plan', '個計劃寫作額度', '个计划写作额度')}` : ''}
              </dd>
              <dt className='text-muted-foreground'>{t('Price holds until', '報價有效至', '报价有效至')}</dt>
              <dd>{locale.formatDateTime(quote.expiresAt)}</dd>
            </dl>
          )}
          {quote && (
            <label className='flex min-h-11 items-center gap-3 text-sm'>
              <Checkbox checked={approved} onCheckedChange={(value) => setApprovedFor(value === true ? quote.id : '')} disabled={!live || starting} data-testid='voice-import-ai-approve' />
              {t('Approve one AI reading of these posts at this quality, up to the cost shown.', '按顯示的費用上限，批准以此質素對這些貼文作一次 AI 解讀。', '按显示的费用上限，批准以此质量对这些帖子作一次 AI 解读。')}
            </label>
          )}
          {quote && (
            <p className='text-muted-foreground text-xs' data-testid='voice-import-ai-egress'>
              {t(
                `Your posts are sent to ${makerLabel(makerOf(quote.model))} through Rafii’s AI gateway for this reading only.`,
                `你的貼文只會為這次解讀，經 Rafii 的 AI 閘道傳送至 ${makerLabel(makerOf(quote.model))}。`,
                `你的帖子只会为这次解读，经 Rafii 的 AI 网关发送至 ${makerLabel(makerOf(quote.model))}。`
              )}
            </p>
          )}
          {quote && !live && <p role='alert' className='text-sm'>{t('This price has expired. Refresh it before approving.', '此報價已過期，請先更新再批准。', '此报价已过期，请先更新再批准。')}</p>}
          <div className='flex flex-wrap items-center gap-2'>
            <Button variant='action' className='min-h-11' data-testid='voice-import-ai-start' disabled={!approved || !live || starting} onClick={() => void start()}>
              {starting ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' aria-hidden /> {t('Starting…', '正在開始…', '正在开始…')}
                </>
              ) : (
                t('Start the AI reading', '開始 AI 解讀', '开始 AI 解读')
              )}
            </Button>
            <Button
              variant='glass'
              className='min-h-11'
              disabled={starting || options.isFetching}
              onClick={() => {
                setApprovedFor('');
                void options.refetch();
              }}
            >
              {t('Refresh prices', '更新報價', '更新报价')}
            </Button>
            <Button variant='ghost' className='min-h-11' disabled={starting} onClick={() => setOpen(false)}>
              {t('Not now', '暫時不用', '暂时不用')}
            </Button>
          </div>
          {problem && (
            <p role='alert' className='text-sm'>
              {problem}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function explain(error: unknown, t: BrainTranslate): string {
  const code = error instanceof ApiError ? error.code : undefined;
  if (code === 'not_enough_posts') return t('AI reading needs at least three posts you wrote.', 'AI 解讀最少需要三篇由你撰寫的貼文。', 'AI 解读至少需要三篇由你撰写的帖子。');
  if (code === 'voice_analysis_active') return t('An AI reading of this voice is already running.', '此風格的 AI 解讀已在進行中。', '此风格的 AI 解读已在进行中。');
  if (code === 'analysis_route_unavailable' || code === 'voice_analysis_unavailable' || code === 'feature_disabled')
    return t('AI reading is not offered in this workspace right now. The measured proposal still works.', '此工作區現時未有提供 AI 解讀，量度得出的提案仍可使用。', '此工作区目前未提供 AI 解读，测量得出的提案仍可使用。');
  return error instanceof Error && error.message ? error.message : t('The prices could not be loaded.', '未能載入報價。', '无法加载报价。');
}
