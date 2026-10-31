import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { isPlayEnabled } from '@/lib/play-launch';

/** A small flower, inline, so the tab icon costs no request to the server. */
const FLOWER = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="9" r="6" fill="#f7c6d9"/><circle cx="23" cy="16" r="6" fill="#f7c6d9"/><circle cx="16" cy="23" r="6" fill="#f7c6d9"/><circle cx="9" cy="16" r="6" fill="#f7c6d9"/><circle cx="16" cy="16" r="5" fill="#f2b705" stroke="#1f2a44" stroke-width="1.5"/></svg>`;

/**
 * The children's play area (D12) replaces the root's /icon and /apple-icon links with an inline SVG, so a /play page
 * points at two fewer server-hosted files. Next still adds the root app/manifest.ts and app/favicon.ico links on every
 * page (a segment cannot remove those); real browsers fetch them with a same-host /play Referer, which the server
 * excludes from its telemetry. Other pages keep the root metadata unchanged.
 */
export const metadata: Metadata = {
  icons: { icon: [{ url: `data:image/svg+xml,${encodeURIComponent(FLOWER)}`, type: 'image/svg+xml', sizes: 'any' }], apple: [], shortcut: [] }
};

export default function PlayLayout({ children }: { children: React.ReactNode }) {
  if (!isPlayEnabled()) notFound(); // launch switch: off until the children's privacy notice is approved
  return children;
}
