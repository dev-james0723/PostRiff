/**
 * Turns an applied Content Library value into the workspace content selection the backend understands.
 *
 * The library keeps a planning vocabulary (31 editorial types, 20 native formats); the runtime records
 * one content type and one of ten format families (`contentSystem.selection`). `contentChoice()` is the
 * pure translation; `selectLibraryContent()` performs it through the workspace action channel the way
 * `selectContentType` in `home-view.tsx` does for Quick Starts: install `pack.creator` once when the
 * chosen type lives in the starter pack, then `p2_content_select { contentTypeId, formatId }`.
 *
 * A native format the runtime cannot draft is `planning-only`: the choice is kept for the composer to
 * show honestly (label + note) and the type's default format is recorded explicitly, so nothing is
 * silently coerced and no stale format from an earlier choice leaks in.
 */
import {
  BACKEND_CONTENT_TYPE_BY_ID,
  BACKEND_FORMAT_LABELS,
  CREATOR_PACK,
  PLANNING_ONLY_LABEL,
  executionFor,
  intentFor,
  taxonomyItem,
  type ComposerIntent
} from '@/lib/content-library';

export interface LibraryValue {
  editorialId: string;
  nativeId: string;
}

export interface PlanningOnlyNote {
  nativeId: string;
  /** The library title of the native format, e.g. "Livestream". */
  title: string;
  /** "Planning only · export or manual posting". */
  label: string;
  /** Why the runtime cannot draft this format and what to do instead. */
  note: string;
  /** The backend format recorded meanwhile (the content type's default), for the composer to state. */
  recordedFormatId: string;
  recordedFormatLabel: string;
}

export interface ContentChoice {
  value: LibraryValue;
  contentTypeId: string;
  contentTypeLabel: string;
  /** Backend format the draft will use; for planning-only formats this is the type's default. */
  formatId: string;
  formatLabel: string;
  /** Present when the native format is planning-only. */
  planningOnly: PlanningOnlyNote | null;
  /** Composer intent hint (Thread, Carousel, Video script, Post); not a backend value. */
  intent: ComposerIntent;
  /** Exactly what `p2_content_select` receives. */
  payload: { contentTypeId: string; formatId: string };
  /** "Status update · Text", for chips and confirmations. */
  summary: string;
  /** Whether the chosen type lives in the creator starter pack. */
  needsCreatorPack: boolean;
}

/** The translation, or null when either id is not a library item of the right dimension. */
export function contentChoice(value: LibraryValue): ContentChoice | null {
  const editorial = taxonomyItem(value.editorialId);
  const native = taxonomyItem(value.nativeId);
  if (!editorial || editorial.dimension !== 'editorial' || !native || native.dimension !== 'native') return null;
  const typeMapping = executionFor(editorial.id);
  const formatMapping = executionFor(native.id);
  if (!typeMapping?.contentTypeId || !formatMapping) return null;
  const type = BACKEND_CONTENT_TYPE_BY_ID[typeMapping.contentTypeId];
  if (!type) return null;
  const planning = formatMapping.execution === 'planning-only' || !formatMapping.formatId;
  const formatId = planning ? type.recommendedFormatIds[0] : formatMapping.formatId!;
  const formatLabel = BACKEND_FORMAT_LABELS[formatId] ?? formatId;
  return {
    value: { editorialId: editorial.id, nativeId: native.id },
    contentTypeId: type.id,
    contentTypeLabel: type.label,
    formatId,
    formatLabel,
    planningOnly: planning ? { nativeId: native.id, title: native.title, label: PLANNING_ONLY_LABEL, note: formatMapping.note, recordedFormatId: formatId, recordedFormatLabel: formatLabel } : null,
    intent: intentFor(native.id),
    payload: { contentTypeId: type.id, formatId },
    summary: `${editorial.title} · ${native.title}`,
    needsCreatorPack: type.id.startsWith(`${CREATOR_PACK.packId}:`)
  };
}

/** The slice of the API client this helper needs (`api.act` returns the new snapshot). */
export interface ContentActionApi<S extends { revision: number }> {
  act: (workspaceId: string, expectedRevision: number, action: string, payload: Record<string, unknown>) => Promise<S>;
}

export interface SelectLibraryContentResult<S extends { revision: number }> {
  choice: ContentChoice;
  /** The snapshot after the last action; callers put it in the query cache. */
  snapshot: S;
  revision: number;
}

/**
 * Applies a library value to the workspace: installs the creator pack when needed, then selects the
 * type and format. Throws the `ApiError` of the failing action (a 409 means a stale revision: refetch
 * and retry once, as `use-channel-languages.ts` does). Rejects with a plain Error for unknown ids.
 */
export async function selectLibraryContent<S extends { revision: number }>(
  api: ContentActionApi<S>,
  workspaceId: string,
  revision: number,
  installedPacks: { id: string }[] | undefined,
  value: LibraryValue
): Promise<SelectLibraryContentResult<S>> {
  const choice = contentChoice(value);
  if (!choice) throw new Error('Choose an editorial type and a native format from the Content Library.');
  let current = revision;
  let snapshot: S | null = null;
  if (choice.needsCreatorPack && !installedPacks?.some((pack) => pack.id === CREATOR_PACK.packId)) {
    snapshot = await api.act(workspaceId, current, 'p2_content_install_pack', { ...CREATOR_PACK });
    current = snapshot.revision;
  }
  snapshot = await api.act(workspaceId, current, 'p2_content_select', { ...choice.payload });
  return { choice, snapshot, revision: snapshot.revision };
}
