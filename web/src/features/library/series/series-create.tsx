'use client';

import { useId, useState, type FormEvent } from 'react';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, SegmentedControl, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';
import { useSeriesCandidates, useSeriesChange, type SeriesChange } from '@/lib/growth-v2/series-hooks';
import type { CandidatePost, CandidateSource } from '@/lib/growth-v2/series-types';
import { cn } from '@/lib/utils';
import { fill, seriesErrorText } from './series-copy';
import { useSeriesCopy, useSeriesLang } from './use-series-copy';

const AGES = [30, 60, 90, 180, 365];
const COUNTS = [2, 3, 4, 5, 6];
const FIELD = 'rafii-field h-12 rounded-[var(--rafii-radius-control)] px-3.5 text-base md:h-11 md:text-sm';

/** Pick an eligible original (an old published post or a source with approved facts), ask the audience question and
 *  the goal, and plan 2–6 episodes. Planning is deterministic: nothing is written and no credit is used. Every opening
 *  starts empty (nothing from an earlier series carries over); the dialog stays open, with the error in place, until the
 *  server saved the series. */
export function SeriesCreateDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; onCreated: (id: string) => void }) {
  const copy = useSeriesCopy();
  const lang = useSeriesLang();
  const ids = useId();
  const [kind, setKind] = useState<'post' | 'source'>('post');
  const [minAge, setMinAge] = useState(30);
  const [origin, setOrigin] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [goal, setGoal] = useState('');
  const [title, setTitle] = useState('');
  const [count, setCount] = useState(3);
  const [intent, setIntent] = useState<SeriesChange | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) {
      setKind('post');
      setMinAge(30);
      setOrigin(null);
      setQuestion('');
      setGoal('');
      setTitle('');
      setCount(3);
      setIntent(null);
      setError(null);
    }
  }
  const candidates = useSeriesCandidates(kind, minAge, open);
  const change = useSeriesChange();
  const items = (candidates.data?.pages.flatMap((page) => page.items) ?? []) as (CandidatePost | CandidateSource)[];
  const ready = Boolean(origin && question.trim() && goal.trim()) && !change.isPending;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !origin) return;
    const next: SeriesChange = intent ?? {
      kind: 'create',
      input: { origin: { kind, id: origin }, audienceQuestion: question.trim(), goal: goal.trim(), episodeCount: count, ...(title.trim() ? { title: title.trim() } : {}), ...(kind === 'post' ? { minAgeDays: minAge } : {}) }
    };
    setIntent(next);   // a retry of this same submission reuses its idempotency key
    setError(null);
    change.mutate(next, {
      onSuccess: (data) => { setIntent(null); onCreated(data.series.id); },
      onError: (failure) => setError(seriesErrorText(copy, failure))
    });
  }

  function reset(next: Partial<{ kind: 'post' | 'source'; minAge: number }>) {
    if (next.kind) setKind(next.kind);
    if (next.minAge) setMinAge(next.minAge);
    setOrigin(null);
    setIntent(null);
    setError(null);
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='lg' lang={lang}>
        <form onSubmit={submit} className='flex min-h-0 flex-1 flex-col'>
          <RafiiDialogHeader title={copy.createTitle} intro={copy.createIntro} closeLabel={copy.cancel} />
          <RafiiDialogBody className='flex flex-col gap-4'>
            <SegmentedControl label={copy.createTitle} value={kind} onChange={(value) => reset({ kind: value })}
                              options={[{ value: 'post', label: copy.sourcePost }, { value: 'source', label: copy.sourceSource }]} />
            {kind === 'post' && (
              <label className='text-muted-foreground flex flex-wrap items-center gap-2 text-sm'>
                {copy.minAge}
                <NativeSelect value={minAge} onChange={(event) => reset({ minAge: Number(event.target.value) })} aria-label={`${copy.minAge} … ${copy.days}`}>
                  {AGES.map((age) => <NativeSelectOption key={age} value={age}>{age}</NativeSelectOption>)}
                </NativeSelect>
                {copy.days}
              </label>
            )}
            <fieldset className='flex flex-col gap-2'>
              <legend className='mb-1 text-sm font-medium'>{kind === 'post' ? copy.sourcePost : copy.sourceSource}</legend>
              {candidates.isError ? (
                <StateMessage kind='error' layout='inline' title={seriesErrorText(copy, candidates.error, copy.loadError)} />
              ) : candidates.isPending ? (
                <p className='text-muted-foreground text-sm' role='status'>…</p>
              ) : items.length === 0 ? (
                <StateMessage kind='empty' layout='inline' title={kind === 'post' ? copy.noPosts : copy.noSources} />
              ) : (
                <ul className='flex max-h-72 flex-col gap-1.5 overflow-y-auto'>
                  {items.map((item) => (
                    <li key={item.id}>
                      <label aria-label={item.excerpt} className={cn('rafii-glass rafii-focus flex min-h-12 cursor-pointer gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2.5', origin === item.id && 'rafii-glass-selected')}>
                        <input type='radio' name={`${ids}-origin`} aria-label={item.excerpt} value={item.id} checked={origin === item.id} onChange={() => { setOrigin(item.id); setIntent(null); }} className='mt-1' />
                        <span className='flex min-w-0 flex-col gap-0.5 text-sm'>
                          <span className='line-clamp-2'>{item.excerpt}</span>
                          <span className='text-muted-foreground text-xs'>
                            {item.kind === 'post'
                              ? [item.platform, item.publishedAt, item.priorUse.length ? fill(copy.priorUse, { n: item.priorUse.length }) : null,
                                 item.observed ? fill(copy.observed, { value: item.observed.value, metric: item.observed.metric, typical: item.observed.typical, n: item.observed.sampleSize }) : null]
                                  .filter(Boolean).join(' · ')
                              : `${item.title} · ${fill(copy.approvedFacts, { n: item.approvedFacts })}`}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {candidates.hasNextPage && (
                <Button type='button' variant='quiet' size='lg' className='min-h-11 self-start' disabled={candidates.isFetchingNextPage} onClick={() => void candidates.fetchNextPage()}>
                  {copy.showMore}
                </Button>
              )}
            </fieldset>
            <label className='flex flex-col gap-1.5 text-sm font-medium' htmlFor={`${ids}-question`}>
              {copy.audienceQuestion}
              <Input id={`${ids}-question`} required maxLength={300} value={question} placeholder={copy.audienceQuestionHint}
                     onChange={(event) => { setQuestion(event.target.value); setIntent(null); }} className={FIELD} />
            </label>
            <label className='flex flex-col gap-1.5 text-sm font-medium' htmlFor={`${ids}-goal`}>
              {copy.goal}
              <Textarea id={`${ids}-goal`} required maxLength={600} rows={2} value={goal} onChange={(event) => { setGoal(event.target.value); setIntent(null); }} className='rafii-field text-base md:text-sm' />
            </label>
            <div className='flex flex-wrap gap-4'>
              <label className='flex min-w-0 flex-[1_1_14rem] flex-col gap-1.5 text-sm font-medium' htmlFor={`${ids}-title`}>
                {copy.title}
                <Input id={`${ids}-title`} maxLength={120} value={title} onChange={(event) => { setTitle(event.target.value); setIntent(null); }} className={FIELD} />
              </label>
              <label className='flex flex-col gap-1.5 text-sm font-medium' htmlFor={`${ids}-count`}>
                {copy.episodeCount}
                <NativeSelect id={`${ids}-count`} value={count} onChange={(event) => { setCount(Number(event.target.value)); setIntent(null); }}>
                  {COUNTS.map((value) => <NativeSelectOption key={value} value={value}>{value}</NativeSelectOption>)}
                </NativeSelect>
              </label>
            </div>
            {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
          </RafiiDialogBody>
          <RafiiDialogFooter className='flex-row justify-end'>
            <Button type='button' variant='quiet' size='control' onClick={() => onOpenChange(false)}>{copy.cancel}</Button>
            <Button type='submit' variant='action' size='control' disabled={!ready}>{copy.create}</Button>
          </RafiiDialogFooter>
        </form>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
