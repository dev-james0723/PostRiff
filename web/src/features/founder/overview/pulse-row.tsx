'use client';

import { MetricTile } from '@/features/founder/shared/metric-tile';
import type { PulseTile } from '@/lib/founder/types';

/**
 * The pulse row (PRD §5.2 B): up to five pressure gauges the server chose. On phones the row scrolls sideways; from
 * `lg` all tiles share one line. A tile that is not ready still appears, saying since when it has been collecting.
 * `relative` makes the row the containing block for the tiles' screen-reader-only text (absolutely positioned), which
 * otherwise sat at its static place in the fifth tile, outside the scroller, and widened the phone page.
 */
export function PulseRow({ tiles, onAsk }: { tiles: PulseTile[]; onAsk: (tile: PulseTile) => void }) {
  if (tiles.length === 0) return null;
  return (
    <div role='list' aria-label='Pulse' data-tour='founder-pulse' className='scrollbar-hide relative -mx-4 flex w-[calc(100%+2rem)] min-w-0 snap-x gap-3 overflow-x-auto px-4 pb-1 md:mx-0 md:grid md:w-full md:grid-cols-3 md:overflow-visible md:px-0 lg:grid-cols-5'>
      {tiles.slice(0, 5).map((tile) => (
        <div key={tile.id} role='listitem' className='w-[min(17rem,80vw)] shrink-0 snap-start md:w-auto'>
          <MetricTile {...tile} onAsk={() => onAsk(tile)} className='h-full' />
        </div>
      ))}
    </div>
  );
}
