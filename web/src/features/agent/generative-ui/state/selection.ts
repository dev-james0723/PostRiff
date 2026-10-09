'use client';

/**
 * `useRecordSelection()` (lane F → C/E components): record what the person selected in a generated list, in the order shown
 * when they selected, plus the list as shown then. Saved into the view's persisted state under the reserved `@selection` key
 * (debounced, whitelisted, CAS) and read back by the server's `ui_store.selection_context` for the next text or voice turn.
 *
 *   const record = useRecordSelection();
 *   record('drafts', [{ type: 'draft', id: 'd2', title: 'Spring launch' }], [{ type: 'draft', id: 'd1' }, { type: 'draft', id: 'd2' }]);
 *
 * Ids are opaque record ids from bound query data (never model text); a title is display text kept with the view only and
 * never sent to a model. Outside a generated view the function does nothing.
 */
import { useCallback } from 'react';
import { useUiArtifactState } from './context';
import type { SelectionItem } from './persisted-state';
import { noteUiInteraction } from './registry';

export type RecordSelection = (listId: string, items: SelectionItem[], visibleOrder?: SelectionItem[]) => void;

export function useRecordSelection(): RecordSelection {
  const bridge = useUiArtifactState();
  return useCallback<RecordSelection>((listId, items, visibleOrder) => {
    if (!bridge) return;
    bridge.recordSelection(listId, items, visibleOrder);
    noteUiInteraction(bridge.artifactId);
  }, [bridge]);
}
