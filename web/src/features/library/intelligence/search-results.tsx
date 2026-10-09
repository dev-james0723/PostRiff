'use client';

import { Icons } from '@/components/icons';
import { PanelButton as Button } from '../ui/controls';
import type { Locator, SearchHit } from '@/lib/api/library-intelligence-types';
import type { Asset } from '@/lib/api/types';
import { normalizeKey } from '@/lib/library/url-state';
import { formatClock, locatorLabel, matchSummary } from '@/lib/library/wording';
import type { HitGroup } from './use-library-search';

/**
 * A stand-in item for a result the browse list has not loaded yet, built only from what the search returned. It shows
 * the right type of cover and title; nothing else about it is guessed.
 */
export function assetFromHit(hit: SearchHit): Asset {
  return {
    id: hit.assetRef.assetId,
    hash: hit.assetRef.sha256,
    mime: hit.mime,
    assetKind: hit.kind,
    displayTitle: hit.displayTitle,
    createdAt: hit.createdAt,
    deleted: false
  };
}

export function resolveHitAsset(group: HitGroup, byKey: ReadonlyMap<string, Asset>): Asset {
  return byKey.get(normalizeKey(group.assetId)) ?? assetFromHit(group.first);
}

/**
 * Why an item matched and where: passages with their page/slide/sheet label, and moments with their time. A moment
 * opens the item at that moment and offers to play from there; nothing plays on its own.
 */
export function HitDetails({ group, onOpenAt, onPlayFrom }: { group: HitGroup; onOpenAt: (locator: Locator | null) => void; onPlayFrom?: (startMs: number) => void }) {
  const reasons = matchSummary(group.hits.flatMap((hit) => hit.matchReasons));
  // Every matching passage or moment the server listed (the best one first), each opening at its own locator.
  const passages = group.hits
    .flatMap((hit) => [
      { key: `${hit.segmentId ?? 'asset'}-best`, title: hit.displayTitle, locator: hit.locator ?? null, label: hit.locatorLabel ?? '', snippet: hit.snippet },
      ...(hit.passages ?? [])
        .filter((passage) => passage.segmentId !== hit.segmentId && passage.locator)
        .map((passage, index) => ({ key: `${passage.segmentId ?? 'passage'}-${index}`, title: hit.displayTitle, locator: passage.locator ?? null, label: passage.locatorLabel ?? '', snippet: '' }))
    ])
    .filter((passage) => passage.locator || passage.snippet)
    .slice(0, 3);
  return (
    <div className='flex min-w-0 flex-col gap-1.5'>
      {reasons ? <p className='text-muted-foreground text-xs'>{reasons}</p> : null}
      {passages.length ? (
        <ul aria-label='Matching passages' className='flex flex-col gap-1'>
          {passages.map((passage) => {
            const where = passage.label || locatorLabel(passage.locator);
            const time = passage.locator?.kind === 'time' ? passage.locator : null;
            return (
              <li key={passage.key} className='flex min-w-0 flex-col gap-0.5'>
                <button
                  type='button'
                  className='rafii-focus hover:rafii-quiet flex min-h-11 min-w-0 flex-col items-start gap-0.5 rounded-[var(--rafii-radius-control)] px-2 py-1.5 text-left'
                  onClick={() => onOpenAt(passage.locator)}
                  aria-label={`Open ${passage.title}${where ? ` at ${where}` : ''}`}
                >
                  {where ? <span className='text-foreground text-xs font-medium'>{where}</span> : null}
                  {passage.snippet ? <span className='text-muted-foreground line-clamp-2 text-xs'>{passage.snippet}</span> : null}
                </button>
                {time && onPlayFrom ? (
                  <Button variant='quiet' size='lg' className='h-11 self-start' onClick={() => onPlayFrom(time.startMs)} aria-label={`Play ${passage.title} from ${formatClock(time.startMs)}`}>
                    <Icons.play aria-hidden />
                    Play from {formatClock(time.startMs)}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
