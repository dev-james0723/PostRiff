/** Small, dependency-free formatting helpers shared by app pages. */

/*
 * Person-level defaults, set by `PreferencesProvider` before the app renders: the zone times are
 * shown in and the language dates and numbers are written with. Browser defaults until then.
 * Module state rather than context so the many call sites keep their plain-function signatures.
 */
let locale = 'en';
let timeZone: string | undefined;
let rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });

function usable(construct: () => unknown) {
  try {
    construct();
    return true;
  } catch {
    return false;
  }
}

export function setTimeDefaults(next: { timeZone?: string; locale?: string }) {
  const nextLocale = next.locale && usable(() => new Intl.NumberFormat(next.locale)) ? next.locale : 'en';
  const nextZone = next.timeZone && usable(() => new Intl.DateTimeFormat('en', { timeZone: next.timeZone })) ? next.timeZone : undefined;
  if (nextLocale === locale && nextZone === timeZone) return;
  locale = nextLocale;
  timeZone = nextZone;
  rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
}

export function timeDefaults() {
  return { locale, timeZone };
}

/** "3 hours ago", "in 2 days" from an epoch in seconds. */
export function relativeTime(epochSeconds: number | null | undefined, now = Date.now() / 1000) {
  if (!epochSeconds) return '—';
  const diff = epochSeconds - now;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), 'second');
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day');
  return rtf.format(Math.round(diff / (86400 * 30)), 'month');
}

export function formatDate(epochSeconds: number | null | undefined, options: Intl.DateTimeFormatOptions = {}) {
  if (!epochSeconds) return '—';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone, ...options }).format(new Date(epochSeconds * 1000));
}

export function formatDateTime(epochSeconds: number | null | undefined) {
  if (!epochSeconds) return '—';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(
    new Date(epochSeconds * 1000)
  );
}

export function daysUntil(epochSeconds: number | null | undefined, now = Date.now() / 1000) {
  if (!epochSeconds) return null;
  return Math.ceil((epochSeconds - now) / 86400);
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat(locale).format(value);
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
