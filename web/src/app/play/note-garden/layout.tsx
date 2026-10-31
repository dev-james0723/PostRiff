import type { Viewport } from 'next';

/** Public children's game: no sign-in (src/proxy.ts only gates /app and /founder), light theme whatever the site theme. */
export const viewport: Viewport = {
  themeColor: '#fff8e7',
  colorScheme: 'light'
};

export default function NoteGardenLayout({ children }: { children: React.ReactNode }) {
  return children;
}
