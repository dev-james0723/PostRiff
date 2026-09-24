/**
 * Render-time preparation of the library SVGs (DNA v8 §14.4, §14.5). The archive bytes stay untouched
 * (`artwork-markup.ts`); this rewrites a copy per rendered instance so that
 *
 *   - gradient, filter, mask and clip ids are unique when the same asset appears twice on a page
 *     (`id="paper"` → `id="<prefix>-paper"`, and every `url(#…)` / `href="#…"` reference with it);
 *   - the wrapper element carries the accessible name, so the root loses `role`, `aria-label` and its
 *     `<title>` (which would otherwise double-announce and show as a native hover tooltip);
 *   - the large illustration's motif group and its last accent circle get motion classes, and the
 *     compact glyph keeps its `glyph-motion` group, for the CSS loops `SemanticIllustration` owns.
 */
import type { ArtworkSize } from './artwork';

export const ART_MOTIF_CLASS = 'rafii-art-motif';
export const ART_ACCENT_CLASS = 'rafii-art-accent';

const ID_ATTR = /\bid="([^"]+)"/g;
const URL_REF = /url\(#([^)]+)\)/g;
const HREF_REF = /\b(xlink:href|href)="#([^"]+)"/g;
const TITLE = /<title>[\s\S]*?<\/title>/;
const ROOT = /^(\s*<svg\b)([^>]*)>/;

export function namespaceIds(markup: string, prefix: string): string {
  return markup
    .replace(ID_ATTR, (_, id: string) => `id="${prefix}-${id}"`)
    .replace(URL_REF, (_, id: string) => `url(#${prefix}-${id})`)
    .replace(HREF_REF, (_, attr: string, id: string) => `${attr}="#${prefix}-${id}"`);
}

/** Strip the root's own semantics: the wrapper decides whether the picture is named or decorative. */
function neutralizeRoot(markup: string): string {
  return markup.replace(TITLE, '').replace(ROOT, (_, open: string, attrs: string) => {
    const cleaned = attrs
      .replace(/\s+role="[^"]*"/g, '')
      .replace(/\s+aria-label="[^"]*"/g, '')
      .replace(/\s+aria-hidden="[^"]*"/g, '')
      .replace(/\s+focusable="[^"]*"/g, '');
    return `${open}${cleaned} aria-hidden="true" focusable="false">`;
  });
}

/** Tag the grayscale motif group and wrap its last accent circle so the two loops can run independently. */
function addLargeMotion(markup: string): string {
  const withMotif = markup.replace('<g style="filter:grayscale(1)">', `<g class="${ART_MOTIF_CLASS}" style="filter:grayscale(1)">`);
  const start = withMotif.indexOf(`<g class="${ART_MOTIF_CLASS}"`);
  if (start < 0) return withMotif;
  const end = withMotif.lastIndexOf('</g></svg>');
  if (end < start) return withMotif;
  const body = withMotif.slice(start, end);
  const circle = body.lastIndexOf('<circle ');
  if (circle < 0) return withMotif;
  const close = body.indexOf('/>', circle);
  if (close < 0) return withMotif;
  const wrapped = `${body.slice(0, circle)}<g class="${ART_ACCENT_CLASS}">${body.slice(circle, close + 2)}</g>${body.slice(close + 2)}`;
  return withMotif.slice(0, start) + wrapped + withMotif.slice(end);
}

export interface PrepareOptions {
  /** Unique per rendered instance; letters, digits, `-` and `_` only. */
  prefix: string;
  size: ArtworkSize;
}

/** The markup for one rendered instance. Pure: the same input always yields the same output. */
export function prepareArtwork(markup: string, { prefix, size }: PrepareOptions): string {
  const safe = prefix.replace(/[^A-Za-z0-9_-]/g, '');
  const scoped = neutralizeRoot(namespaceIds(markup, safe || 'art'));
  return size === 'large' ? addLargeMotion(scoped) : scoped;
}
