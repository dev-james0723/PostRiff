'use client';

import { ChannelIcon } from '@/components/channel-icon';
import { formatLabel, mediaNote, type NativeFormat } from '@/lib/creation/capabilities';

export interface NativeFormatRow {
  /** `selectionKey`: the account id, else the platform. */
  key: string;
  platform: string;
  account?: string;
  formats: NativeFormat[];
  defaultFormat: string | null;
}

/**
 * One native format per selected destination (a Facebook Page post or a Reel, an Instagram carousel or a Story). Only
 * platforms with more than one format get a row. The note beside a format says what it still needs (an image, a video);
 * choosing a format never means the media exists or that the draft can be published.
 */
export function NativeFormatPicker({ rows, value, onChange, disabled }: { rows: NativeFormatRow[]; value: Record<string, string>; onChange: (key: string, format: string) => void; disabled?: boolean }) {
  const shown = rows.filter((row) => row.formats.length > 1);
  if (!shown.length) return null;
  return (
    <fieldset className='mx-3 mb-1.5 flex min-w-0 flex-col gap-1' disabled={disabled}>
      <legend className='sr-only'>Post format for each destination</legend>
      {shown.map((row) => {
        const selected = value[row.key] ?? row.defaultFormat ?? row.formats[0].id;
        const format = row.formats.find((f) => f.id === selected) ?? row.formats[0];
        const note = mediaNote(format);
        const id = `native-format-${row.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
        return (
          <div key={row.key} className='flex min-h-10 min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-sm' data-native-format={row.platform}>
            <ChannelIcon platform={row.platform} size='sm' />
            <label htmlFor={id} className='text-muted-foreground min-w-0 truncate'>
              {row.account ? `${row.platform} · ${row.account}` : row.platform}
            </label>
            <select
              id={id}
              value={format.id}
              onChange={(event) => onChange(row.key, event.target.value)}
              className='rafii-focus border-border/70 bg-background text-foreground h-9 min-w-0 rounded-[var(--rafii-radius-control)] border px-2 text-sm'
            >
              {row.formats.map((f) => (
                <option key={f.id} value={f.id}>
                  {formatLabel(row.platform, f.id)}
                </option>
              ))}
            </select>
            {note && <span className='text-muted-foreground w-full pl-8 text-xs sm:w-auto sm:pl-0'>{note}</span>}
          </div>
        );
      })}
    </fieldset>
  );
}
