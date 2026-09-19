'use client';

import type { ReactNode } from 'react';
import { LevelBadge, levelKey } from '@/components/app/level-badge';
import { capabilityDotClass } from '@/components/marketing/capability-badge';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { Capability } from '@/lib/api/types';
import { CAPABILITY_CHIPS, LEVEL_MEANING, type CapabilityChipDef } from '@/lib/channels/capabilities';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';

const HOVER_OPEN_DELAY = 80;
const HOVER_CLOSE_DELAY = 100;

function ChipEvidence({ chip, value }: { chip: CapabilityChipDef; value: Capability | undefined }) {
  const level = value?.level ?? 'Unsupported';
  const evidence = value?.evidence?.trim();
  return (
    <div className='flex flex-col gap-2'>
      <div className='flex items-center justify-between gap-2'>
        <span className='font-medium'>{chip.label}</span>
        <LevelBadge level={level} />
      </div>
      <p className='text-muted-foreground text-xs'>{chip.meaning}</p>
      <p className='text-xs'>{evidence || LEVEL_MEANING[level] || LEVEL_MEANING.Unsupported}</p>
      <dl className='text-muted-foreground grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]'>
        <dt>Verified</dt>
        <dd>{value?.verifiedAt ? formatDateTime(value.verifiedAt) : 'Not verified yet'}</dd>
        <dt>Version</dt>
        <dd>capability v{value?.capabilityVersion ?? 0}</dd>
      </dl>
    </div>
  );
}

function chipClasses(level: string | undefined) {
  const key = levelKey(level);
  return cn(
    'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium whitespace-nowrap',
    'outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/50',
    key === 'unsupported'
      ? 'border-border bg-muted text-muted-foreground hover:text-foreground'
      : 'border-border bg-card text-foreground hover:bg-accent'
  );
}

function ChipFace({ chip, level }: { chip: CapabilityChipDef; level: string | undefined }) {
  return (
    <>
      <span aria-hidden className={cn('size-1.5 rounded-full', capabilityDotClass(levelKey(level)))} />
      {chip.label}
      <span className='sr-only'>: {level ?? 'Unsupported'}</span>
    </>
  );
}

/**
 * Six capability chips for one account. The dot colour is the verified level; hover or
 * keyboard focus opens the evidence and its verification time. Touch devices, which
 * cannot hover, get the same content in a tap-to-open popover.
 */
export function CapabilityChips({
  capabilities,
  className,
  ...rest
}: {
  capabilities: Record<string, Capability>;
  className?: string;
  'data-tour'?: string;
}) {
  const canHover = useHoverCapable();
  return (
    <ul className={cn('flex flex-wrap gap-1.5', className)} aria-label='Capabilities' {...rest}>
      {CAPABILITY_CHIPS.map((chip) => {
        const value = capabilities[chip.key];
        const level = value?.level;
        const label = `${chip.label}: ${level ?? 'Unsupported'}. Show evidence`;
        const content: ReactNode = <ChipEvidence chip={chip} value={value} />;
        return (
          <li key={chip.key} className='contents'>
            {canHover ? (
              <HoverCard>
                <HoverCardTrigger
                  render={<button type='button' aria-label={label} />}
                  delay={HOVER_OPEN_DELAY}
                  closeDelay={HOVER_CLOSE_DELAY}
                  className={chipClasses(level)}
                >
                  <ChipFace chip={chip} level={level} />
                </HoverCardTrigger>
                <HoverCardContent align='start' className='w-72'>
                  {content}
                </HoverCardContent>
              </HoverCard>
            ) : (
              <Popover>
                <PopoverTrigger aria-label={label} className={chipClasses(level)}>
                  <ChipFace chip={chip} level={level} />
                </PopoverTrigger>
                <PopoverContent align='start' className='w-72'>
                  {content}
                </PopoverContent>
              </Popover>
            )}
          </li>
        );
      })}
    </ul>
  );
}
