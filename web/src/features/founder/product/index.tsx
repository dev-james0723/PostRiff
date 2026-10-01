'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { ProductView } from './product-view';

/** `/founder/product` — active workspaces, publish outcomes, time back and the honest activation / retention state. */
export default function ProductSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='product' onAsk={onAsk}>
      <ProductView />
    </FounderAskProvider>
  );
}
