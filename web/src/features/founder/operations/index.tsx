'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { OperationsView } from './operations-view';

/** `/founder/operations` — incidents with ack, publishing, notification delivery, phone calls and source health. */
export default function OperationsSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='operations' onAsk={onAsk}>
      <OperationsView />
    </FounderAskProvider>
  );
}
