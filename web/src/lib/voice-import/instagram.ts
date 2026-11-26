/**
 * Instagram export, posts file. Three layout generations hold the same array:
 *   content/posts_1.json  ->  your_instagram_activity/content/posts_1.json  ->  your_instagram_activity/media/posts_1.json (2025)
 * The export carries no post id or link, so neither is invented.
 */
import { collectMediaPosts, emptyExport } from './meta';
import { isRecord } from './text';
import type { ParsedExport } from './types';

export function instagramLayout(name: string): string {
  const path = name.replace(/\\/g, '/').toLowerCase();
  if (/your_instagram_activity\/media\/posts_\d+\.json$/.test(path)) return 'activity-media';
  if (/your_instagram_activity\/content\/posts_\d+\.json$/.test(path)) return 'activity-content';
  if (/(^|\/)content\/posts_\d+\.json$/.test(path)) return 'content';
  return 'posts';
}

/** An array in which some entry has a `media` list: checked on the first entries only, the file can be large. */
export function looksLikeInstagram(json: unknown): boolean {
  return Array.isArray(json) && json.slice(0, 20).some((entry) => isRecord(entry) && Array.isArray(entry.media));
}

export function parseInstagram(json: unknown, layout: string): ParsedExport {
  if (!Array.isArray(json)) return emptyExport('instagram', layout, ['unknown_shape']);
  // A feed post is the account's own post, never a reply or a repost.
  return collectMediaPosts(emptyExport('instagram', layout), json, 'original');
}
