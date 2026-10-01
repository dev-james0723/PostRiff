'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { RevenueView } from './revenue-view';

/** `/founder/revenue` — cash, subscriptions, payment failures, refunds and the honest MRR state (CONTRACTS §6). */
export default function RevenueSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='revenue' onAsk={onAsk}>
      <RevenueView />
    </FounderAskProvider>
  );
}
