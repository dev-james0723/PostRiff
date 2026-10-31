import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { NoteGarden } from '@/components/music-game/note-garden';
import { isPlayEnabled } from '@/lib/play-launch';

/** Resolved even when the play layout returns a 404, so it says nothing while the launch switch is off. */
export function generateMetadata(): Metadata {
  if (!isPlayEnabled()) return {};
  return {
    title: 'Note Garden',
    // Claims only what the route guarantees (privacy F3): pages are still served by a host that logs requests.
    description: 'A free music game for children aged 6 to 10: high and low, note names, beats, steps and skips. No sign-in, no ads, no tracking. Progress stays on this device.'
  };
}

export default function NoteGardenPage() {
  // Also checked here: Next renders the page alongside the play layout, so the layout's 404 alone would still emit the
  // game's client reference (component chunks) in the RSC payload.
  if (!isPlayEnabled()) notFound();
  return <NoteGarden />;
}
