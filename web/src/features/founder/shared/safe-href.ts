/**
 * Links an answer or a payload may carry are followed only inside the founder admin: a same-origin `/founder/…`
 * path with an optional query and fragment. Everything else (absolute URLs, protocol tricks, other app areas)
 * renders as plain text, mirroring the site agent's route-manifest guard.
 */
export function founderSafeHref(href: string | null | undefined): string | null {
  if (!href || typeof href !== 'string') return null;
  if (!href.startsWith('/founder') || href.startsWith('//') || /[\s\\<>]/.test(href)) return null;
  const rest = href.slice('/founder'.length);
  if (rest && !/^[/?#]/.test(rest)) return null;
  if (/[?&][^=&]*=[^&]*(javascript|data):/i.test(href)) return null;
  return href;
}
