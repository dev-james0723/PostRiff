/** The post shape Instagram and Threads exports share, and an empty result for any parser to start from. */
import { asString, isRecord, isoFromEpoch, repairMojibake, stableId } from './text';
import type { ExportItem, ExportKind, ExportNote, ExportProvider, ParsedExport } from './types';

export function emptyExport(provider: ExportProvider, layout: string, notes: ExportNote[] = []): ParsedExport {
  return { provider, layout, items: [], skipped: { unsupported: 0, empty: 0 }, local: { notPublic: 0, reposts: 0 }, notes };
}

function seconds(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
}

/**
 * One `{media: [{uri, creation_timestamp, title}], title?, creation_timestamp?}` entry. The caption is the
 * post-level title, or the first media item's title when the post has none; the same order applies to the time.
 * `null` means the entry is not a post at all.
 */
export function readMediaPost(entry: unknown): { text: string; seconds?: number } | null {
  if (!isRecord(entry)) return null;
  const media = Array.isArray(entry.media) ? entry.media.filter(isRecord) : [];
  if (!media.length && typeof entry.title !== 'string') return null;
  const title = asString(entry.title).trim() ? asString(entry.title) : asString(media[0]?.title);
  return { text: repairMojibake(title).trim(), seconds: seconds(entry.creation_timestamp) ?? seconds(media[0]?.creation_timestamp) };
}

/** Adds each entry as a post, an empty caption or an unreadable entry. */
export function collectMediaPosts(result: ParsedExport, entries: unknown[], kind?: ExportKind): ParsedExport {
  for (const entry of entries) {
    const post = readMediaPost(entry);
    if (!post) result.skipped.unsupported++;
    else if (!post.text) result.skipped.empty++;
    else {
      const item: ExportItem = { externalId: stableId(result.provider, post.seconds, post.text), text: post.text };
      const publishedAt = isoFromEpoch(post.seconds);
      if (publishedAt) item.publishedAt = publishedAt;
      if (kind) item.kind = kind;
      result.items.push(item);
    }
  }
  return result;
}
