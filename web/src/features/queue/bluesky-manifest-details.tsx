import type { Manifest } from '@/lib/api/types';

export function BlueskyManifestDetails({ manifest }: { manifest: Manifest }) {
  if (manifest.platform !== 'Bluesky' || !manifest.media.length) return null;
  return <ol className='flex flex-col gap-1 text-sm' aria-label='Bluesky image descriptions'>
    {manifest.media.map((image, index) => <li key={image.id}>Image {index + 1}: {image.alt}</li>)}
  </ol>;
}
