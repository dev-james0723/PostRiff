/** Text helpers shared by the export parsers. Pure; nothing here throws on odd input. */

export type Json = Record<string, unknown>;

export function isRecord(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** `undefined` for text that is not JSON, so a caller can tell "not JSON" from the JSON value `null`. */
export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

const STRICT_UTF8 = new TextDecoder('utf-8', { fatal: true });

/**
 * Meta's exporter writes each UTF-8 byte as its own `\u00XX` escape, so 🙂 arrives as four Latin-1 characters.
 * A string is repaired only when every character is U+00FF or below and the bytes are valid UTF-8; real text
 * (anything above U+00FF) and genuine Latin-1 are returned unchanged.
 */
export function repairMojibake(value: string): string {
  let high = false;
  for (let index = 0; index < value.length; index++) {
    const code = value.charCodeAt(index);
    if (code > 0xff) return value;
    if (code > 0x7f) high = true;
  }
  if (!high) return value;
  try {
    return STRICT_UTF8.decode(Uint8Array.from(value, (char) => char.charCodeAt(0)));
  } catch {
    return value;
  }
}

/** A file's bytes as text: UTF-8 when valid (byte order mark dropped), otherwise Windows-1252, which older LinkedIn exports use. */
export function decodeBytes(bytes: Uint8Array): string {
  try {
    return STRICT_UTF8.decode(bytes);
  } catch {
    return new TextDecoder('windows-1252').decode(bytes);
  }
}

const NAMED_ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };

/** One pass, so `&amp;lt;` becomes the text `&lt;` and not a tag. */
export function decodeEntities(text: string): string {
  return text.replace(/&(#x[0-9a-f]{1,6}|#\d{1,7}|[a-z]{2,6});/gi, (whole, body: string) => {
    if (body[0] !== '#') return NAMED_ENTITIES[body.toLowerCase()] ?? whole;
    const code = body[1].toLowerCase() === 'x' ? Number.parseInt(body.slice(2), 16) : Number.parseInt(body.slice(1), 10);
    const valid = Number.isFinite(code) && code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff);
    return valid ? String.fromCodePoint(code) : whole;
  });
}

/** Post HTML to plain text: paragraphs and line breaks survive, every other tag is dropped. The result is only ever shown as text. */
export function stripHtml(html: string): string {
  const text = html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>\s*<p[^>]*>/gi, '\n\n')
    .replace(/<\/(?:p|div|li|blockquote|h[1-6])>/gi, '\n')
    .replace(/<[^>]*>/g, '');
  return decodeEntities(text)
    .replace(/ /g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** Epoch seconds (or milliseconds) to ISO 8601; `undefined` when the export gave no usable time. */
export function isoFromEpoch(value: unknown): string | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return undefined;
  const date = new Date(value < 1e12 ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

export function isoFromText(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? new Date(ms).toISOString() : undefined;
}

/**
 * A repeatable id for exports that carry none (Instagram, Facebook, Threads), so a second upload of the same file
 * lands on the same records. It is derived from the post's time and text, and is not a platform id.
 */
export function stableId(provider: string, seconds: number | undefined, text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let index = 0; index < text.length; index++) {
    const code = text.charCodeAt(index);
    h1 = Math.imul(h1 ^ code, 2654435761);
    h2 = Math.imul(h2 ^ code, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  const hash = (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
  return `export:${provider}:${seconds === undefined ? 0 : Math.round(seconds)}:${hash}`;
}

/** Characters as a person counts them (code points), which is how the 20,000-character limit on a post is defined. */
export function countChars(text: string): number {
  let count = 0;
  for (let index = 0; index < text.length; index++) {
    const code = text.charCodeAt(index);
    // A high surrogate followed by a low one is one character; a lone surrogate counts as one, as string iteration does.
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) index++;
    }
    count++;
  }
  return count;
}
