'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { AiCostView } from './ai-cost-view';

/** `/founder/ai-cost` — cost by feature, model / route, coverage, budget and the reconcile queue (CONTRACTS §6). */
export default function AiCostSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='ai-cost' onAsk={onAsk}>
      <AiCostView />
    </FounderAskProvider>
  );
}
