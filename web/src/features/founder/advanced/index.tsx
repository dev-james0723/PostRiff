'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { AdvancedView } from './advanced-view';

/** `/founder/advanced` — audit log, receipt lookup and source health detail (CONTRACTS §6). */
export default function AdvancedSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='advanced' onAsk={onAsk}>
      <AdvancedView />
    </FounderAskProvider>
  );
}
