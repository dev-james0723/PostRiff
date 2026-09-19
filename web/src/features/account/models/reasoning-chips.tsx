import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ReasoningLevel } from './catalog';

const LEVEL_NAME: Record<string, string> = { quick: 'Quick', standard: 'Standard', deep: 'Deep' };

/**
 * Reasoning levels one route reports, rendered only when the API sends them for that route.
 * Spans throughout, because it can sit inside a radio option's label.
 */
export function ReasoningChips({ levels }: { levels: ReasoningLevel[] }) {
  return (
    <span className='flex flex-col gap-1.5'>
      <span className='text-foreground text-sm font-medium'>Reasoning levels</span>
      {levels.map((level) => (
        <span key={level.id} className='flex flex-wrap items-center gap-2 text-sm'>
          <Badge variant='outline' className={cn(!level.available && 'text-muted-foreground border-dashed')}>
            {LEVEL_NAME[level.id] ?? level.id}
            {level.available ? '' : ' · not available'}
          </Badge>
          {level.detail && <span className='text-muted-foreground text-xs'>{level.detail}</span>}
        </span>
      ))}
    </span>
  );
}
