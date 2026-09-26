/**
 * Session-only, user/workspace-scoped input recovery. Never restores permissions.
 *
 * Version 2 (chat-context SPEC §11.5) adds the message's chips as `{kind, id, label, role, slot, stopped}` only; the
 * composer re-checks every chip against the snapshot on restore. Version 1 records (text only) still decode.
 */
import type { SavedChip } from './attachments/state';

export const briefStorageKey = (owner: string, workspace: string) =>
  `rafii.brief.${encodeURIComponent(owner)}.${encodeURIComponent(workspace)}`;

/** The conversation composer's key: one saved turn per owner, workspace and conversation. */
export const turnStorageKey = (owner: string, workspace: string, conversationId: string) =>
  `rafii.turn.${encodeURIComponent(owner)}.${encodeURIComponent(workspace)}.${encodeURIComponent(conversationId)}`;

const TEXT_MAX = 20000;
const CHIPS_MAX = 16;
const KINDS = new Set(['post', 'template', 'source', 'image', 'video']);
const ROLES = new Set(['rework', 'inspire', 'post', 'reference']);
const SLOTS = new Set(['A', 'B', 'C', 'D']);
const ID = /^[A-Za-z0-9_.:-]{1,120}$/;

export interface SavedBrief {
  text: string;
  chips: SavedChip[];
}

function chipOf(value: unknown): SavedChip | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as Record<string, unknown>;
  if (typeof item.kind !== 'string' || !KINDS.has(item.kind)) return null;
  if (typeof item.id !== 'string' || !ID.test(item.id)) return null;
  if (typeof item.label !== 'string' || item.label.length > 80) return null;
  if (item.role !== undefined && (typeof item.role !== 'string' || !ROLES.has(item.role)))
    return null;
  if (item.slot !== undefined && (typeof item.slot !== 'string' || !SLOTS.has(item.slot)))
    return null;
  return {
    kind: item.kind as SavedChip['kind'],
    id: item.id,
    label: item.label,
    ...(item.role ? { role: item.role as SavedChip['role'] } : {}),
    ...(item.slot ? { slot: item.slot as SavedChip['slot'] } : {}),
    ...(item.stopped === true ? { stopped: true as const } : {})
  };
}

export function encodeBrief(
  owner: string,
  workspace: string,
  text: string,
  chips: readonly SavedChip[] = []
): string {
  if (
    !owner ||
    !workspace ||
    typeof text !== 'string' ||
    text.length > TEXT_MAX ||
    !Array.isArray(chips) ||
    chips.length > CHIPS_MAX
  ) {
    throw new Error('Invalid brief.');
  }
  const clean = chips.map(chipOf);
  if (clean.some((chip) => chip === null)) throw new Error('Invalid brief.');
  return JSON.stringify({ version: 2, owner, workspace, text, chips: clean });
}

/** The saved text and chips for this owner and workspace, or null (another owner, damaged, oversized). */
export function decodeBriefState(
  raw: string | null,
  owner: string,
  workspace: string
): SavedBrief | null {
  if (!raw || raw.length > 100000 || !owner || !workspace) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object') return null;
    const item = value as Record<string, unknown>;
    if (
      (item.version !== 1 && item.version !== 2) ||
      item.owner !== owner ||
      item.workspace !== workspace
    )
      return null;
    if (typeof item.text !== 'string' || item.text.length > TEXT_MAX) return null;
    if (item.version === 1) return { text: item.text, chips: [] };
    if (!Array.isArray(item.chips) || item.chips.length > CHIPS_MAX) return null;
    const chips = item.chips.map(chipOf);
    if (chips.some((chip) => chip === null)) return null;
    return { text: item.text, chips: chips as SavedChip[] };
  } catch {
    return null;
  }
}

/** The saved text only (version 1 callers). */
export function decodeBrief(raw: string | null, owner: string, workspace: string): string | null {
  return decodeBriefState(raw, owner, workspace)?.text ?? null;
}
