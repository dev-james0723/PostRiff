/** Preserve provider identifiers and hierarchy. Unknown/missing numbers never become zero. */
export type NativeComment = { id: string; text: string; author: string; parentId: string | null; rootId: string | null };
const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const identifier = (value: unknown): string | null => typeof value === 'string' || typeof value === 'number' ? String(value) : null;

export function nativeComments(data: unknown): NativeComment[] {
  const root = record(data);
  const values = Array.isArray(root.data) ? root.data : Array.isArray(root.elements) ? root.elements : Array.isArray(root.items) ? root.items : [];
  const comments: NativeComment[] = [];
  for (const value of values) {
    const item = record(value), snippet = record(item.snippet);
    const top = record(snippet.topLevelComment);
    const comment = Object.keys(top).length ? top : item;
    const details = Object.keys(top).length ? record(top.snippet) : snippet;
    const message = record(comment.message);
    const id = identifier(comment.commentUrn) ?? identifier(comment.id);
    if (!id) continue;
    comments.push({ id, text: String(comment.text ?? message.text ?? details.textOriginal ?? details.textDisplay ?? ''),
      author: String(comment.username ?? record(comment.from).name ?? details.authorDisplayName ?? comment.actor ?? ''),
      parentId: identifier(comment.replied_to) ?? identifier(comment.parentComment) ?? identifier(comment.parent_id) ?? identifier(details.parentId),
      rootId: identifier(comment.root_post) ?? identifier(comment.object) ?? identifier(details.videoId) ?? identifier(snippet.videoId) });
    for (const child of Array.isArray(record(item.replies).comments) ? record(item.replies).comments as unknown[] : []) {
      const c = record(child), s = record(c.snippet), childId = identifier(c.id);
      if (childId) comments.push({ id: childId, text: String(s.textOriginal ?? s.textDisplay ?? ''), author: String(s.authorDisplayName ?? ''), parentId: identifier(s.parentId) ?? id, rootId: identifier(details.videoId) ?? identifier(snippet.videoId) });
    }
  }
  return comments;
}

export function nativeMetricRows(data: unknown): { name: string; value: number }[] {
  const rows: { name: string; value: number }[] = [];
  function visit(value: unknown, path: string, depth: number) {
    if (depth > 8 || rows.length >= 200) return;
    if (typeof value === 'number' && Number.isFinite(value)) { rows.push({ name: path, value }); return; }
    if (Array.isArray(value)) { value.slice(0, 50).forEach((item, index) => visit(item, `${path}[${index}]`, depth + 1)); return; }
    const obj = record(value);
    const name = typeof obj.name === 'string' ? obj.name : path;
    for (const [key, child] of Object.entries(obj)) {
      if (['id', 'timestamp', 'start', 'end', 'startTime', 'endTime'].includes(key)) continue;
      visit(child, `${name}${name ? '.' : ''}${key}`, depth + 1);
    }
  }
  visit(data, '', 0); return rows;
}
