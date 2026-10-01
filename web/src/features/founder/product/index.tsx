'use client';

import { FounderAskProvider } from '../customers/kit/ask';
import type { FounderSectionProps } from '../sections';
import { ProductView } from './product-view';

/** `/founder/product` — activation funnel and stuck workspaces, time to value, adoption, retention, time back and correlations. */
export default function ProductSection({ onAsk }: FounderSectionProps) {
  return (
    <FounderAskProvider section='product' onAsk={onAsk}>
      <ProductView />
    </FounderAskProvider>
  );
}
