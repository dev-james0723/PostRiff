/** Small, dependency-free formatting helpers shared by app pages. */

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

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
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', ...options }).format(new Date(epochSeconds * 1000));
}

export function formatDateTime(epochSeconds: number | null | undefined) {
  if (!epochSeconds) return '—';
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(epochSeconds * 1000)
  );
}

export function daysUntil(epochSeconds: number | null | undefined, now = Date.now() / 1000) {
  if (!epochSeconds) return null;
  return Math.ceil((epochSeconds - now) / 86400);
}

export function formatNumber(value: number) {
  return new Intl.NumberFormat('en').format(value);
}

export function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
