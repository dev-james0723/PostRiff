import type { YouTubeResource } from '@/lib/youtube/types';

/** Row-sized first, then other supplied sizes; never synthesize a URL from an ID. */
export function youtubeThumbnailUrls(resource: YouTubeResource): string[] {
  const thumbnails = resource.snippet?.thumbnails;
  if (!thumbnails) return [];

  const urls: string[] = [];
  for (const size of ['medium', 'high', 'standard', 'maxres', 'default'] as const) {
    const suppliedUrl = thumbnails[size]?.url;
    const url = typeof suppliedUrl === 'string' ? suppliedUrl.trim() : '';
    if (!url || urls.includes(url)) continue;
    try {
      // API thumbnails are absolute HTTPS URLs. Ignore malformed or unsafe schemes.
      if (new URL(url).protocol === 'https:') urls.push(url);
    } catch {
      // A malformed provider image must not prevent the resource from being selected.
    }
  }
  return urls;
}
