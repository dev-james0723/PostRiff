'use client';

import { SegmentedControl } from '@/components/rafii';
import { StatusChip } from '@/features/workspace/rafii-parts';
import type { FounderMode } from '@/lib/founder/types';
import { cn } from '@/lib/utils';

/** Live / Demo data mode switch (one selection lens). Demo is a data mode, never an environment, so the copy says "data". */
export function ModePill({ mode, onChange, size = 'sm', className }: { mode: FounderMode; onChange: (mode: FounderMode) => void; size?: 'sm' | 'md'; className?: string }) {
  return (
    <SegmentedControl<FounderMode>
      label='Data mode'
      size={size}
      widths='content'
      value={mode}
      onChange={onChange}
      className={cn('shrink-0', className)}
      options={[
        { value: 'live', label: 'Live', title: 'Live records from this environment' },
        { value: 'demo', label: 'Demo', title: 'Fictional data; emails, calls and account changes stay off' }
      ]}
    />
  );
}

export function ModeBadge({ mode, className }: { mode: FounderMode; className?: string }) {
  return (
    <StatusChip icon={mode === 'demo' ? 'circleDashed' : 'circleCheck'} className={className}>
      {mode === 'demo' ? 'Demo data' : 'Live'}
    </StatusChip>
  );
}
