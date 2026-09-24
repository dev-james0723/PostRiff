import type { ActionId, ActionImpl } from 'kbar';
import * as React from 'react';
import { Kbd } from '@/components/ui/kbd';
import { cn } from '@/lib/utils';

/** One palette row: the active row carries the selection lens (DNA §5.2), never a hard outline. */
const ResultItem = React.forwardRef(
  (
    {
      action,
      active,
      currentRootActionId
    }: {
      action: ActionImpl;
      active: boolean;
      currentRootActionId: ActionId;
    },
    ref: React.Ref<HTMLDivElement>
  ) => {
    const ancestors = React.useMemo(() => {
      if (!currentRootActionId) return action.ancestors;
      const index = action.ancestors.findIndex((ancestor) => ancestor.id === currentRootActionId);
      return action.ancestors.slice(index + 1);
    }, [action.ancestors, currentRootActionId]);

    return (
      <div
        ref={ref}
        className={cn(
          'relative mx-2.5 flex min-h-11 cursor-pointer items-center justify-between gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2 text-sm transition-colors',
          active ? 'rafii-lens text-foreground' : 'text-foreground'
        )}
      >
        <div className='flex min-w-0 items-center gap-2.5'>
          {action.icon}
          <div className='flex min-w-0 flex-col'>
            <div className='truncate'>
              {ancestors.length > 0 &&
                ancestors.map((ancestor) => (
                  <React.Fragment key={ancestor.id}>
                    <span className='text-muted-foreground mr-2'>{ancestor.name}</span>
                    <span className='mr-2'>&rsaquo;</span>
                  </React.Fragment>
                ))}
              <span>{action.name}</span>
            </div>
            {action.subtitle && <span className='text-muted-foreground truncate text-xs'>{action.subtitle}</span>}
          </div>
        </div>
        {action.shortcut?.length ? (
          <div className='grid shrink-0 grid-flow-col gap-1'>
            {action.shortcut.map((sc, i) => (
              <Kbd key={sc + i}>{sc}</Kbd>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
);

ResultItem.displayName = 'KBarResultItem';

export default ResultItem;
