/** Session-only, user/workspace-scoped input recovery. Never restores permissions. */
export const briefStorageKey = (owner: string, workspace: string) =>
  `rafii.brief.${encodeURIComponent(owner)}.${encodeURIComponent(workspace)}`;

export function encodeBrief(owner: string, workspace: string, text: string): string {
  if (!owner || !workspace || typeof text !== 'string' || text.length > 20000) {
    throw new Error('Invalid brief.');
  }
  return JSON.stringify({ version: 1, owner, workspace, text });
}

export function decodeBrief(raw: string | null, owner: string, workspace: string): string | null {
  if (!raw || raw.length > 100000 || !owner || !workspace) return null;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object') return null;
    const item = value as Record<string, unknown>;
    if (item.version !== 1 || item.owner !== owner || item.workspace !== workspace || typeof item.text !== 'string' || item.text.length > 20000) return null;
    return item.text;
  } catch {
    return null;
  }
}
