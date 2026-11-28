'use client';

import { Surface } from '@/components/rafii/surface';

interface TimelineClip {
  id: string;
  label: string;
  durationMs: number;
}

function timecode(milliseconds: number) {
  const ms = Math.round(milliseconds);
  const seconds = String(Math.floor(ms / 1000) % 60).padStart(2, '0');
  const fraction = String(ms % 1000).padStart(3, '0').replace(/0+$/, '');
  return `${Math.floor(ms / 60000)}:${seconds}${fraction ? `.${fraction}` : ''}`;
}

export function CutTimeline({ clips, selectedId, onSelect, positionMs, disabled }: {
  clips: TimelineClip[];
  selectedId?: string;
  onSelect: (id: string) => void;
  positionMs?: number;
  disabled?: boolean;
}) {
  let endMs = 0;
  const segments = clips.map(clip => {
    const startMs = endMs;
    endMs += clip.durationMs;
    return { ...clip, startMs, endMs };
  });
  if (!endMs) return null;
  const selected = segments.find(clip => clip.id === selectedId);
  const position = positionMs ?? selected?.startMs;
  const playhead = position == null ? undefined : Math.min(endMs, Math.max(0, position));

  return <Surface as='section' material='quiet' aria-label='Cut timeline' className='grid gap-3'>
    <div className='flex flex-wrap items-baseline justify-between gap-2'>
      <h2 className='text-lg font-medium'>Cut timeline</h2>
      <span className='font-mono text-xs tabular-nums'>{playhead == null ? '—' : timecode(playhead)} / {timecode(endMs)}</span>
    </div>
    <div className='overflow-x-auto p-1'>
      <div className='relative pt-6' style={{ width: `max(100%, ${segments.length * 3.25}rem)` }}>
        {[0, 25, 50, 75, 100].map(percent => <span key={percent} aria-hidden='true'
          className='absolute top-0 font-mono text-[10px] tabular-nums text-muted-foreground'
          style={{ left: `${percent}%`, transform: `translateX(-${percent === 0 ? 0 : percent === 100 ? 100 : 50}%)` }}>
          {timecode(endMs * percent / 100)}
        </span>)}
        <div className='relative flex overflow-hidden rounded-md border bg-background'>
          {segments.map((clip, index) => {
            const active = clip.id === selectedId;
            const description = `Scene ${index + 1}, ${clip.label}, ${timecode(clip.startMs)} to ${timecode(clip.endMs)}`;
            return <button type='button' key={clip.id} aria-pressed={active} aria-label={description}
              title={description} disabled={disabled} onClick={() => onSelect(clip.id)}
              style={{ flex: `${clip.durationMs} 1 0%` }}
              className={`relative h-12 min-w-0 overflow-hidden text-left focus-visible:z-10 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring disabled:opacity-60 ${active ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground hover:bg-accent'}`}>
              <span className='absolute inset-y-0 left-0 border-l border-background/50' />
              <span className='block truncate px-2 text-xs font-medium'>{index + 1} · {clip.label}</span>
            </button>;
          })}
          {playhead != null && <span aria-hidden='true' className='pointer-events-none absolute inset-y-0 w-0.5 -translate-x-px bg-foreground shadow-[0_0_0_1px_var(--background)]'
            style={{ left: `${100 * playhead / endMs}%` }} />}
        </div>
      </div>
    </div>
    {selected && <p className='text-xs text-muted-foreground'><span className='font-medium text-foreground'>{selected.label}</span>
      {' · '}{timecode(selected.startMs)}–{timecode(selected.endMs)}</p>}
  </Surface>;
}
