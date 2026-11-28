'use client';

import { useRef, useState } from 'react';
import { Surface } from '@/components/rafii/surface';
import { Button } from '@/components/ui/button';
import { CutTimeline } from '@/features/creative-video/cut-timeline';

const versions = [
  { file: 'reference', label: 'Reference', detail: 'Rafii detected cuts at 1.25 and 2.75 seconds.' },
  { file: 'original-cut', label: 'First cut', detail: 'Three original shots follow the timing of the reference.' },
  { file: 'revised-cut', label: 'Revised opening', detail: 'The opening shot and its caption change in this version.' }
] as const;
type Version = (typeof versions)[number]['file'];

const shots = [
  { id: 'opening', label: 'Opening', startMs: 0, endMs: 1250, caption: 'A turn to begin.' },
  { id: 'middle', label: 'Dial in motion', startMs: 1250, endMs: 2750, caption: 'Time in motion.' },
  { id: 'closing', label: 'Closing', startMs: 2750, endMs: 4000, caption: 'Find your tempo.' }
].map(shot => ({ ...shot, durationMs: shot.endMs - shot.startMs }));

export function SampleCutPlayer() {
  const [version, setVersion] = useState<Version>('original-cut');
  const [positionMs, setPositionMs] = useState(0);
  const players = useRef<Partial<Record<Version, HTMLVideoElement | null>>>({});
  const active = useRef<Version>('original-cut');
  const pendingMs = useRef<number | null>(null);
  const selected = shots.find(shot => positionMs < shot.endMs) ?? shots[shots.length - 1];
  const caption = version === 'revised-cut' && selected.id === 'opening' ? 'Start with one turn.' : selected.caption;

  function seek(ms: number) {
    const video = players.current[active.current];
    setPositionMs(ms);
    if (video && video.readyState >= 1) {
      pendingMs.current = null;
      video.currentTime = ms / 1000;
    } else {
      pendingMs.current = ms;
    }
  }

  function compare(next: Version) {
    if (active.current === next) return;
    const previous = players.current[active.current];
    const time = pendingMs.current ?? (previous ? previous.currentTime * 1000 : positionMs);
    previous?.pause();
    active.current = next;
    setVersion(next);
    seek(time);
  }

  return (
    <Surface as='section' material='paper' aria-labelledby='sample-timeline' className='grid min-w-0 gap-5'>
      <div className='grid gap-1'>
        <h2 id='sample-timeline' className='text-xl font-medium'>Explore the cut</h2>
        <p className='text-muted-foreground text-sm'>Choose a shot on the timeline, then switch versions to compare the same moment.</p>
      </div>
      <div className='grid min-w-0 gap-5 sm:grid-cols-[minmax(0,15rem)_minmax(0,1fr)]'>
        <div className='overflow-hidden rounded-lg bg-black'>
          {versions.map(({ file, label }) => (
            <div key={file} hidden={version !== file}>
              <video ref={node => { players.current[file] = node; }} aria-label={label} controls playsInline preload='metadata'
                className='mx-auto aspect-[9/16] w-full max-w-60'
                src={`/rafii/studio-examples/${file}.mp4`}
                onLoadedMetadata={() => { if (file === active.current && pendingMs.current !== null) seek(pendingMs.current); }}
                onTimeUpdate={event => {
                  if (file === active.current && pendingMs.current === null) setPositionMs(event.currentTarget.currentTime * 1000);
                }}>
                <track kind='captions' label='English' srcLang='en' src={`/rafii/studio-examples/${file}.vtt`} />
              </video>
            </div>
          ))}
        </div>
        <div className='grid content-start gap-4'>
          <div role='group' aria-label='Video version' className='flex flex-wrap gap-2'>
            {versions.map(({ file, label }) => (
              <Button type='button' key={file} size='sm' variant={version === file ? 'default' : 'outline'}
                aria-pressed={version === file} onClick={() => compare(file)}>{label}</Button>
            ))}
          </div>
          <p className='text-muted-foreground text-sm'>{versions.find(item => item.file === version)?.detail}</p>
          <dl className='grid gap-2 border-t pt-3 text-sm'>
            <div><dt className='text-muted-foreground'>Shot</dt><dd className='font-medium'>{selected.label}</dd></div>
            <div><dt className='text-muted-foreground'>Time in cut</dt><dd>{selected.startMs / 1000}–{selected.endMs / 1000} s</dd></div>
            {version !== 'reference' && <div><dt className='text-muted-foreground'>Caption</dt><dd>{caption}</dd></div>}
          </dl>
        </div>
      </div>
      <CutTimeline clips={shots} selectedId={selected.id} positionMs={positionMs} onSelect={id => {
        const shot = shots.find(item => item.id === id);
        if (shot) seek(shot.startMs);
      }} />
    </Surface>
  );
}
