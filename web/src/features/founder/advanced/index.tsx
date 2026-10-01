'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { AdvancedView } from './advanced-view';

/** `/founder/advanced` — audit log, receipt lookup, source health detail, founder actions and engineering evidence (CONTRACTS §6). */
export default function AdvancedSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='advanced' onAsk={onAsk}>
      <AdvancedView />
    </FounderAskProvider>
  );
}
