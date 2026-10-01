'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { SupportView } from './support-view';

/** `/founder/support` — data request backlog and aging, with the readiness note that no ticket system exists. */
export default function SupportSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='support' onAsk={onAsk}>
      <SupportView />
    </FounderAskProvider>
  );
}
