import packs from './health-copy.json';

export type HealthCopyKey = keyof typeof packs.en;
export type HealthCopy = { [K in HealthCopyKey]: string };
export type HealthLanguage = 'en' | 'zh-Hant' | 'zh-Hans';

/**
 * Connection Health copy in English, Traditional Chinese and Simplified Chinese. A display preference picks one
 * complete pack (region tags share it); any other language reads English, never a mix of partial strings.
 */
export function healthCopy(locale: string): { copy: HealthCopy; lang: HealthLanguage } {
  const tag = (locale || 'en').replaceAll('_', '-').toLowerCase();
  const base = tag.split('-')[0];
  if (base === 'zh' || base === 'yue') {
    const lang: HealthLanguage = /hans|-(cn|sg)(-|$)/.test(tag) ? 'zh-Hans' : 'zh-Hant';
    return { copy: packs[lang], lang };
  }
  return { copy: packs.en, lang: 'en' };
}

/** `{name}` placeholders filled from values; an unknown placeholder stays visible rather than vanishing. */
export function fill(text: string, values: Record<string, string | number> = {}): string {
  return text.replace(/\{([a-zA-Z]+)\}/g, (placeholder, key: string) => {
    const value = values[key];
    return value === undefined || value === null ? placeholder : String(value);
  });
}

/** The copy for a key that is built at run time (a state, reason or status); falls back to `fallback`, never to a raw key. */
export function copyFor(copy: HealthCopy, key: string, fallback: HealthCopyKey): string {
  return (copy as Record<string, string>)[key] ?? copy[fallback];
}
