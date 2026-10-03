'use client';

import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/utils';
import { RafiiThinkingOrb } from './rafii-thinking-orb';
import { THINKING_LABELS, type ThinkingOp } from './thinking-op';

function formatElapsed(totalSeconds: number) {
  const safe = Math.max(0, totalSeconds);
  const minutes = Math.floor(safe / 60);
  const seconds = (safe % 60).toFixed(1);
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

export interface RafiiThinkingStatusProps {
  op: ThinkingOp;
  size?: 20 | 64;
  startedAt?: number;
  elapsedSeconds?: number;
  showElapsed?: boolean;
  announce?: boolean;
  className?: string;
  label?: string;
}

export function RafiiThinkingStatus({
  op,
  size = 20,
  startedAt,
  elapsedSeconds,
  showElapsed = true,
  announce = true,
  className,
  label
}: RafiiThinkingStatusProps) {
  const initial = useMemo(() => (startedAt == null ? 0 : Math.max(0, Date.now() / 1000 - startedAt)), [startedAt]);
  const [elapsed, setElapsed] = useState(initial);

  useEffect(() => {
    if (!showElapsed || elapsedSeconds != null || startedAt == null || op === 'breathing') return;
    const origin = performance.now() - initial * 1000;
    const timer = window.setInterval(() => setElapsed((performance.now() - origin) / 1000), 100);
    return () => window.clearInterval(timer);
  }, [elapsedSeconds, initial, op, showElapsed, startedAt]);

  const text = label ?? THINKING_LABELS[op];
  const visibleElapsed = elapsedSeconds ?? elapsed;

  return (
    <span
      role='status'
      aria-live={announce ? 'polite' : 'off'}
      aria-label={text}
      data-thinking-op={op}
      className={cn('text-muted-foreground inline-flex items-center gap-2 text-xs', className)}
    >
      <RafiiThinkingOrb op={op} size={size} className='inline-flex shrink-0' />
      <span className='font-medium'>{text}</span>
      {showElapsed && op !== 'breathing' && (startedAt != null || elapsedSeconds != null) ? (
        <span aria-hidden='true' className='tabular-nums text-muted-foreground/70'>
          {formatElapsed(visibleElapsed)}
        </span>
      ) : null}
    </span>
  );
}
