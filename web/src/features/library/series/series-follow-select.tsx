'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { useGrowthFeatures } from '@/lib/growth-v2/features';
import { seriesOff, useSeries, useSeriesList } from '@/lib/growth-v2/series-hooks';
import { fill, followState, type SeriesCopy, type SeriesLocale } from './series-copy';
import { useSeriesCopy, useSeriesLang } from './use-series-copy';

/**
 * The Evergreen option's series choice (`include.evergreen.seriesId`): with a series chosen, each run drafts that
 * series' approved episode once; without one, Evergreen refreshes an older post exactly as before.
 *
 * The server refuses to save an automation that follows an archived or missing series, so a follow saved earlier is
 * never hidden: its state is said in words and "Stop following" clears it. With Signature Series switched off the server
 * keeps a follow saved earlier (the automation still saves; no episodes are drafted meanwhile), so that is said as a
 * note, not an error, with the same way out (then no series request is made at all). With nothing chosen and nothing to
 * choose, it renders nothing.
 */
export function SeriesFollowSelect({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const copy = useSeriesCopy();
  const lang = useSeriesLang();
  const features = useGrowthFeatures();
  const [cleared, setCleared] = useState(false);
  const clear = () => {
    setCleared(true);
    onChange(null);
  };
  const choose = (next: string | null) => {
    setCleared(false);
    onChange(next);
  };
  if (features.isPending) return null;
  if (features.data?.series !== true) {
    if (value) return <FollowProblem copy={copy} lang={lang} text={copy.followOff} onClear={clear} tone='note' />;
    return cleared ? <FollowCleared copy={copy} lang={lang} /> : null;
  }
  return <FollowChooser copy={copy} lang={lang} value={value} onChange={choose} onClear={clear} cleared={cleared} />;
}

function FollowChooser({ copy, lang, value, onChange, onClear, cleared }: {
  copy: SeriesCopy; lang: SeriesLocale; value: string | null; onChange: (id: string | null) => void; onClear: () => void; cleared: boolean;
}) {
  const id = useId();
  const selectRef = useRef<HTMLSelectElement>(null);
  const list = useSeriesList(false);
  const items = list.data?.pages.flatMap((page) => page.items) ?? [];
  const listed = value ? items.find((item) => item.id === value) : undefined;
  // Archived (or older) series are not on the list: read the followed one on its own to say where it stands.
  const detail = useSeries(value && list.data && !listed ? value : null);
  const state = followState(value, listed?.status, { status: detail.data?.series.status, error: detail.error });
  const options = items.filter((item) => item.status === 'active');
  const visible = Boolean(list.data) && (options.length > 0 || Boolean(value));

  useEffect(() => {
    // After "Stop following" the select is the next thing to use.
    if (cleared && !value) selectRef.current?.focus();
  }, [cleared, value]);

  if (seriesOff(list)) {
    if (value) return <FollowProblem copy={copy} lang={lang} text={copy.followOff} onClear={onClear} tone='note' />;
    return cleared ? <FollowCleared copy={copy} lang={lang} /> : null;
  }
  if (list.isError) return value ? <FollowProblem copy={copy} lang={lang} text={copy.followUnknown} onClear={onClear} /> : null;
  if (!visible) return cleared ? <FollowCleared copy={copy} lang={lang} /> : null;

  const title = listed?.title ?? detail.data?.series.title ?? null;
  const status = listed?.status ?? detail.data?.series.status ?? null;
  const currentLabel = !title ? (state === 'checking' ? '…' : copy.unavailableSeries)
    : status === 'archived' ? fill(copy.archivedTitle, { title })
    : status && status !== 'active' ? `${title} · ${copy.status[status]}` : title;
  // Switched off is not a problem to fix: the follow is kept and the automation still saves (said, with the way out).
  const problem = state === 'archived' ? copy.followArchived : state === 'missing' ? copy.followMissing : state === 'unknown' ? copy.followUnknown : null;
  const note = state === 'off' ? copy.followOff : null;
  return (
    <div lang={lang} className='flex flex-col gap-1 pl-7'>
      <label htmlFor={id} className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
        {copy.follow}
        <NativeSelect ref={selectRef} id={id} value={value ?? ''} aria-describedby={problem || note ? `${id}-problem` : undefined} aria-invalid={problem ? true : undefined}
                      onChange={(event) => onChange(event.target.value || null)}>
          <NativeSelectOption value=''>{copy.followNone}</NativeSelectOption>
          {value && !options.some((item) => item.id === value) && <NativeSelectOption value={value}>{currentLabel}</NativeSelectOption>}
          {options.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.title}</NativeSelectOption>)}
        </NativeSelect>
      </label>
      {state === 'checking' && <p role='status' className='text-muted-foreground text-xs'>{copy.followChecking}</p>}
      {problem || note ? (
        <div className='flex flex-col gap-1.5'>
          <p id={`${id}-problem`} className={problem ? 'text-destructive text-xs' : 'text-muted-foreground text-xs'}>{problem ?? note}</p>
          <Button type='button' variant='quiet' size='lg' className='min-h-11 self-start' onClick={onClear}>{copy.stopFollowing}</Button>
        </div>
      ) : (
        value && state === 'ok' && <p className='text-muted-foreground text-xs'>{copy.followNote}</p>
      )}
    </div>
  );
}

/** A follow that can't be read or used (or, as a `note`, is kept while Series is off): said in words, with the way out. */
function FollowProblem({ copy, lang, text, onClear, tone = 'problem' }: { copy: SeriesCopy; lang: SeriesLocale; text: string; onClear: () => void; tone?: 'problem' | 'note' }) {
  return (
    <div lang={lang} className='flex flex-col gap-1.5 pl-7'>
      <p className={tone === 'note' ? 'text-muted-foreground text-xs' : 'text-destructive text-xs'}>{text}</p>
      <Button type='button' variant='quiet' size='lg' className='min-h-11 self-start' onClick={onClear}>{copy.stopFollowing}</Button>
    </div>
  );
}

/** Confirms "Stop following" where nothing else is left to show, and keeps keyboard focus on the page. */
function FollowCleared({ copy, lang }: { copy: SeriesCopy; lang: SeriesLocale }) {
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return <p ref={ref} lang={lang} tabIndex={-1} role='status' className='text-muted-foreground pl-7 text-xs outline-none'>{copy.followCleared}</p>;
}
