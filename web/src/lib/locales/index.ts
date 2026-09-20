import data from './catalogue.generated.json';
import { createLocales, type Catalogue, type LocaleEntry } from './core';

export type { Catalogue, LocaleEntry, LocaleTag, MessageLanguages, NamedLanguage, SearchResult } from './core';
export { fold, PLATFORM_WORDS } from './core';

/** The shared catalogue (built by scripts/build_locale_catalogue.mjs, identical to the server's). */
export const locales = createLocales(data as Catalogue);

/** Flags are emoji text. Windows has no flag glyphs, so Noto Color Emoji is the fallback. */
export const FLAG_FONT = '"Apple Color Emoji", "Noto Color Emoji", "Segoe UI Emoji", sans-serif';

const GLYPH_FONTS: Record<NonNullable<LocaleEntry['glyphs']>, string> = {
  hk: '"PingFang HK", "Noto Sans HK", "Microsoft JhengHei"',
  tw: '"PingFang TC", "Noto Sans TC", "Microsoft JhengHei"',
  cn: '"PingFang SC", "Noto Sans SC", "Microsoft YaHei"',
  ja: '"Hiragino Sans", "Noto Sans JP", "Yu Gothic"',
  ko: '"Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic"',
  ar: '"Geeza Pro", "Noto Sans Arabic"',
  ur: '"Noto Nastaliq Urdu", "Geeza Pro", "Noto Sans Arabic"',
  he: '"Arial Hebrew", "Noto Sans Hebrew"'
};

/** The regional CJK (or script) face for text in a language; the same font file renders HK and TW glyphs differently only by `lang`. */
export function glyphFontFamily(glyphs: LocaleEntry['glyphs']): string | undefined {
  return glyphs ? `var(--font-sans), ${GLYPH_FONTS[glyphs]}, sans-serif` : undefined;
}

/** "🇭🇰 繁體中文（香港）": a language as plain text, for titles and select values. */
export function languageLabel(value: unknown): string {
  const entry = locales.entry(value);
  return entry ? `${entry.flag} ${entry.native}` : typeof value === 'string' ? value : '';
}

/** Characters as the server counts them (code points), so a draft over the limit reads the same everywhere. */
export function textLength(text: string): number {
  return Array.from(text ?? '').length;
}

/** Attributes for any element that shows text written in a language. */
export function textAttributes(value: unknown) {
  const entry = locales.entry(value);
  return {
    lang: entry?.tag,
    dir: 'auto' as const,
    style: entry?.glyphs ? { fontFamily: glyphFontFamily(entry.glyphs) } : undefined
  };
}
