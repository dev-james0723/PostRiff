import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ReasoningLevel } from './catalog';

const LEVEL_NAME: Record<string, string> = { quick: 'Quick', standard: 'Standard', deep: 'Deep' };

/**
 * Reasoning levels one route reports, rendered only when the API sends them for that route.
 * Spans throughout, because it can sit inside a radio option's label. Monochrome: an unavailable
 * level says so in words (DNA §22.3), not in colour.
 */
export function ReasoningChips({ levels }: { levels: ReasoningLevel[] }) {
  // One row of chips; each level's note is its tooltip, not a visible line under it.
  return (
    <span className='flex flex-wrap items-center gap-1.5'>
      <span className='text-muted-foreground text-xs'>Reasoning</span>
      {levels.map((level) => (
        <Badge key={level.id} variant='secondary' title={level.detail || undefined} className={cn(!level.available && 'text-muted-foreground border-dashed')}>
          {level.label || LEVEL_NAME[level.id] || level.id}
          {level.available ? '' : ' · not available'}
        </Badge>
      ))}
    </span>
  );
}
