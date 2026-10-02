'use client';

import { useEffect, useId, useMemo, useRef, useState, type ChangeEvent } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useGrowthFeatureState } from '@/lib/growth-v2/features';
import { errorCode, errorMessage, isFeatureDisabled } from '@/lib/growth-v2/request';
import { wasStopped } from '@/lib/growth-v2/source-uploads';
import {
  useAcceptQuote,
  useCreateSourceFromUpload,
  useSaveUploadText,
  useSelectPages,
  useSourceUpload,
  useSourceUploadLimits,
  useSourceUploadQuote,
  useSourceUploads,
  useSourceUploadText,
  useStartSourceUpload,
  useUploadAction
} from '@/lib/growth-v2/source-uploads-hooks';
import {
  classifyFile,
  copyFor,
  errorText,
  formatCount,
  formatCredits,
  formatDuration,
  formatMegabytes,
  languageFor,
  pageRangeProblem,
  panelMode,
  pickerFor,
  presentState,
  tooLong,
  type Lang,
  type Tone
} from '@/lib/growth-v2/source-uploads-model';
import type { JobView, LimitsView, UploadView } from '@/lib/growth-v2/source-uploads-types';
import { usePreferences } from '@/lib/preferences';
import { cn } from '@/lib/utils';

type Copy = ReturnType<typeof copyFor>;

const TONE: Record<Tone, string> = {
  progress: 'text-muted-foreground',
  attention: 'text-foreground font-medium',
  done: 'text-foreground font-medium',
  error: 'text-destructive',
  muted: 'text-muted-foreground'
};

interface SourceUploadPanelProps {
  canEdit: boolean;
  /** Opens a source the upload just created in the inspector. */
  onSourceCreated: (sourceId: string) => void;
}

/** The browser's own reading of a recording's length (the server measures again and decides). */
function measureAudio(file: File): Promise<number | undefined> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const audio = document.createElement('audio');
    let settled = false;
    const finish = (value?: number) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      URL.revokeObjectURL(url);
      resolve(value);
    };
    const timer = window.setTimeout(() => finish(undefined), 5000);
    audio.preload = 'metadata';
    audio.addEventListener('loadedmetadata', () => finish(Number.isFinite(audio.duration) ? audio.duration : undefined), { once: true });
    audio.addEventListener('error', () => finish(undefined), { once: true });
    audio.src = url;
  });
}

function failure(error: unknown, lang: Lang): string {
  return errorText(errorCode(error), errorMessage(error), lang);
}

/** True while the person is still in `root` (or nowhere in particular): only then may something there take focus. */
function focusIsWithin(root: Element | null | undefined): boolean {
  const active = typeof document === 'undefined' ? null : document.activeElement;
  return !active || active === document.body || Boolean(root?.contains(active));
}

/**
 * Raw-file intake inside Ideas (PRD R-FWR-04): limits are shown before a file is chosen, the file goes straight to
 * private storage, and its text is read (or, with an accepted quote, transcribed), reviewed and corrected before it
 * becomes a source. Every state shown is the server's; nothing is published. With the feature off (D-012: admission
 * of new work stops) earlier uploads stay listed, readable, cancellable and deletable, and no switched-off route is
 * asked; with none, nothing renders. Only formats this deployment can read are offered.
 */
