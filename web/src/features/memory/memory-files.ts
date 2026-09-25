import type { MemoryEgress, MemoryFile } from '@/lib/api/types';

/**
 * Which rendered memory files a writing route actually receives. The API names them in
 * `egress.sharedFiles` (the prompt files, in prompt order); every other file is rendered for people
 * to read. Nothing here assumes the list: when the API leaves it out, no file is labelled.
 */
export type DraftGroup = 'given' | 'reference';

export const DRAFT_GROUP_LABEL: Record<DraftGroup, string> = {
  given: 'Sent to writers',
  reference: 'For you to read'
};

/**
 * The name a person reads for a memory file. The API keys them as files (`VOICE.md`), which is how writers
 * receive them; people see what the file is about instead. Unknown files lose only the extension.
 */
const FILE_LABELS: Record<string, string> = {
  'AGENT.md': 'How Rafii works',
  'IDENTITY.md': 'Identity',
  'VOICE.md': 'Voice',
  'BOUNDARIES.md': 'Boundaries',
  'BRAND.md': 'Brand'
};

export function memoryFileLabel(name: string): string {
  if (FILE_LABELS[name]) return FILE_LABELS[name];
  const base = name.replace(/\.md$/i, '').replace(/[_-]+/g, ' ').trim().toLowerCase();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : name;
}

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
