import type { Metadata } from 'next';

/** A small flower, inline, so the tab icon costs no request to the server. */
const FLOWER = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="9" r="6" fill="#f7c6d9"/><circle cx="23" cy="16" r="6" fill="#f7c6d9"/><circle cx="16" cy="23" r="6" fill="#f7c6d9"/><circle cx="9" cy="16" r="6" fill="#f7c6d9"/><circle cx="16" cy="16" r="5" fill="#f2b705" stroke="#1f2a44" stroke-width="1.5"/></svg>`;

/**
 * The children's play area (D1, D12) references no site manifest and no server-hosted icons, so a visit requests
 * nothing outside /play and /_next/static (which the server then excludes from its telemetry by Referer).
 * Next always adds the root app/favicon.ico link as well; the inline SVG (sizes "any") is offered so browsers can use
 * it instead. Other pages keep the root metadata unchanged.
 */
export const metadata: Metadata = {
  manifest: null,
  icons: { icon: [{ url: `data:image/svg+xml,${encodeURIComponent(FLOWER)}`, type: 'image/svg+xml', sizes: 'any' }], apple: [], shortcut: [] }
};

export default function PlayLayout({ children }: { children: React.ReactNode }) {
  return children;
}
