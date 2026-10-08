/**
 * Browser performance marks for G17 (no source text, no data in details; one mark per artifact/revision):
 *   rafii-genui:first-component  {artifactId, revision}  first non-skeleton component rendered
 *   rafii-genui:ready            {artifactId, revision}  the server-accepted canonical source is rendered
 */
const marked = new Set<string>();
const MAX_REMEMBERED = 500;

function mark(name: string, key: string, detail: Record<string, string | number>): void {
  if (marked.has(key)) return;
  if (marked.size > MAX_REMEMBERED) marked.clear();
  marked.add(key);
  try {
    if (typeof performance !== 'undefined' && typeof performance.mark === 'function') performance.mark(name, { detail });
  } catch {
    // Marks are evidence only; never let them affect rendering.
  }
}

export function markFirstComponent(artifactId: string, revision: number): void {
  mark('rafii-genui:first-component', `first:${artifactId}`, { artifactId, revision });
}

export function markReady(artifactId: string, revision: number): void {
  mark('rafii-genui:ready', `ready:${artifactId}:${revision}`, { artifactId, revision });
}
