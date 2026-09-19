import type { MemoryEgress, MemoryFile } from '@/lib/api/types';

/**
 * Which rendered memory files a writing route actually receives. The API names them in
 * `egress.sharedFiles` (the prompt files, in prompt order); every other file is rendered for people
 * to read. Nothing here assumes the list: when the API leaves it out, no file is labelled.
 */
export type DraftGroup = 'given' | 'reference';

export const DRAFT_GROUP_LABEL: Record<DraftGroup, string> = {
  given: 'Given to writing routes',
  reference: 'For you to read'
};

export interface GroupedMemoryFiles {
  /** Files a writing route receives, in the order the API lists them. */
  given: MemoryFile[];
  /** Files shown here for people and never sent to a route. */
  reference: MemoryFile[];
  /** False when the API did not say which files a route receives. */
  known: boolean;
}

export function groupMemoryFiles(files: MemoryFile[], egress: MemoryEgress | undefined): GroupedMemoryFiles {
  const shared = egress?.sharedFiles;
  if (!Array.isArray(shared)) return { given: [], reference: files, known: false };
  const byName = new Map(files.map((file) => [file.name, file]));
  const given = shared.flatMap((name) => byName.get(name) ?? []);
  const reference = files.filter((file) => !shared.includes(file.name));
  return { given, reference, known: true };
}

export function draftGroupOf(grouped: GroupedMemoryFiles, name: string): DraftGroup | null {
  if (!grouped.known) return null;
  return grouped.given.some((file) => file.name === name) ? 'given' : 'reference';
}
