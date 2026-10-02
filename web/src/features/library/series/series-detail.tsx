'use client';

import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type Ref } from 'react';
import Image from 'next/image';
import { useInView } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Checkbox } from '@/components/motion/checkbox';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { useAssetImage } from '@/features/library/asset-card';
import { StatusChip } from '@/features/queue/status-chip';
import { panelStore } from '@/features/site-agent/store';
import { useSnapshot } from '@/lib/api/hooks';
import type { Asset } from '@/lib/api/types';
import { useInlineForm, type FocusTarget } from '@/lib/growth-v2/inline-form';
import { errorCode, errorMessage } from '@/lib/growth-v2/request';
import { useDraftCheck, useFetchDraftCheck, useSeries, useSeriesChange, type SeriesChange } from '@/lib/growth-v2/series-hooks';
import type { DraftCheck, SeriesClaim, SeriesEpisode, SeriesMutation, SeriesView, SimilarityWarning } from '@/lib/growth-v2/series-types';
import { cn } from '@/lib/utils';
import {
  DRAFT_PAGE,
  IMAGE_PAGE,
  addDays,
  coverageLine,
  draftChips,
  draftOptionLabel,
  draftSearchText,
  episodeBrief,
  fill,
  imageOptionLabel,
  newestDrafts,
  newestImages,
  nextActionText,
  percent,
  pickPage,
  seriesErrorText,
  stateTone,
  withSelected,
  type SeriesCopy,
  type SeriesLocale
} from './series-copy';
import { useSeriesCopy, useSeriesLang } from './use-series-copy';

/** Saves one change and resolves with the re-read series; rejects with the server's answer, which the caller shows in place. */
type Run = (change: SeriesChange) => Promise<SeriesMutation>;
/** A one-click change (a button): its error shows at the top of the dialog. */
type Act = (change: SeriesChange) => void;
const HEADING = 'text-sm font-medium';
const FIELD = 'rafii-field h-11 rounded-[var(--rafii-radius-control)] px-3 text-base md:text-sm';

function WarningList({ copy, warnings }: { copy: SeriesCopy; warnings: { code: string; similarity: number; index?: number }[] }) {
  return (
    <ul className='flex flex-col gap-1 text-xs'>
      {warnings.map((warning, i) => (
        <li key={i} className='flex items-center gap-1.5'>
          <Icons.warning className='size-3.5 shrink-0' aria-hidden />
          {fill(copy.warning[warning.code as keyof SeriesCopy['warning']] ?? warning.code, { pct: percent(warning.similarity), n: warning.index ?? '' })}
        </li>
      ))}
    </ul>
  );
}

/** What the duplicate check says about the chosen draft: checking, a refusal, or the warnings to acknowledge. */
function CheckResult({ copy, check, warnings, acknowledged, onAcknowledge }: {
  copy: SeriesCopy;
  check: { isLoading: boolean; isError: boolean; error: unknown; data?: DraftCheck };
  warnings: SimilarityWarning[];
  acknowledged: boolean;
  onAcknowledge: (value: boolean) => void;
}) {
  if (check.isLoading) return <p role='status' className='text-muted-foreground text-sm'>{copy.checking}</p>;
  if (check.isError) return <p role='alert' className='text-destructive text-sm'>{seriesErrorText(copy, check.error, errorMessage(check.error))}</p>;
  if (check.data?.refusal) return <p role='alert' className='text-destructive text-sm'>{copy.refused}: {check.data.refusal.message}</p>;
  if (!warnings.length) return null;
  return (
    <div className='flex flex-col gap-2'>
      <WarningList copy={copy} warnings={warnings} />
      <Checkbox checked={acknowledged} onCheckedChange={(value) => onAcknowledge(Boolean(value))} label={copy.acknowledge} className='min-h-11 gap-2.5 [&>span]:text-sm' />
    </div>
  );
}

/** Choose an existing draft (newest first, searchable, a page at a time), see what the duplicate check says,
 *  acknowledge any near-duplicate, then add it. The form stays open until the server saved the link. */
