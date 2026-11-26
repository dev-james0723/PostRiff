/**
 * Facebook export, posts file:
 *   posts/your_posts_1.json (before 2024)  ->  your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json
 * The writing is in `data[].post`. `title` is a sentence Facebook writes ("… updated their status"), never the post.
 */
import { emptyExport } from './meta';
import { asString, isRecord, isoFromEpoch, repairMojibake, stableId } from './text';
import type { ExportItem, ParsedExport } from './types';

export function facebookLayout(name: string): string {
  return /your_posts__check_ins__photos_and_videos_\d+\.json$/i.test(name) ? 'activity-posts' : 'posts';
}

export function looksLikeFacebook(json: unknown): boolean {
  return (
    Array.isArray(json) &&
    json.slice(0, 20).some((entry) => isRecord(entry) && typeof entry.timestamp === 'number' && !Array.isArray(entry.media) && (Array.isArray(entry.data) || Array.isArray(entry.attachments) || typeof entry.title === 'string'))
  );
}

export function parseFacebook(json: unknown, layout: string): ParsedExport {
  const result = emptyExport('facebook', layout);
  if (!Array.isArray(json)) return { ...result, notes: ['unknown_shape'] };
  for (const entry of json) {
    if (!isRecord(entry)) {
      result.skipped.unsupported++;
      continue;
    }
    const data = Array.isArray(entry.data) ? entry.data.filter(isRecord) : [];
    const text = repairMojibake(asString(data.find((part) => typeof part.post === 'string')?.post)).trim();
    if (!text) {
      // A photo, a check-in or a shared link with nothing written.
      result.skipped.empty++;
      continue;
    }
    const seconds = typeof entry.timestamp === 'number' && Number.isFinite(entry.timestamp) && entry.timestamp > 0 ? entry.timestamp : undefined;
    const item: ExportItem = { externalId: stableId('facebook', seconds, text), text };
    const publishedAt = isoFromEpoch(seconds);
    if (publishedAt) item.publishedAt = publishedAt;
    result.items.push(item);
  }
  return result;
}