export function SourceUploadPanel({ canEdit, onSourceCreated }: SourceUploadPanelProps) {
  const { locale } = usePreferences();
  const lang = languageFor(locale);
  const copy = copyFor(locale);
  const feature = useGrowthFeatureState('sourceUploads');
  const limits = useSourceUploadLimits(feature === 'on');
  const list = useSourceUploads();
  const start = useStartSourceUpload();
  const [activeId, setActiveId] = useState<string | null>(null);
  // Whether opening the detail may move focus: always when the person opened it, after an upload only if they are
  // still in this panel (an upload finishing never pulls focus from what they moved on to).
  const [takeFocus, setTakeFocus] = useState(true);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [progress, setProgress] = useState<{ fraction: number; stage: 'uploading' | 'checking' | 'reading' } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const chooseButton = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const rows = useRef(new Map<string, HTMLButtonElement>());
  const headingId = useId();
  const items = list.data?.items ?? [];
  // A deployment whose limits route is off although the features list said on: treat it as off (manage only).
  const mode = panelMode(feature === 'on' && isFeatureDisabled(limits.error) ? 'off' : feature, canEdit, items.length);

  if (mode === 'hidden') return null;
  const view = limits.data;
  const picker = pickerFor(view, lang);
  const uploading = mode === 'full';
  const stageLabel = !progress ? '' : progress.stage === 'uploading' ? copy.uploading(Math.round(progress.fraction * 100)) : progress.stage === 'checking' ? copy.checking : copy.reading;

  /** Closing the detail returns focus to the upload's row (or, if it is gone, to the panel). */
  function closeDetail() {
    const id = activeId;
    setActiveId(null);
    const target = (id && rows.current.get(id)) || chooseButton.current || heading.current;
    target?.focus();
  }

  async function choose(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !view) return;
    setProblem(null);
    setNotice(null);
    const choice = classifyFile(file, view, lang);
    if (!choice.ok) {
      setProblem(choice.message);
      return;
    }
    let durationSeconds: number | undefined;
    if (choice.kind === 'audio') {
      durationSeconds = await measureAudio(file);
      if (durationSeconds !== undefined && durationSeconds > view.limits.audio.maxSeconds) {
        setProblem(tooLong(durationSeconds, view.limits.audio.maxSeconds, lang));
        return;
      }
    }
    const controller = new AbortController();
    abort.current = controller;
    setProgress({ fraction: 0, stage: 'uploading' });
    start.mutate(
      {
        file,
        choice: choice.kind === 'transcript' ? { kind: 'transcript', format: choice.format } : { kind: choice.kind, mime: choice.mime },
        durationSeconds: durationSeconds === undefined ? undefined : Math.round(durationSeconds * 10) / 10,
        signal: controller.signal,
        onProgress: (fraction) => setProgress((current) => ({ fraction, stage: current?.stage ?? 'uploading' })),
        onStage: (stage) => setProgress((current) => ({ fraction: current?.fraction ?? 0, stage }))
      },
      {
        onSuccess: (uploaded) => {
          setTakeFocus(focusIsWithin(heading.current?.closest('section')));
          setActiveId(uploaded.id);
        },
        onError: (error) => {
          if (wasStopped(error, controller.signal)) setNotice(copy.stopped);
          else setProblem(failure(error, lang));
        },
        onSettled: () => {
          setProgress(null);
          abort.current = null;
        }
      }
    );
  }

  return (
    <Surface as='section' lang={lang} material='quiet' radius='card' padding='none' aria-labelledby={headingId} className='flex flex-col gap-4 p-4 sm:p-5'>
      <div className='flex flex-col gap-1'>
        <h2 id={headingId} ref={heading} tabIndex={-1} className='text-foreground text-base font-medium outline-none'>
          {mode === 'manage' ? copy.titleManage : picker.title}
        </h2>
        <p className='text-muted-foreground text-sm text-pretty'>{mode === 'manage' ? copy.offNote : copy.intro}</p>
      </div>

      {feature === 'on' &&
        (limits.isLoading ? (
          <StateMessage kind='loading' layout='inline' title={copy.loadingLimits} />
        ) : view ? (
          <Limits view={view} copy={copy} lang={lang} />
        ) : limits.error && !isFeatureDisabled(limits.error) ? (
          <StateMessage kind='error' layout='inline' title={failure(limits.error, lang)} />
        ) : null)}

      {view && uploading && (
        <div className='flex flex-col gap-2'>
          {/* The button is the one control; the native picker stays out of the tab order. */}
          <input ref={input} type='file' accept={picker.accept} className='sr-only' tabIndex={-1} aria-hidden onChange={(event) => void choose(event)} disabled={Boolean(progress)} />
          <Button
            ref={chooseButton}
            variant='glass'
            size='control'
            className='w-full sm:w-fit'
            disabled={Boolean(progress)}
            onClick={() => input.current?.click()}
            aria-describedby={`${headingId}-hint`}
          >
            <Icons.upload aria-hidden className='size-4' />
            {copy.choose}
          </Button>
          <p id={`${headingId}-hint`} className='text-muted-foreground text-xs'>
            {picker.hint}
          </p>
        </div>
      )}

      {progress && (
        <div className='flex flex-col gap-2' role='status' aria-live='polite'>
          <span className='text-sm'>{stageLabel}</span>
          <div role='progressbar' aria-label={stageLabel} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress.fraction * 100)} className='bg-muted h-1.5 w-full overflow-hidden rounded-full'>
            <div className='bg-primary h-full transition-[width] motion-reduce:transition-none' style={{ width: `${Math.round(progress.fraction * 100)}%` }} />
          </div>
          {progress.stage === 'uploading' && (
            <Button variant='quiet' size='sm' className='w-fit' onClick={() => abort.current?.abort()}>
              {copy.cancelUpload}
            </Button>
          )}
        </div>
      )}

      {problem && <StateMessage kind='error' layout='inline' title={problem} />}
      {notice && !problem && (
        <p role='status' className='text-muted-foreground text-sm'>
          {notice}
        </p>
      )}

      {activeId && (
        <UploadDetail
          key={activeId}
          id={activeId}
          lang={lang}
          copy={copy}
          canEdit={canEdit}
          canStartWork={uploading}
          takeFocus={takeFocus}
          onSourceCreated={onSourceCreated}
          onClose={closeDetail}
        />
      )}

      {items.length > 0 && (
        <div className='flex flex-col gap-2'>
          <h3 className='text-muted-foreground text-xs font-medium tracking-wide uppercase'>{copy.recent}</h3>
          <ul className='flex flex-col gap-1'>
            {items.map((item) => (
              <li key={item.id}>
                <UploadRow
                  item={item}
                  lang={lang}
                  copy={copy}
                  selected={item.id === activeId}
                  onOpen={() => {
                    setTakeFocus(true);
                    setActiveId(item.id);
                  }}
                  register={(node) => {
                    if (node) rows.current.set(item.id, node);
                    else rows.current.delete(item.id);
                  }}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </Surface>
  );
}

function Limits({ view, copy, lang }: { view: LimitsView; copy: Copy; lang: Lang }) {
  const audio = view.formats.audio;
  return (
    <ul className='text-muted-foreground flex flex-col gap-1 text-sm' aria-label={copy.limitsLabel}>
      <li>{view.formats.pdf.supported ? copy.limitsPdf(formatMegabytes(view.limits.pdf.maxBytes), view.limits.pdf.maxPages, formatCount(view.limits.pdf.maxCharacters, lang)) : copy.pdfOff}</li>
      <li>{audio.supported ? copy.limitsAudio(formatMegabytes(view.limits.audio.maxBytes), Math.floor(view.limits.audio.maxSeconds / 60)) : copy.audioOff}</li>
      {audio.supported && audio.synthetic && <li className='text-foreground'>{copy.audioSynthetic}</li>}
      <li>{copy.transcriptHint}</li>
    </ul>
  );
}

function UploadRow({ item, lang, copy, selected, onOpen, register }: { item: UploadView; lang: Lang; copy: Copy; selected: boolean; onOpen: () => void; register: (node: HTMLButtonElement | null) => void }) {
  const said = presentState(item, lang);
  const Mark = item.kind === 'pdf' ? Icons.fileTypePdf : item.kind === 'audio' ? Icons.music : Icons.text;
  return (
    <button
      ref={register}
      type='button'
      onClick={onOpen}
      aria-pressed={selected}
      className={cn('rafii-focus flex min-h-12 w-full items-center gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-left', selected ? 'rafii-glass-selected' : 'hover:rafii-quiet')}
    >
      <Mark aria-hidden className='text-muted-foreground size-4 shrink-0' />
      <span className='flex min-w-0 flex-1 flex-col'>
        <span className='truncate text-sm'>{item.name ?? copy.deletedUpload}</span>
        <span className={cn('text-xs', TONE[said.tone])}>{said.label}</span>
      </span>
    </button>
  );
}

interface DetailProps {
  id: string;
  lang: Lang;
  copy: Copy;
  canEdit: boolean;
  /** Whether steps that start or change work (quote, pages, corrections, "use as source", process) are available:
   *  false while the feature is off, when only reading, cancelling and deleting remain. */
  canStartWork: boolean;
  /** Move focus to the detail when it opens (the person's own action), not when it merely appears. */
  takeFocus: boolean;
  onSourceCreated: (sourceId: string) => void;
  onClose: () => void;
}

function UploadDetail({ id, lang, copy, canEdit, canStartWork, takeFocus, onSourceCreated, onClose }: DetailProps) {
  const status = useSourceUpload(id);
  const action = useUploadAction();
  const [problem, setProblem] = useState<string | null>(null);
  const [opened] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  const heading = useRef<HTMLHeadingElement>(null);
  const focused = useRef(false);
  const titleId = useId();
  const view = status.data;
  const said = view ? presentState(view, lang) : null;
  const waiting = Boolean(view?.job && ['queued', 'running'].includes(view.job.state));
  // Status polling stops after three minutes; this local clock (no requests) is what shows the "still working" note.
  const stalled = waiting && now - opened > 180_000;
  const ready = Boolean(view);

  // Focus moves here once, when the person opens the detail (or their upload finishes); later step changes from polling
  // are announced by the status line, never by moving focus away from what the person is doing.
  useEffect(() => {
    if (!ready || focused.current) return;
    focused.current = true;
    if (takeFocus) heading.current?.focus();
  }, [ready, takeFocus]);

  useEffect(() => {
    if (!waiting) return;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [waiting]);

  const run = (kind: 'cancel' | 'process' | 'delete') => {
    setProblem(null);
    action.mutate(
      { id, action: kind },
      {
        // The button just pressed disappears with the new state: keep focus in the detail, on its title.
        onSuccess: () => heading.current?.focus(),
        onError: (error) => setProblem(failure(error, lang))
      }
    );
  };

  if (status.isLoading) return <StateMessage kind='loading' layout='inline' title={copy.checking} />;
  if (!view) return status.error ? <StateMessage kind='error' layout='inline' title={failure(status.error, lang)} /> : null;
  const working = canEdit && canStartWork;

  return (
    <Surface as='section' material='glass' radius='card' padding='none' aria-labelledby={titleId} className='flex flex-col gap-3 p-4'>
      <div className='flex items-start justify-between gap-3'>
        <div className='flex min-w-0 flex-col gap-1'>
          <h3 id={titleId} ref={heading} tabIndex={-1} className='truncate text-sm font-medium outline-none'>
            {view.name ?? copy.deletedUpload}
          </h3>
          <p className={cn('text-sm', said ? TONE[said.tone] : '')} role={said?.tone === 'error' ? 'alert' : 'status'}>
            {waiting && <Icons.spinner aria-hidden className='mr-1 inline size-3.5 animate-spin motion-reduce:animate-none' />}
            {said?.label}
            {view.durationSeconds ? ` · ${formatDuration(view.durationSeconds)}` : ''}
          </p>
          {said?.detail && <p className='text-muted-foreground text-sm text-pretty'>{said.detail}</p>}
        </div>
        <Button variant='quiet' size='icon-control' aria-label={copy.close} onClick={onClose}>
          <Icons.close className='size-4' />
        </Button>
      </div>

      {stalled && (
        <StateMessage kind='stale' layout='inline' title={copy.stillWorking} action={<Button variant='quiet' size='sm' onClick={() => void status.refetch()}>{copy.refresh}</Button>} />
      )}

      {working && view.next === 'accept_quote' && <QuoteCard id={id} copy={copy} lang={lang} />}
      {working && view.next === 'select_pages' && <PagesForm view={view} copy={copy} lang={lang} />}
      {(view.next === 'review' || view.next === 'done') && (
        <ReviewEditor id={id} view={view} copy={copy} lang={lang} canEdit={working && view.next === 'review'} onSourceCreated={onSourceCreated} />
      )}
      {view.next === 'upload_transcript' && <StateMessage kind='unsupported' layout='inline' title={copy.audioOff} />}

      {problem && <StateMessage kind='error' layout='inline' title={problem} />}

      {canEdit && (
        <div className='flex flex-wrap gap-2'>
          {view.job?.cancellable && view.next !== 'done' && (
            <Button variant='quiet' size='sm' disabled={action.isPending} onClick={() => run('cancel')}>
              {copy.cancel}
            </Button>
          )}
          {working && view.job?.state === 'queued' && (
            <Button variant='quiet' size='sm' disabled={action.isPending} onClick={() => run('process')}>
              {copy.refresh}
            </Button>
          )}
          {view.state !== 'deleted' && !view.job?.cancellable && (
            <Button variant='quiet' size='sm' disabled={action.isPending} onClick={() => run('delete')}>
              {copy.remove}
            </Button>
          )}
        </div>
      )}
    </Surface>
  );
}

function QuoteCard({ id, copy, lang }: { id: string; copy: Copy; lang: Lang }) {
  const quote = useSourceUploadQuote(id, true);
  const accept = useAcceptQuote();
  const [problem, setProblem] = useState<string | null>(null);
  const data = quote.data;
  if (quote.isLoading) return <StateMessage kind='loading' layout='inline' title={copy.quoteTitle} />;
  if (!data) return quote.error ? <StateMessage kind='error' layout='inline' title={failure(quote.error, lang)} /> : null;
  if (!data.allowed) {
    return (
      <StateMessage
        kind='unsupported'
        layout='inline'
        title={errorText(data.reason, data.message ?? copy.audioOff, lang)}
        description={copy.transcriptHint}
        action={data.upgradePath ? <Link href={data.upgradePath} className='rafii-focus text-sm font-medium underline underline-offset-4'>{copy.upgrade}</Link> : undefined}
      />
    );
  }
  const ceiling = data.ceilingMilliCredits ?? 0;
  return (
    <div className='flex flex-col gap-2'>
      <h4 className='text-sm font-medium'>{copy.quoteTitle}</h4>
      <p className='text-sm text-pretty'>{copy.quoteBody(formatDuration(data.seconds), formatCredits(data.estimateMilliCredits), formatCredits(ceiling))}</p>
      <p className='text-muted-foreground text-sm'>{data.enough ? copy.quoteAvailable(formatCredits(data.availableMilliCredits)) : copy.quoteNotEnough}</p>
      {data.synthetic && <p className='text-muted-foreground text-xs'>{copy.audioSynthetic}</p>}
      {problem && <StateMessage kind='error' layout='inline' title={problem} />}
      <Button
        variant='action'
        size='control'
        className='w-full sm:w-fit'
        disabled={!data.enough || accept.isPending}
        onClick={() => {
          setProblem(null);
          accept.mutate({ id, maxMilliCredits: ceiling }, { onError: (error) => setProblem(failure(error, lang)) });
        }}
      >
        {copy.transcribe}
      </Button>
    </div>
  );
}

function PagesForm({ view, copy, lang }: { view: UploadView; copy: Copy; lang: Lang }) {
  const select = useSelectPages();
  const progress: JobView['progress'] = view.job?.progress ?? {};
  const total = progress.pageCount ?? 1;
  const maxPages = progress.maxPages ?? 100;
  const maxChars = progress.maxChars ?? 60_000;
  // Suggest the longest run from page 1 that fits both limits, from the per-page counts the server measured.
  const suggested = useMemo(() => {
    let sum = 0;
    let last = 0;
    for (const page of progress.pages ?? []) {
      if (sum + page.chars > maxChars || page.page > maxPages) break;
      sum += page.chars + 2;
      last = page.page;
    }
    return Math.max(1, Math.min(last || maxPages, total));
  }, [progress.pages, maxChars, maxPages, total]);
  const [from, setFrom] = useState(1);
  const [to, setTo] = useState(suggested);
  const [problem, setProblem] = useState<string | null>(null);
  const fromId = useId();
  const toId = useId();
  const rangeId = useId();
  // Said in place, before anything is sent: which limit the range breaks and how to fix it.
  const invalid = pageRangeProblem({ from, to }, { total, maxPages, maxChars, pages: progress.pages }, lang);
  return (
    <form
      className='flex flex-col gap-3'
      onSubmit={(event) => {
        event.preventDefault();
        if (invalid) return;
        setProblem(null);
        select.mutate({ id: view.id, from, to }, { onError: (error) => setProblem(failure(error, lang)) });
      }}
    >
      <h4 className='text-sm font-medium'>{copy.pagesTitle}</h4>
      <p className='text-sm text-pretty'>
        {progress.totalChars ? copy.pagesBody(formatCount(progress.totalChars, lang), formatCount(maxChars, lang), total) : copy.pagesTooMany(total, maxPages)}
      </p>
      <div className='grid grid-cols-2 gap-3 sm:max-w-sm'>
        <div className='flex flex-col gap-1'>
          <Label htmlFor={fromId}>{copy.from}</Label>
          <Input
            id={fromId}
            type='number'
            inputMode='numeric'
            min={1}
            max={total}
            value={from}
            onChange={(event) => setFrom(Number(event.target.value))}
            aria-invalid={Boolean(invalid)}
            aria-describedby={invalid ? rangeId : undefined}
          />
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor={toId}>{copy.to}</Label>
          <Input
            id={toId}
            type='number'
            inputMode='numeric'
            min={1}
            max={total}
            value={to}
            onChange={(event) => setTo(Number(event.target.value))}
            aria-invalid={Boolean(invalid)}
            aria-describedby={invalid ? rangeId : undefined}
          />
        </div>
      </div>
      {invalid && (
        <p id={rangeId} role='alert' className='text-destructive text-sm'>
          {invalid}
        </p>
      )}
      {problem && <StateMessage kind='error' layout='inline' title={problem} />}
      <Button type='submit' variant='action' size='control' className='w-full sm:w-fit' disabled={Boolean(invalid) || select.isPending}>
        {copy.readPages}
      </Button>
    </form>
  );
}

function ReviewEditor({ id, view, copy, lang, canEdit, onSourceCreated }: { id: string; view: UploadView; copy: Copy; lang: Lang; canEdit: boolean; onSourceCreated: (sourceId: string) => void }) {
  const text = useSourceUploadText(id, true);
  const save = useSaveUploadText();
  const create = useCreateSourceFromUpload();
  const [draft, setDraft] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const areaId = useId();
  const data = text.data;
  const sourceId = view.job?.sourceId ?? data?.sourceId ?? null;

  if (text.isLoading) return <StateMessage kind='loading' layout='inline' title={copy.checking} />;
  if (!data) return text.error ? <StateMessage kind='error' layout='inline' title={failure(text.error, lang)} /> : null;
  const value = draft ?? data.text;
  const changed = draft !== null && draft !== data.text;
  const over = value.length > data.maxCharacters;

  async function persist(): Promise<number | null> {
    if (!changed) return data!.revision;
    const saved = await save.mutateAsync({ id, expectedRevision: data!.revision, text: value });
    setDraft(null);
    return saved.revision;
  }

  return (
    <div className='flex flex-col gap-3'>
      <div className='flex flex-col gap-1'>
        <h4 className='text-sm font-medium'>{copy.reviewTitle}</h4>
        {canEdit && <p className='text-muted-foreground text-sm text-pretty'>{copy.reviewHelp}</p>}
      </div>
      <p id={`${areaId}-note`} className='text-muted-foreground flex items-start gap-2 text-xs'>
        <Icons.shieldCheck aria-hidden className='mt-0.5 size-3.5 shrink-0' />
        {copy.untrusted}
      </p>
      {data.synthetic && <StateMessage kind='partial' layout='inline' title={copy.synthetic} />}
      {data.injectionFlags.length > 0 && <StateMessage kind='partial' layout='inline' title={copy.injection(data.injectionFlags.length)} />}
      {data.emptyPages.length > 0 && <StateMessage kind='partial' layout='inline' title={copy.emptyPages(data.emptyPages.slice(0, 8).join(', '))} />}
      <Label htmlFor={areaId} className='sr-only'>
        {copy.reviewTitle}
      </Label>
      <Textarea
        id={areaId}
        value={value}
        readOnly={!canEdit}
        onChange={(event) => setDraft(event.target.value)}
        rows={12}
        dir='auto'
        aria-describedby={`${areaId}-note ${areaId}-count`}
        aria-invalid={over}
        className='rafii-field min-h-48 rounded-[var(--rafii-radius-control)] border-0 px-4 py-3 text-base leading-relaxed md:text-sm'
      />
      <p id={`${areaId}-count`} className={cn('text-xs tabular-nums', over ? 'text-destructive' : 'text-muted-foreground')}>
        {copy.characters(formatCount(value.length, lang), formatCount(data.maxCharacters, lang))}
        {' · '}
        {data.claimsPreview.capped ? copy.claimsCapped(data.claimsPreview.limit) : copy.claims(data.claimsPreview.count)}
      </p>
      {problem && <StateMessage kind='error' layout='inline' title={problem} />}
      {notice && !problem && <p role='status' className='text-muted-foreground text-sm'>{notice}</p>}
      {sourceId ? (
        <StateMessage
          kind='success'
          layout='inline'
          title={copy.sourceCreated}
          action={<Button variant='glass' size='sm' onClick={() => onSourceCreated(sourceId)}>{copy.openSource}</Button>}
        />
      ) : (
        canEdit && (
          <div className='flex flex-col gap-2 sm:flex-row'>
            <Button
              variant='glass'
              size='control'
              disabled={!changed || over || save.isPending || create.isPending}
              onClick={() => {
                setProblem(null);
                persist().then(() => setNotice(copy.saved), (error: unknown) => setProblem(failure(error, lang)));
              }}
            >
              {copy.save}
            </Button>
            <Button
              variant='action'
              size='control'
              disabled={over || save.isPending || create.isPending}
              onClick={() => {
                setProblem(null);
                persist()
                  .then((revision) => create.mutateAsync({ id, expectedRevision: revision ?? data.revision }))
                  .then((created) => onSourceCreated(created.sourceId), (error: unknown) => setProblem(failure(error, lang)));
              }}
            >
              {copy.useAsSource}
            </Button>
          </div>
        )
      )}
    </div>
  );
}
