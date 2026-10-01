'use client';

import type { FounderSectionProps } from '../sections';
import { CustomersView } from './customers-view';
import { FounderAskProvider } from './kit/ask';

/** `/founder/customers` — the list, saved views and Customer 360 sheet (CONTRACTS §6). */
export default function CustomersSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='customers' onAsk={onAsk}>
      <CustomersView />
    </FounderAskProvider>
  );
}