function DraftPicker({ copy, series, episode, run, busy, onClose, returnFocus }: {
  copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; run: Run; busy: boolean; onClose: () => void; returnFocus: FocusTarget;
}) {
  const id = useId();
  const snapshot = useSnapshot();
  const linked = useMemo(() => new Set(series.episodes.flatMap((e) => e.drafts.map((d) => d.variantId))), [series]);
  const drafts = useMemo(() => newestDrafts(snapshot.data?.state.variants ?? [], linked), [snapshot.data, linked]);
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(DRAFT_PAGE);
  const [variantId, setVariantId] = useState<string | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const check = useDraftCheck(series.id, episode.id, variantId);
  const warnings = check.data?.variantId === variantId ? check.data?.warnings ?? [] : [];
  const page = useMemo(() => pickPage(drafts, query, draftSearchText, limit), [drafts, query, limit]);
  const options = withSelected(page.items, drafts, variantId);
  const { formRef, firstRef } = useInlineForm<HTMLInputElement>(true, onClose, { returnFocus, containEscape: true });
  const empty = !snapshot.isPending && !snapshot.isError && drafts.length === 0;
  const ready = Boolean(variantId && check.data?.variantId === variantId && !check.data.refusal && (!warnings.length || acknowledged));

  useEffect(() => {
    // Nothing to search: the way out gets focus instead of the page.
    if (empty) cancelRef.current?.focus();
  }, [empty]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !variantId || busy) return;
    setError(null);
    try {
      await run({ kind: 'link', id: series.id, revision: series.revision, episodeId: episode.id, variantId, acknowledgedWarnings: warnings.map((w) => w.id) });
      onClose();
    } catch (failure) {
      setError(seriesErrorText(copy, failure));
      if (errorCode(failure) === 'warnings_unacknowledged') {
        // The warnings changed since they were shown: show the current ones to acknowledge again.
        setAcknowledged(false);
        void check.refetch();
      }
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3' aria-label={copy.addDraft}>
      {empty ? (
        <p className='text-muted-foreground text-sm'>{copy.noDrafts}</p>
      ) : (
        <>
          <label htmlFor={`${id}-search`} className='text-sm font-medium'>{copy.searchDrafts}</label>
          <Input ref={firstRef} id={`${id}-search`} type='search' value={query} placeholder={copy.searchHint} autoComplete='off'
                 onChange={(event) => { setQuery(event.target.value); setLimit(DRAFT_PAGE); }} className={FIELD} />
          {snapshot.isPending ? (
            <p role='status' className='text-muted-foreground text-sm'>…</p>
          ) : snapshot.isError ? (
            <p role='alert' className='text-destructive text-sm'>{errorMessage(snapshot.error)}</p>
          ) : (
            <>
              <label htmlFor={`${id}-draft`} className='text-sm font-medium'>{copy.chooseDraft}</label>
              <NativeSelect id={`${id}-draft`} value={variantId ?? ''} aria-describedby={`${id}-count`}
                            onChange={(event) => { setVariantId(event.target.value || null); setAcknowledged(false); setError(null); }} className='w-full'>
                <NativeSelectOption value=''>—</NativeSelectOption>
                {options.map((draft) => <NativeSelectOption key={draft.id} value={draft.id}>{draftOptionLabel(draft)}</NativeSelectOption>)}
              </NativeSelect>
              <p id={`${id}-count`} className='text-muted-foreground text-xs' aria-live='polite'>
                {page.total ? fill(copy.pickerCount, { shown: page.items.length, total: page.total }) : copy.noMatches}
              </p>
              {page.more && (
                <Button type='button' variant='quiet' size='lg' className='min-h-11 self-start' onClick={() => setLimit((value) => value + DRAFT_PAGE)}>{copy.showMore}</Button>
              )}
            </>
          )}
          {variantId && <CheckResult copy={copy} check={check} warnings={warnings} acknowledged={acknowledged} onAcknowledge={setAcknowledged} />}
        </>
      )}
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
      <div className='flex flex-wrap gap-2'>
        {!empty && <Button type='submit' variant='glass' size='lg' className='min-h-11' disabled={busy || !ready}>{copy.link}</Button>}
        <Button ref={cancelRef} type='button' variant='quiet' size='lg' className='min-h-11' onClick={onClose}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/** One Library image to choose, its thumbnail loaded only when it scrolls near (the Library's own cache key). */
function ImageChoice({ asset, name, checked, label, onChoose, inputRef }: { asset: Asset; name: string; checked: boolean; label: string; onChoose: () => void; inputRef?: Ref<HTMLInputElement> }) {
  const ref = useRef<HTMLLabelElement>(null);
  const near = useInView(ref, { once: true, margin: '120px 0px' });
  const image = useAssetImage(asset.id, near);
  return (
    <label ref={ref} className={cn('rafii-glass flex cursor-pointer flex-col gap-1.5 rounded-[var(--rafii-radius-control)] p-2 text-xs', checked && 'rafii-glass-selected')}>
      <span className='flex min-w-0 items-center gap-2'>
        <input ref={inputRef} type='radio' name={name} value={asset.id} checked={checked} onChange={onChoose} aria-label={label} className='shrink-0' />
        <span className='min-w-0 flex-1 truncate'>{label}</span>
      </span>
      <span className='bg-foreground/[0.06] block aspect-square w-full overflow-hidden rounded-[var(--rafii-radius-micro)]'>
        {image.data ? (
          <Image src={image.data} alt='' width={160} height={160} unoptimized className='size-full object-cover' />
        ) : image.isError ? (
          <span className='text-muted-foreground grid size-full place-items-center'><Icons.media className='size-4' aria-hidden /></span>
        ) : (
          <Skeleton className='size-full rounded-none' />
        )}
      </span>
    </label>
  );
}

/** Reference one Library image for the episode (images only, newest first, a page at a time; the image stays in Library). */
function ImagePicker({ copy, series, episode, run, busy, onClose, returnFocus }: {
  copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; run: Run; busy: boolean; onClose: () => void; returnFocus: FocusTarget;
}) {
  const id = useId();
  const snapshot = useSnapshot();
  const images = useMemo(() => newestImages(snapshot.data?.state.phase2?.assets ?? [], episode.assetIds), [snapshot.data, episode.assetIds]);
  const [limit, setLimit] = useState(IMAGE_PAGE);
  const [assetId, setAssetId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const { formRef, firstRef } = useInlineForm<HTMLInputElement>(true, onClose, { returnFocus, containEscape: true });
  const shown = images.slice(0, limit);

  useEffect(() => {
    // The choices appear once the workspace is read: focus the first (or the way out) unless the person moved on.
    if (snapshot.isPending) return;
    const active = document.activeElement;
    if (active && active !== document.body && !formRef.current?.contains(active)) return;
    (firstRef.current ?? cancelRef.current)?.focus();
  }, [snapshot.isPending, formRef, firstRef]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!assetId || busy) return;
    setError(null);
    try {
      await run({ kind: 'linkAsset', id: series.id, revision: series.revision, episodeId: episode.id, assetId });
      onClose();
    } catch (failure) {
      setError(seriesErrorText(copy, failure));
    }
  }

  return (
    <form ref={formRef} onSubmit={submit} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      <fieldset className='flex min-w-0 flex-col gap-2'>
        <legend className='mb-1 text-sm font-medium'>{copy.chooseImage}</legend>
        {snapshot.isPending ? (
          <p role='status' className='text-muted-foreground text-sm'>…</p>
        ) : snapshot.isError ? (
          <p role='alert' className='text-destructive text-sm'>{errorMessage(snapshot.error)}</p>
        ) : !images.length ? (
          <p className='text-muted-foreground text-sm'>{copy.noImages}</p>
        ) : (
          <>
            <ul className='grid grid-cols-2 gap-2 sm:grid-cols-3'>
              {shown.map((asset, index) => (
                <li key={asset.id} className='min-w-0'>
                  <ImageChoice asset={asset} name={`${id}-image`} checked={assetId === asset.id} label={imageOptionLabel(copy, asset)}
                               onChoose={() => { setAssetId(asset.id); setError(null); }} inputRef={index === 0 ? firstRef : undefined} />
                </li>
              ))}
            </ul>
            <p className='text-muted-foreground text-xs' aria-live='polite'>{fill(copy.pickerCount, { shown: shown.length, total: images.length })}</p>
            {images.length > limit && (
              <Button type='button' variant='quiet' size='lg' className='min-h-11 self-start' onClick={() => setLimit((value) => value + IMAGE_PAGE)}>{copy.showMore}</Button>
            )}
          </>
        )}
      </fieldset>
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
      <div className='flex flex-wrap gap-2'>
        {images.length > 0 && <Button type='submit' variant='glass' size='lg' className='min-h-11' disabled={busy || !assetId}>{copy.link}</Button>}
        <Button ref={cancelRef} type='button' variant='quiet' size='lg' className='min-h-11' onClick={onClose}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

/** A draft an automation run made for this episode: the same duplicate check as a chosen draft. With no warnings it is
 *  added at once; near-duplicates are shown for the person to acknowledge first, and a refusal is shown, never retried. */
function CandidateRow({ copy, series, episode, draft, run, busy }: {
  copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; draft: SeriesEpisode['candidateDrafts'][number]; run: Run; busy: boolean;
}) {
  const fetchCheck = useFetchDraftCheck();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [checking, setChecking] = useState(false);
  const [pending, setPending] = useState<DraftCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const formId = useId();

  async function add() {
    setError(null);
    setChecking(true);
    try {
      const check = await fetchCheck(series.id, episode.id, draft.variantId);
      if (check.refusal || check.warnings.length) {
        setPending(check);
        return;
      }
      await run({ kind: 'link', id: series.id, revision: series.revision, episodeId: episode.id, variantId: draft.variantId, acknowledgedWarnings: [] });
    } catch (failure) {
      setError(seriesErrorText(copy, failure));
    } finally {
      setChecking(false);
    }
  }

  /** The warnings changed under an open confirmation: show the current ones (or the refusal) instead. */
  async function recheck() {
    try {
      setPending(await fetchCheck(series.id, episode.id, draft.variantId));
    } catch (failure) {
      setPending(null);
      setError(seriesErrorText(copy, failure));
    }
  }

  return (
    <li className='flex flex-col gap-2 text-sm'>
      <div className='flex flex-wrap items-center gap-2'>
        <span className='text-muted-foreground min-w-0 flex-1 truncate text-xs'>{copy.candidate}: {draft.excerpt}</span>
        <Button ref={triggerRef} variant='glass' size='lg' className='min-h-11' disabled={busy || checking} aria-expanded={Boolean(pending)}
                aria-controls={pending ? formId : undefined} onClick={() => (pending ? setPending(null) : void add())}>
          {copy.link}
        </Button>
      </div>
      {checking && <p role='status' className='text-muted-foreground text-xs'>{copy.checking}</p>}
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
      {pending && (
        <CandidateConfirm id={formId} copy={copy} series={series} episode={episode} variantId={draft.variantId} check={pending} run={run} busy={busy}
                          onClose={() => setPending(null)} onRecheck={() => void recheck()} returnFocus={triggerRef} />
      )}
    </li>
  );
}

function CandidateConfirm({ id, copy, series, episode, variantId, check, run, busy, onClose, onRecheck, returnFocus }: {
  id: string; copy: SeriesCopy; series: SeriesView; episode: SeriesEpisode; variantId: string; check: DraftCheck; run: Run; busy: boolean;
  onClose: () => void; onRecheck: () => void; returnFocus: FocusTarget;
}) {
  const ackId = useId();
  const [acknowledged, setAcknowledged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const { formRef, firstRef } = useInlineForm<HTMLButtonElement>(true, onClose, { returnFocus, containEscape: true });
  const needsAck = !check.refusal && check.warnings.length > 0;
  const canLink = !check.refusal && (!needsAck || acknowledged);

  useEffect(() => {
    // The first thing to answer: the acknowledgement, or (no warnings any more) adding it; with a refusal, the way out.
    if (needsAck) document.getElementById(ackId)?.focus();
    else if (!check.refusal) submitRef.current?.focus();
    else firstRef.current?.focus();
  }, [check, needsAck, ackId, firstRef]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canLink || busy) return;
    setError(null);
    try {
      await run({ kind: 'link', id: series.id, revision: series.revision, episodeId: episode.id, variantId, acknowledgedWarnings: check.warnings.map((w) => w.id) });
      onClose();
    } catch (failure) {
      setError(seriesErrorText(copy, failure));
      if (errorCode(failure) === 'warnings_unacknowledged') {
        setAcknowledged(false);
        onRecheck();
      }
    }
  }

  return (
    <form id={id} ref={formRef} onSubmit={submit} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      {check.refusal ? (
        <p role='alert' className='text-destructive text-sm'>{copy.refused}: {check.refusal.message}</p>
      ) : needsAck ? (
        <>
          <WarningList copy={copy} warnings={check.warnings} />
          <Checkbox id={ackId} checked={acknowledged} onCheckedChange={(value) => setAcknowledged(Boolean(value))} label={copy.acknowledge} className='min-h-11 gap-2.5 [&>span]:text-sm' />
        </>
      ) : null}
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
      <div className='flex flex-wrap gap-2'>
        {!check.refusal && <Button ref={submitRef} type='submit' variant='glass' size='lg' className='min-h-11' disabled={busy || !canLink}>{copy.link}</Button>}
        <Button ref={check.refusal ? firstRef : undefined} type='button' variant='quiet' size='lg' className='min-h-11' onClick={onClose}>{check.refusal ? copy.close : copy.cancel}</Button>
      </div>
    </form>
  );
}

/** Shown when the clipboard refused: the brief, selected, so the person can copy it themselves. */
function BriefFallback({ copy, text, onClose, returnFocus }: { copy: SeriesCopy; text: string; onClose: () => void; returnFocus: FocusTarget }) {
  const id = useId();
  const { formRef, firstRef } = useInlineForm<HTMLTextAreaElement>(true, onClose, { returnFocus, containEscape: true });
  return (
    <form ref={formRef} onSubmit={(event) => { event.preventDefault(); onClose(); }} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] p-3'>
      <p role='alert' className='text-sm'>{copy.copyFailed}</p>
      <label htmlFor={`${id}-brief`} className='text-sm font-medium'>{copy.briefText}</label>
      <Textarea ref={firstRef} id={`${id}-brief`} readOnly rows={6} value={text} onFocus={(event) => event.currentTarget.select()} className='rafii-field text-base md:text-sm' />
      <Button type='submit' variant='quiet' size='lg' className='min-h-11 self-start'>{copy.close}</Button>
    </form>
  );
}

function EpisodeCard({ copy, lang, series, episode, canEdit, run, act, busy }: {
  copy: SeriesCopy; lang: SeriesLocale; series: SeriesView; episode: SeriesEpisode; canEdit: boolean; run: Run; act: Act; busy: boolean;
}) {
  const [picking, setPicking] = useState(false);
  const [pickingImage, setPickingImage] = useState(false);
  const [manualBrief, setManualBrief] = useState<string | null>(null);
  const draftTrigger = useRef<HTMLButtonElement>(null);
  const imageTrigger = useRef<HTMLButtonElement>(null);
  const copyTrigger = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const pickerId = useId();
  const decide = (decision: 'accept' | 'reject' | 'do_not_repeat', level: 'angle' | 'role' = 'angle') =>
    act({ kind: 'decide', id: series.id, revision: series.revision, episodeId: episode.id, decision, level });
  const open = episode.workflowState !== 'skipped';
  const producing = episode.workflowState === 'approved' || episode.workflowState === 'drafting' || episode.workflowState === 'drafted';

  async function copyBrief() {
    const text = episodeBrief(copy, series, episode);
    try {
      if (typeof navigator.clipboard?.writeText !== 'function') throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(text);
      setManualBrief(null);
      toast.success(<span lang={lang}>{copy.copied}</span>);
    } catch {
      setManualBrief(text);
    }
  }

  return (
    <Surface as='article' material='glass' radius='card' padding='md' aria-labelledby={titleId} className='flex flex-col gap-2'>
      <div className='flex flex-wrap items-center gap-2'>
        <h4 id={titleId} className='min-w-0 flex-1 text-sm font-medium'>{episode.index}. {copy.role[episode.role]}</h4>
        <StatusChip tone={stateTone(episode.state, episode.factState)}>{copy.state[episode.state]}</StatusChip>
        {episode.factState === 'needs_fact_review' && open && <StatusChip tone='warning'>{copy.factNeeds}</StatusChip>}
        {episode.angleDecision === 'accepted' && <StatusChip tone='neutral'>{copy.angleAccepted}</StatusChip>}
      </div>
      <dl className='grid gap-x-3 gap-y-1 text-sm sm:grid-cols-[6rem_minmax(0,1fr)]'>
        <dt className='text-muted-foreground'>{copy.question}</dt>
        <dd>{episode.question}</dd>
        <dt className='text-muted-foreground'>{copy.angle}</dt>
        <dd>{episode.angle.text}</dd>
      </dl>
      {episode.factReasons.length > 0 && open && (
        <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs'>
          {episode.factReasons.map((reason) => <li key={reason}>· {copy.reason[reason]}</li>)}
        </ul>
      )}
      {episode.drafts.length > 0 && (
        <ul className='flex flex-col gap-1.5'>
          {episode.drafts.map((draft) => (
            <li key={draft.variantId} className='rafii-quiet flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
              <span className='flex min-w-0 flex-1 flex-col gap-1'>
                <span className='font-medium'>{[draft.platform, draft.language].filter(Boolean).join(' · ')}</span>
                {draft.excerpt && <span className='text-muted-foreground block truncate text-xs'>{draft.excerpt}</span>}
                <span className='flex flex-wrap gap-1.5'>
                  {draftChips(copy, draft).map((chip) => <StatusChip key={chip.key} tone={chip.tone}>{chip.label}</StatusChip>)}
                </span>
                {draft.factGate && !draft.published && <span className='block text-xs'>{copy.gateNote}</span>}
                {draft.warnings.length > 0 && <WarningList copy={copy} warnings={draft.warnings} />}
              </span>
              {canEdit && !draft.published && (
                <Button variant='quiet' size='lg' className='min-h-11' disabled={busy}
                        onClick={() => act({ kind: 'unlink', id: series.id, revision: series.revision, episodeId: episode.id, variantId: draft.variantId })}>
                  {copy.unlink}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {episode.assets.length > 0 && (
        <div className='flex flex-wrap items-center gap-2 text-xs'>
          <span className='text-muted-foreground'>{fill(copy.images, { n: episode.assets.length })}</span>
          {episode.assets.some((asset) => !asset.available) && <span role='status'>{copy.imageGone}</span>}
          {canEdit && episode.assets.map((asset) => (
            <Button key={asset.assetId} variant='quiet' size='lg' className='min-h-11' disabled={busy}
                    aria-label={`${copy.unlink} ${asset.assetId.slice(0, 8)}`}
                    onClick={() => act({ kind: 'unlinkAsset', id: series.id, revision: series.revision, episodeId: episode.id, assetId: asset.assetId })}>
              {copy.unlink} · {asset.assetId.slice(0, 8)}
            </Button>
          ))}
        </div>
      )}
      {canEdit && episode.candidateDrafts.length > 0 && (
        <ul className='flex flex-col gap-1.5' aria-label={copy.candidate}>
          {episode.candidateDrafts.map((draft) => <CandidateRow key={draft.variantId} copy={copy} series={series} episode={episode} draft={draft} run={run} busy={busy} />)}
        </ul>
      )}
      {canEdit && open && (
        <div className='flex flex-wrap gap-2'>
          {episode.canApprove && (
            <Button variant='action' size='lg' className='min-h-11' disabled={busy} onClick={() => act({ kind: 'approve', id: series.id, revision: series.revision, episodeId: episode.id })}>
              {copy.approveNext}
            </Button>
          )}
          {producing && (
            <Button ref={draftTrigger} variant='glass' size='lg' className='min-h-11' aria-expanded={picking} aria-controls={picking ? `${pickerId}-draft` : undefined}
                    onClick={() => setPicking((value) => !value)}>
              {copy.addDraft}
            </Button>
          )}
          {producing && (
            <Button ref={imageTrigger} variant='quiet' size='lg' className='min-h-11' aria-expanded={pickingImage} aria-controls={pickingImage ? `${pickerId}-image` : undefined}
                    onClick={() => setPickingImage((value) => !value)}>
              {copy.addImage}
            </Button>
          )}
          {producing && episode.factState === 'ok' && (
            <Button variant='glass' size='lg' className='min-h-11' onClick={() => panelStore.ask(episodeBrief(copy, series, episode))}>
              <Icons.sparkles aria-hidden />
              {copy.draftWithRafii}
            </Button>
          )}
          <Button ref={copyTrigger} variant='quiet' size='lg' className='min-h-11' onClick={() => void copyBrief()}>
            <Icons.copy aria-hidden />
            {copy.copyBrief}
          </Button>
          {episode.angleDecision !== 'accepted' && <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('accept')}>{copy.accept}</Button>}
          {!episode.drafts.length && <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('reject')}>{copy.reject}</Button>}
          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('do_not_repeat')}>{copy.doNotRepeat}</Button>
          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => decide('do_not_repeat', 'role')}>{copy.doNotRepeatRole}</Button>
        </div>
      )}
      {manualBrief && <BriefFallback copy={copy} text={manualBrief} onClose={() => setManualBrief(null)} returnFocus={copyTrigger} />}
      {producing && <p className='text-muted-foreground text-xs'>{copy.draftNote}</p>}
      {canEdit && producing && picking && (
        <div id={`${pickerId}-draft`}>
          <DraftPicker copy={copy} series={series} episode={episode} run={run} busy={busy} onClose={() => setPicking(false)} returnFocus={draftTrigger} />
        </div>
      )}
      {canEdit && producing && pickingImage && (
        <div id={`${pickerId}-image`}>
          <ImagePicker copy={copy} series={series} episode={episode} run={run} busy={busy} onClose={() => setPickingImage(false)} returnFocus={imageTrigger} />
        </div>
      )}
    </Surface>
  );
}

/** Confirm a flagged fact is still true, or correct it, with the next review date. Open until the server saved it. */
function ClaimForm({ copy, series, claim, mode, run, busy, onClose, returnFocus }: {
  copy: SeriesCopy; series: SeriesView; claim: SeriesClaim; mode: 'review' | 'correct'; run: Run; busy: boolean; onClose: () => void; returnFocus: FocusTarget;
}) {
  const id = useId();
  // Fresh from the current fact every time the form opens: never the wording or date of an earlier visit.
  const [reviewBy, setReviewBy] = useState(() => addDays(new Date(), 180));
  const [text, setText] = useState(claim.text);
  const [error, setError] = useState<string | null>(null);
  const { formRef, firstRef } = useInlineForm<HTMLElement>(true, onClose, { returnFocus, containEscape: true });
  const setFirst = (node: HTMLElement | null) => {
    firstRef.current = node;
  };

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || (mode === 'correct' && !text.trim())) return;
    setError(null);
    try {
      await run({ kind: 'claim', id: series.id, revision: series.revision, claimId: claim.id,
                  action: mode === 'review' ? { action: 'reviewed', reviewBy } : { action: 'update', text: text.trim(), reviewBy } });
      onClose();
    } catch (failure) {
      setError(seriesErrorText(copy, failure));
    }
  }

  return (
    <form ref={formRef} className='flex flex-col gap-2' onSubmit={submit}>
      {mode === 'correct' && (
        <label htmlFor={`${id}-text`} className='flex flex-col gap-1 font-medium'>
          {copy.correctedText}
          <Textarea ref={setFirst} id={`${id}-text`} required maxLength={280} rows={2} value={text} onChange={(event) => setText(event.target.value)} className='rafii-field text-base md:text-sm' />
        </label>
      )}
      <label htmlFor={`${id}-date`} className='flex flex-col gap-1 font-medium'>
        {copy.reviewBy}
        <Input ref={mode === 'review' ? setFirst : undefined} id={`${id}-date`} type='date' required value={reviewBy} min={addDays(new Date(), 1)} max={addDays(new Date(), series.limits.reviewMaxDays)}
               onChange={(event) => setReviewBy(event.target.value)} className='rafii-field h-11 w-fit rounded-[var(--rafii-radius-control)] px-3' />
      </label>
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
      <div className='flex gap-2'>
        <Button type='submit' variant='glass' size='lg' className='min-h-11' disabled={busy || (mode === 'correct' && !text.trim())}>{copy.save}</Button>
        <Button type='button' variant='quiet' size='lg' className='min-h-11' onClick={onClose}>{copy.cancel}</Button>
      </div>
    </form>
  );
}

function ClaimRow({ copy, series, claim, canEdit, run, act, busy }: { copy: SeriesCopy; series: SeriesView; claim: SeriesClaim; canEdit: boolean; run: Run; act: Act; busy: boolean }) {
  const [mode, setMode] = useState<'idle' | 'review' | 'correct'>('idle');
  const rowRef = useRef<HTMLLIElement>(null);
  const reviewRef = useRef<HTMLButtonElement>(null);
  const correctRef = useRef<HTMLButtonElement>(null);
  const opener = useRef<'review' | 'correct'>('review');
  const flagged = claim.freshness.state !== 'ok' && claim.freshness.state !== 'removed';
  // Back to the button that opened the form; when the fact no longer needs a check, to the fact itself.
  const back = useCallback(() => (opener.current === 'review' ? reviewRef.current : correctRef.current) ?? correctRef.current ?? rowRef.current, []);
  const start = (next: 'review' | 'correct') => {
    opener.current = next;
    setMode(next);
  };
  return (
    <li ref={rowRef} tabIndex={-1} className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2.5 text-sm outline-none'>
      <div className='flex flex-wrap items-start gap-2'>
        <span className={claim.status === 'removed' ? 'text-muted-foreground min-w-0 flex-1 line-through' : 'min-w-0 flex-1'}>{claim.text}</span>
        {flagged && <StatusChip tone='warning'>{claim.freshness.reason ? copy.reason[claim.freshness.reason] : copy.factNeeds}</StatusChip>}
      </div>
      <span className='text-muted-foreground text-xs'>
        {copy.reviewBy}: {claim.reviewBy}{claim.support.title ? ` · ${claim.support.title}` : ''}
      </span>
      {canEdit && flagged && mode === 'idle' && (
        <div className='flex flex-wrap gap-2'>
          {claim.support.available && <Button ref={reviewRef} variant='glass' size='lg' className='min-h-11' onClick={() => start('review')}>{copy.stillTrue}</Button>}
          <Button ref={correctRef} variant='glass' size='lg' className='min-h-11' onClick={() => start('correct')}>{copy.correct}</Button>
          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => act({ kind: 'claim', id: series.id, revision: series.revision, claimId: claim.id, action: { action: 'remove' } })}>
            {copy.removeFact}
          </Button>
        </div>
      )}
      {mode !== 'idle' && (
        <ClaimForm key={mode} copy={copy} series={series} claim={claim} mode={mode} run={run} busy={busy} onClose={() => setMode('idle')} returnFocus={back} />
      )}
    </li>
  );
}

/** One series: the next action, which audience questions are covered, each episode with its facts, drafts and angle
 *  decisions, and the plan/status controls. Every change waits for the server's re-read before it shows. */
export function SeriesDetailDialog({ seriesId, onClose }: { seriesId: string | null; onClose: () => void }) {
  const copy = useSeriesCopy();
  const lang = useSeriesLang();
  const query = useSeries(seriesId);
  const change = useSeriesChange();
  const [count, setCount] = useState(2);
  const [error, setError] = useState<string | null>(null);
  const [shownId, setShownId] = useState(seriesId);
  if (shownId !== seriesId) {
    // Another series, or the dialog closed: nothing from the previous one carries over.
    setShownId(seriesId);
    setCount(2);
    setError(null);
  }
  const series = query.data?.series;
  const canEdit = Boolean(query.data?.canEdit);
  const busy = change.isPending;
  const run: Run = async (next) => {
    const data = await change.mutateAsync(next);
    if (data.verified) toast.success(<span lang={lang}>{copy.saved}</span>);
    else toast(<span lang={lang}>{copy.unverified}</span>);
    return data;
  };
  const act: Act = (next) => {
    setError(null);
    run(next).catch((failure: unknown) => setError(seriesErrorText(copy, failure)));
  };
  const live = series?.episodes.filter((episode) => episode.workflowState !== 'skipped') ?? [];
  const setAside = series?.episodes.filter((episode) => episode.workflowState === 'skipped') ?? [];
  return (
    <RafiiDialog open={Boolean(seriesId)} onOpenChange={(open) => !open && onClose()}>
      <RafiiDialogContent size='lg' lang={lang}>
        <RafiiDialogHeader title={series?.title ?? copy.sectionTitle} intro={series?.audienceQuestion} closeLabel={copy.cancel} eyebrow={series ? copy.status[series.status] : undefined} />
        <RafiiDialogBody className='flex flex-col gap-5'>
          {query.isError && <StateMessage kind='error' layout='inline' title={copy.loadError} description={seriesErrorText(copy, query.error, errorMessage(query.error))} />}
          {query.isPending && seriesId && <p role='status' className='text-muted-foreground text-sm'>…</p>}
          {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
          {series && (
            <>
              <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-1' role='status'>
                <span className='text-sm font-medium'>{nextActionText(copy, series)}</span>
                <span className='text-muted-foreground text-xs'>
                  {series.origin.available
                    ? series.origin.kind === 'post'
                      ? fill(copy.fromPost, { platform: series.origin.platform ?? '', date: series.origin.publishedAt ?? '' })
                      : fill(copy.fromSource, { title: series.origin.title ?? '' })
                    : copy.originGone}
                  {series.followers.length > 0 ? ` · ${fill(copy.followers, { n: series.followers.length })}` : ''}
                </span>
              </Surface>
              <section aria-labelledby='series-coverage' className='flex flex-col gap-2'>
                <h3 id='series-coverage' className={HEADING}>{copy.coverageHeading} · {coverageLine(copy, series.coverage.coveredCount, series.coverage.total)}</h3>
                <ul className='flex flex-col gap-1 text-sm'>
                  {series.coverage.questions.map((item) => (
                    <li key={item.episodeId} className='flex items-start gap-2'>
                      {item.covered ? <Icons.circleCheck className='mt-0.5 size-4 shrink-0' aria-hidden /> : <Icons.circleDashed className='text-muted-foreground mt-0.5 size-4 shrink-0' aria-hidden />}
                      <span>{item.index}. {item.question} <span className='text-muted-foreground'>({copy.state[item.state]})</span></span>
                    </li>
                  ))}
                </ul>
              </section>
              <section aria-labelledby='series-episodes' className='flex flex-col gap-3'>
                <h3 id='series-episodes' className={HEADING}>{copy.episodesHeading}</h3>
                {live.map((episode) => (
                  <EpisodeCard key={episode.id} copy={copy} lang={lang} series={series} episode={episode} canEdit={canEdit} run={run} act={act} busy={busy} />
                ))}
                {setAside.length > 0 && (
                  <p className='text-muted-foreground text-xs'>{copy.state.skipped}: {setAside.map((episode) => `${episode.index}. ${copy.role[episode.role]}`).join(', ')}</p>
                )}
              </section>
              <section aria-labelledby='series-facts' className='flex flex-col gap-2'>
                <h3 id='series-facts' className={HEADING}>{copy.factsHeading}</h3>
                <ul className='flex flex-col gap-1.5'>
                  {series.claims.map((claim) => <ClaimRow key={claim.id} copy={copy} series={series} claim={claim} canEdit={canEdit} run={run} act={act} busy={busy} />)}
                </ul>
              </section>
              {series.decisions.length > 0 && (
                <section aria-labelledby='series-decisions' className='flex flex-col gap-2'>
                  <h3 id='series-decisions' className={HEADING}>{copy.decisionsHeading}</h3>
                  <ul className='flex flex-col gap-1.5'>
                    {series.decisions.map((decision) => (
                      <li key={decision.id} className='rafii-quiet flex flex-wrap items-center gap-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm'>
                        <span className='min-w-0 flex-1'>
                          <span className='font-medium'>{copy.decision[decision.decision]}</span> · {copy.role[decision.role]}
                          {decision.angleText ? ` · ${decision.angleText}` : ''}
                          <span className='text-muted-foreground block text-xs'>
                            {decision.status !== 'active' ? copy.revoked : decision.storage === 'overlay' ? copy.storageMemory
                              : decision.reason === 'owner_required' ? copy.reasonOwner : decision.reason === 'overlays_disabled' ? copy.reasonOverlaysOff : copy.storageSeries}
                          </span>
                        </span>
                        {decision.canRevoke && (
                          <Button variant='quiet' size='lg' className='min-h-11' disabled={busy} onClick={() => act({ kind: 'revoke', id: series.id, revision: series.revision, decisionId: decision.id })}>
                            {copy.revoke}
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </RafiiDialogBody>
        {series && canEdit && (
          <RafiiDialogFooter className='flex-row flex-wrap items-center justify-end'>
            {(series.status === 'active' || series.status === 'paused') && (
              <span className='flex items-center gap-2'>
                <NativeSelect value={count} onChange={(event) => setCount(Number(event.target.value))} aria-label={copy.planMore}>
                  {[1, 2, 3, 4, 5, 6].map((value) => <NativeSelectOption key={value} value={value}>{value}</NativeSelectOption>)}
                </NativeSelect>
                <Button variant='glass' size='control' disabled={busy} onClick={() => act({ kind: 'plan', id: series.id, revision: series.revision, count })}>{copy.planMore}</Button>
              </span>
            )}
            {series.status === 'active' && <Button variant='quiet' size='control' disabled={busy} onClick={() => act({ kind: 'status', id: series.id, revision: series.revision, status: 'paused' })}>{copy.pause}</Button>}
            {series.status !== 'active' && <Button variant='quiet' size='control' disabled={busy} onClick={() => act({ kind: 'status', id: series.id, revision: series.revision, status: 'active' })}>{copy.resume}</Button>}
            {series.status !== 'completed' && series.status !== 'archived' && (
              <Button variant='quiet' size='control' disabled={busy} onClick={() => act({ kind: 'status', id: series.id, revision: series.revision, status: 'completed' })}>{copy.complete}</Button>
            )}
            {series.status !== 'archived' && <Button variant='quiet' size='control' disabled={busy} onClick={() => act({ kind: 'status', id: series.id, revision: series.revision, status: 'archived' })}>{copy.archive}</Button>}
          </RafiiDialogFooter>
        )}
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
