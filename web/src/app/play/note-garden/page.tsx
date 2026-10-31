import type { Metadata } from 'next';
import { NoteGarden } from '@/components/music-game/note-garden';

export const metadata: Metadata = {
  title: 'Note Garden',
  // Claims only what the route guarantees (privacy F3): pages are still served by a host that logs requests.
  description: 'A free music game for children aged 6 to 10: high and low, note names, beats, steps and skips. No sign-in, no ads, no tracking. Progress stays on this device.'
};

export default function NoteGardenPage() {
  return <NoteGarden />;
}
