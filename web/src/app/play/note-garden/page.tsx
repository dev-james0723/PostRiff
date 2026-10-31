import type { Metadata } from 'next';
import { NoteGarden } from '@/components/music-game/note-garden';

export const metadata: Metadata = {
  title: 'Note Garden',
  description: 'A free music game for children aged 6 to 10: high and low, note names, beats, steps and skips. No sign-in, nothing sent anywhere.'
};

export default function NoteGardenPage() {
  return <NoteGarden />;
}
