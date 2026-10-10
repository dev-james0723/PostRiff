/** Only same-origin route changes are intercepted. Hash navigation, downloads and external/new tabs keep native behavior. */
export function departureHref(href: string, currentHref: string, target = '', download = false): string | null {
  if (download || (target && target !== '_self')) return null;
  try {
    const current = new URL(currentHref);
    const next = new URL(href, current);
    if (!['http:', 'https:'].includes(next.protocol) || next.origin !== current.origin || next.pathname === current.pathname) return null;
    return next.pathname + next.search + next.hash;
  } catch { return null; }
}
