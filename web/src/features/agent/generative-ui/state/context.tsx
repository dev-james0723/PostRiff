'use client';

/**
 * The view-state bridge of one generated artifact (lane F), provided by F's surface around C's RafiiGenerativeMessage.
 *
 * C's renderer reads it to wire OpenUI: `initialState` (persisted safe state with this tab's unsaved fields on top; keep it
 * referentially stable between revisions, openui-package §5) and `onStateUpdate` (the Renderer callback). Rafii components
 * that let the person pick records report the ordered selection with `useRecordSelection()` (selection.ts) so a follow-up such
 * as "compare the second draft" resolves against the order shown at selection time. Outside a provider every hook is a no-op.
 */
import { createContext, useContext } from 'react';
import type { JsonValue } from '@/lib/agent-runtime/ui-contracts';
import type { DeclaredState, SelectionItem } from './persisted-state';

export interface UiArtifactStateBridge {
  artifactId: string;
  revision: number;
  stateRevision: number;
  /** OpenUI `initialState` for this revision (stable object until the revision or scope changes). */
  initialState: Record<string, JsonValue>;
  /** Pass to `<Renderer onStateUpdate>`; whitelists declared fields and debounces the save. */
  onStateUpdate: (snapshot: Record<string, unknown>) => void;
  /** Record the ordered selection of one list (`listId`), and optionally the list as currently shown. */
  recordSelection: (listId: string, items: SelectionItem[], visibleOrder?: SelectionItem[]) => void;
  /** Fields this tab changed that are not saved yet (a patch that would remove one must warn first). */
  dirtyFields: () => string[];
  declared: DeclaredState;
  /** Writes of view state are possible for this caller (viewers keep state in the tab only). */
  canPersist: boolean;
}

export const UiArtifactStateContext = createContext<UiArtifactStateBridge | null>(null);

export function useUiArtifactState(): UiArtifactStateBridge | null {
  return useContext(UiArtifactStateContext);
}
