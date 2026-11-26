/**
 * LinkedIn export: Shares.csv with the columns Date, ShareLink, ShareCommentary, SharedUrl, MediaUrl, Visibility.
 * A row with no commentary is a reshare with nothing written and counts as empty.
 */
import { parseCsv } from './csv';
import { emptyExport } from './meta';
import { isoFromText, stableId } from './text';
import type { ExportItem, ParsedExport } from './types';

const LAYOUT = 'shares';

export function looksLikeLinkedIn(text: string): boolean {
  return /(^|,)\s*"?ShareCommentary"?\s*(,|\r?\n|$)/i.test(text.slice(0, 2000).split(/\r?\n/)[0] ?? '');
}

/** The post URN inside ShareLink (`urn:li:share:…`, `urn:li:ugcPost:…`, `urn:li:activity:…`): the id LinkedIn itself uses for the post. */
function postUrn(link: string): string | null {
  let decoded = link;
  try {
    decoded = decodeURIComponent(link);
  } catch {
    /* keep the link as written */
  }
  return /urn:li:(?:share|ugcPost|activity):\d{5,30}/.exec(decoded)?.[0] ?? null;
}

/** "2024-03-01 14:22:10". The export does not state a zone; it is read as UTC. */
function shareDate(value: string): string | undefined {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value.trim());
  if (!match) return isoFromText(value);
  const ms = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6] ?? 0));
  return Number.isFinite(ms) ? new Date(ms).toISOString() : undefined;
}

export function parseLinkedIn(text: string): ParsedExport {
  const result = emptyExport('linkedin', LAYOUT);
  const [header, ...rows] = parseCsv(text);
  const columns = (header ?? []).map((name) => name.trim().toLowerCase());
  const commentary = columns.indexOf('sharecommentary');
  if (commentary < 0) return { ...result, notes: ['unknown_shape'] };
  const date = columns.indexOf('date');
  const link = columns.indexOf('sharelink');
  for (const row of rows) {
    const body = (row[commentary] ?? '').trim();
    if (!body) {
      result.skipped.empty++;
      continue;
    }
    const publishedAt = date >= 0 ? shareDate(row[date] ?? '') : undefined;
    const url = link >= 0 ? (row[link] ?? '').trim() : '';
    const item: ExportItem = { externalId: postUrn(url) ?? stableId('linkedin', publishedAt ? Date.parse(publishedAt) / 1000 : undefined, body), text: body };
    if (publishedAt) item.publishedAt = publishedAt;
    if (/^https:\/\/([a-z0-9-]+\.)*linkedin\.com\//i.test(url)) item.permalink = url;
    result.items.push(item);
  }
  return result;
}
