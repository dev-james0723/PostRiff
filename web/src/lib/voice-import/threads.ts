/**
 * Threads export: your_instagram_activity/threads/threads_and_replies.json, `text_post_app_text_posts[]`.
 * The file mixes posts and replies without marking them, so no kind is set.
 */
import { collectMediaPosts, emptyExport } from './meta';
import { isRecord } from './text';
import type { ParsedExport } from './types';

export const THREADS_LAYOUT = 'threads-and-replies';

export function looksLikeThreads(json: unknown): boolean {
  return isRecord(json) && Array.isArray(json.text_post_app_text_posts);
}

export function parseThreads(json: unknown): ParsedExport {
  if (!isRecord(json) || !Array.isArray(json.text_post_app_text_posts)) return emptyExport('threads', THREADS_LAYOUT, ['unknown_shape']);
  return collectMediaPosts(emptyExport('threads', THREADS_LAYOUT), json.text_post_app_text_posts);
}
