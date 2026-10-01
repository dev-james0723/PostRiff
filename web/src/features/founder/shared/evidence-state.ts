'use client';

import { useCallback } from 'react';
import { parseAsString, useQueryState } from 'nuqs';

/**
 * The evidence drawer is addressed by the URL (`?evidence=<receiptId>`): opening pushes history so Back closes it,
 * Escape and the close button clear the parameter, and a shared link opens straight onto the receipt. Only the opaque
 * receipt id travels, never a record's name.
 */
export function useEvidence() {
  const [receiptId, setReceiptId] = useQueryState('evidence', parseAsString.withOptions({ history: 'push' }));
  const open = useCallback((id: string) => void setReceiptId(id), [setReceiptId]);
  const close = useCallback(() => void setReceiptId(null), [setReceiptId]);
  return { receiptId, open, close };
}
