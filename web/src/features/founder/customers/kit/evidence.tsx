'use client';

import { useCallback, useState } from 'react';
import { useEvidence } from '@/features/founder/shared/evidence-state';
import { EvidenceDrawer } from './shared';

/**
 * Evidence for the domain pages (PRD §5.4). A receipt on its own opens the shell's URL-addressed drawer
 * (`?evidence=<receiptId>`: Back closes it, a link shares it, focus returns to the chip); only a row the page already
 * has on screen opens a controlled drawer here, so the masked record never travels in the address. The drawer
 * itself (web-shell) fetches and masks; nothing is cached here.
 */
export interface EvidenceTarget {
  receiptId?: string | null;
  record?: Record<string, unknown> | null;
}

export function useEvidenceDrawer() {
  const { open: openUrl, close: closeUrl } = useEvidence();
  const [target, setTarget] = useState<EvidenceTarget | null>(null);
  const open = useCallback(
    (next: EvidenceTarget) => {
      if (next.record) {
        setTarget(next);
        return;
      }
      if (next.receiptId) openUrl(next.receiptId);
    },
    [openUrl]
  );
  const close = useCallback(() => {
    setTarget(null);
    closeUrl();
  }, [closeUrl]);
  const drawer = target ? (
    <EvidenceDrawer
      open
      onOpenChange={(next: boolean) => {
        if (!next) setTarget(null);
      }}
      receiptId={target.receiptId ?? null}
      record={target.record ?? null}
    />
  ) : null;
  return { open, close, drawer, target };
}

/** The one receipt chip (web-shell): opens the URL-addressed drawer, so a chip on a tile and one in Customer 360 behave the same. */
export { ReceiptChip } from '@/features/founder/shared/receipt-chip';
