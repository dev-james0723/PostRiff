/**
 * The Library's OpenUI task components, as plain descriptors for the site-wide runtime to register
 * (contract agreed with the "Rafii × OpenUI" runtime owner; their registry is features/agent/generative-ui/library.tsx).
 *
 *   { name: PascalCase, version, propsSchema: zod v4 strict object with a stable (positional) key order,
 *     component: React component taking the validated props plus an injected `onAction(actionId, inputs, event)`
 *       (`event` is the press itself; the Library's own host requires it, trusted and from the issuing component),
 *     actions: action ids only }
 *
 * This file adds no OpenUI dependency. OpenUI composes only the task-result region; the Library shell stays the
 * deterministic app. Components never write on mount or in effects: their controls call `onAction`, which the host
 * routes through `useLibraryActionAdapter` (the trusted press on that action's own control, issued targets, a fresh
 * idempotency key per press and the same key on Retry, one at a time). Visible labels come from the action type.
 */
import type { ComponentType } from 'react';
import type { z } from 'zod';
import { LIBRARY_ACTION_TYPES, LIBRARY_OPENUI_SCHEMAS, LIBRARY_OPENUI_VERSION, parseLibraryProps, type LibraryOpenUiName } from '@/lib/library/openui-schemas';
import { manifestActionId } from '@/lib/library/openui-policy';
import {
  AssetCandidateCard,
  CollectionProposal,
  DraftWorkspace,
  ProcessingStatus,
  SourceCitation,
  SourcePackReview,
  SourceScope,
  SuggestionReview,
  VersionComparison,
  type HostInjected
} from './components';

export type LibraryOpenUiComponent = ComponentType<Record<string, unknown> & HostInjected>;

export interface LibraryOpenUiDescriptor {
  name: LibraryOpenUiName;
  version: string;
  propsSchema: z.ZodObject;
  component: LibraryOpenUiComponent;
  actions: readonly string[];
}

function describe<N extends LibraryOpenUiName>(name: N, component: ComponentType<z.infer<(typeof LIBRARY_OPENUI_SCHEMAS)[N]['schema']> & HostInjected>): LibraryOpenUiDescriptor {
  const entry = LIBRARY_OPENUI_SCHEMAS[name];
  return {
    name,
    version: LIBRARY_OPENUI_VERSION,
    propsSchema: entry.schema as unknown as z.ZodObject,
    // The schema validates props before render, so the component's own prop type holds at runtime.
    component: component as unknown as LibraryOpenUiComponent,
    actions: entry.actions
  };
}

/** The versioned Rafii Library allowlist. Anything else in a task result is rejected, never rendered. */
export const LIBRARY_OPENUI_DESCRIPTORS: readonly LibraryOpenUiDescriptor[] = [
  describe('AssetCandidateCard', AssetCandidateCard),
  describe('SourceCitation', SourceCitation),
  describe('SourceScope', SourceScope),
  describe('VersionComparison', VersionComparison),
  describe('CollectionProposal', CollectionProposal),
  describe('SourcePackReview', SourcePackReview),
  describe('DraftWorkspace', DraftWorkspace),
  describe('ProcessingStatus', ProcessingStatus),
  describe('SuggestionReview', SuggestionReview)
];

const BY_NAME = new Map(LIBRARY_OPENUI_DESCRIPTORS.map((descriptor) => [descriptor.name as string, descriptor]));

/** Lookup for the deterministic renderer and adapters; unknown names return undefined. */
export function libraryDescriptor(name: string): LibraryOpenUiDescriptor | undefined {
  return BY_NAME.get(name);
}

/**
 * The runtime's manifest id for each server action type: `library_` plus the type in snake case
 * (collection.save → library_collection_save; ^[a-z][a-z0-9_]{1,63}$). library.select and library.open stay host-only.
 */
export const LIBRARY_OPENUI_ACTION_IDS: Readonly<Record<(typeof LIBRARY_ACTION_TYPES)[number], string>> = Object.fromEntries(
  LIBRARY_ACTION_TYPES.map((type) => [type, manifestActionId(type)])
) as Record<(typeof LIBRARY_ACTION_TYPES)[number], string>;

/** Props validation for task results (unknown component → null). */
export const parseLibraryTaskProps = parseLibraryProps;
