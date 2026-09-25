'use client';

import type { ReactNode } from 'react';
import { LevelBadge, levelKey } from '@/components/app/level-badge';
import { CAPABILITY_LEVELS, capabilityDotClass } from '@/components/marketing/capability-badge';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { Capability } from '@/lib/api/types';
import { CAPABILITY_CHIPS, LEVEL_MEANING, type CapabilityChipDef } from '@/lib/channels/capabilities';
import { useHoverCapable } from '@/lib/hooks/use-hover-capable';
import { formatDateTime } from '@/lib/time';
import { cn } from '@/lib/utils';
import { POPOVER_ELEVATED } from './rafii-materials';

const HOVER_OPEN_DELAY = 80;
const HOVER_CLOSE_DELAY = 100;

function ChipEvidence({ chip, value }: { chip: CapabilityChipDef; value: Capability | undefined }) {
  const level = value?.level ?? 'Unsupported';
  const evidence = value?.evidence?.trim();
  return (
    <div className='flex flex-col gap-2'>
      <div className='flex items-center justify-between gap-2'>
        <span className='text-foreground font-medium'>{chip.label}</span>
        <LevelBadge level={level} />
      </div>
      <p className='text-muted-foreground text-xs leading-relaxed'>{chip.meaning}</p>
      <p className='text-foreground text-xs leading-relaxed'>{evidence || LEVEL_MEANING[level] || LEVEL_MEANING.Unsupported}</p>
      <dl className='text-muted-foreground grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-xs'>
        <dt>Verified</dt>
        <dd>{value?.verifiedAt ? formatDateTime(value.verifiedAt) : 'Not yet'}</dd>
      </dl>
    </div>
  );
}

/** Borderless quiet chips with a visible focus ring (DNA §2.2); the whole chip is the hit target. */
function chipClasses(level: string | undefined) {
  const key = levelKey(level);
  return cn(
    'rafii-focus inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-full px-3 text-xs font-medium whitespace-nowrap transition-colors',
    'bg-foreground/5 hover:bg-foreground/10',
    key === 'unsupported' ? 'text-muted-foreground hover:text-foreground' : 'text-foreground'
  );
}

/** The verified level is carried by the dot and by the word beside it, never by colour alone (DNA §4.3). */
function ChipFace({ chip, level }: { chip: CapabilityChipDef; level: string | undefined }) {
  const key = levelKey(level);
  return (
    <>
      <span aria-hidden className={cn('size-1.5 rounded-full', capabilityDotClass(key))} />
      {chip.label}
      <span className='text-muted-foreground font-normal'>{CAPABILITY_LEVELS[key].label}</span>
    </>
  );
}

/**
 * Six capability chips for one account. The dot colour and the word are the verified level; hover or
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
  const unsupported = CAPABILITY_CHIPS.filter((chip) => levelKey(capabilities[chip.key]?.level) === 'unsupported').length;
  return (
    <ul className={cn('flex flex-wrap gap-1.5', className)} aria-label='Capabilities' {...rest}>
      {CAPABILITY_CHIPS.map((chip) => {
        const value = capabilities[chip.key];
        const level = value?.level;
        const label = `${chip.label}: ${level ?? 'Unsupported'}. Show details`;
        const content: ReactNode = <ChipEvidence chip={chip} value={value} />;
        return (
          // Phones list only what the account can do; the unsupported ones collapse into one count below.
          <li key={chip.key} className={cn('contents', levelKey(level) === 'unsupported' && 'max-md:hidden')}>
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
                <HoverCardContent align='start' className={cn(POPOVER_ELEVATED, 'w-72')}>
                  {content}
                </HoverCardContent>
              </HoverCard>
            ) : (
              <Popover>
                <PopoverTrigger aria-label={label} className={chipClasses(level)}>
                  <ChipFace chip={chip} level={level} />
                </PopoverTrigger>
                <PopoverContent align='start' className={cn(POPOVER_ELEVATED, 'w-72')}>
                  {content}
                </PopoverContent>
              </Popover>
            )}
          </li>
        );
      })}
      {unsupported > 0 && <li className='text-muted-foreground inline-flex min-h-9 items-center px-1 text-xs md:hidden'>+{unsupported} not supported</li>}
    </ul>
  );
}
