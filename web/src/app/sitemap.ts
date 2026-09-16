import type { MetadataRoute } from 'next';
import { channels } from '@/config/channels';
import { DOCS } from '@/content/docs';
import { siteConfig } from '@/config/site';

const STATIC = ['/', '/pricing', '/channels', '/docs', '/changelog', '/status', '/contact', '/security', '/privacy', '/terms', '/data-deletion'];

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();
  return [
    ...STATIC.map((path) => ({ url: `${siteConfig.url}${path}`, lastModified: now, changeFrequency: 'weekly' as const, priority: path === '/' ? 1 : 0.7 })),
    ...channels.map((c) => ({ url: `${siteConfig.url}/channels/${c.slug}`, lastModified: now, changeFrequency: 'monthly' as const, priority: 0.6 })),
    ...DOCS.map((d) => ({ url: `${siteConfig.url}/docs/${d.slug}`, lastModified: now, changeFrequency: 'monthly' as const, priority: 0.5 }))
  ];
}
