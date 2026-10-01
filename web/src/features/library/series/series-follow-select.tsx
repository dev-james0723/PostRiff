'use client';

import { useId } from 'react';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { seriesOff, useSeriesList } from '@/lib/growth-v2/series-hooks';
import { useSeriesCopy } from './use-series-copy';

/**
 * The Evergreen option's series choice (`include.evergreen.seriesId`): with a series chosen, each run drafts that
 * series' approved episode once; without one, Evergreen refreshes an older post exactly as before. Renders nothing when
 * the feature is off or the workspace has no active series (and none is chosen).
 */
export function SeriesFollowSelect({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const copy = useSeriesCopy();
  const id = useId();
  const list = useSeriesList(false);
  if (seriesOff(list) || !list.data) return null;
  const items = list.data.pages.flatMap((page) => page.items).filter((item) => item.status === 'active' || item.id === value);
  if (!items.length && !value) return null;
  return (
    <div className='flex flex-col gap-1 pl-7'>
      <label htmlFor={id} className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
        {copy.follow}
        <NativeSelect id={id} value={value ?? ''} onChange={(event) => onChange(event.target.value || null)}>
          <NativeSelectOption value=''>{copy.followNone}</NativeSelectOption>
          {items.map((item) => <NativeSelectOption key={item.id} value={item.id}>{item.title}</NativeSelectOption>)}
        </NativeSelect>
      </label>
      {value && <p className='text-muted-foreground text-xs'>{copy.followNote}</p>}
    </div>
  );
}
