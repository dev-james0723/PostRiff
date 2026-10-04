import packs from './history-import-copy.json';

export type HistoryImportCopy = { [K in keyof typeof packs.en]: string };

/** Rafii display-preference locales; region aliases share a complete pack, never partial strings. */
export function historyImportCopy(locale: string): { copy: HistoryImportCopy; lang: string; fallback: boolean } {
  const tag = locale.replaceAll('_', '-').toLowerCase();
  let lang = tag.split('-')[0];
  if (lang === 'zh' || lang === 'yue') {
    lang = /hans|-(cn|sg)(-|$)/.test(tag) ? 'zh-Hans' : 'zh-Hant';
  } else if (lang === 'pt') lang = 'pt-BR';
  const pack = packs[lang as keyof typeof packs];
  return { copy: pack ?? packs.en, lang: pack ? lang : 'en', fallback: !pack };
}

export function importCopyValues(text: string, values: Record<string, string | number>, locale: string) {
  let numbers: Intl.NumberFormat;
  try { numbers = new Intl.NumberFormat(locale); } catch { numbers = new Intl.NumberFormat('en'); }
  return text.replace(/\{([a-z]+)\}/g, (placeholder, key: string) => {
    const value = values[key];
    return typeof value === 'number' ? numbers.format(value) : value ?? placeholder;
  });
}
