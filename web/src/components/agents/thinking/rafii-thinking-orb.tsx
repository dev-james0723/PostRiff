'use client';

import { useEffect, useState } from 'react';
import { ThinkingOrb } from 'thinking-orbs';
import { OFFICIAL_ORB_STATE, type ThinkingOp } from './thinking-op';

export interface RafiiThinkingOrbProps {
  op: ThinkingOp;
  size?: 20 | 64;
  className?: string;
}

export function RafiiThinkingOrb({ op, size = 20, className }: RafiiThinkingOrbProps) {
  const [actingState, setActingState] = useState<'connecting' | 'working'>('connecting');

  useEffect(() => {
    if (op !== 'acting') {
      setActingState('connecting');
      return;
    }
    setActingState('connecting');
    const timer = window.setTimeout(() => setActingState('working'), 400);
    return () => window.clearTimeout(timer);
  }, [op]);

  const state = op === 'acting' ? actingState : OFFICIAL_ORB_STATE[op];

  return (
    <span aria-hidden='true' className={className}>
      <ThinkingOrb state={state} size={size} />
    </span>
  );
}
