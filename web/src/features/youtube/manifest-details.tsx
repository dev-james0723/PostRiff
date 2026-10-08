'use client';

import type { Manifest } from '@/lib/api/types';

function show(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.map(show).join(', ');
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '';
}
/** Exact frozen creator choices, alongside the shared campaign approval. */
export function YouTubeManifestDetails({ manifest }: { manifest: Manifest }) {
  if (manifest.platform !== 'YouTube' || !manifest.publishOptions) return null;
  const options = manifest.publishOptions;
  const labels: Record<string, string> = {
    title: 'Video title',
    description: 'Description',
    mode: 'Composer format candidate',
    privacyStatus: 'Visibility',
    publicationMode: 'Publication mode',
    publishAt: 'Native YouTube publication time',
    categoryId: 'Category',
    tags: 'Tags',
    defaultLanguage: 'Metadata language',
    defaultAudioLanguage: 'Audio language',
    madeForKids: 'Made for Kids',
    containsSyntheticMedia: 'Realistic altered or synthetic media',
    notifySubscribers: 'Notify subscribers',
    license: 'License',
    embeddable: 'Allow embedding',
    publicStatsViewable: 'Public statistics',
    recordingDate: 'Recording date',
    thumbnailAssetId: 'Thumbnail',
    playlistIds: 'Playlists',
    podcastPlaylistId: 'Podcast show'
  };
  const captions = Array.isArray(options.captionTracks)
    ? (options.captionTracks as Record<string, unknown>[])
    : [];
  const localizations =
    options.localizations && typeof options.localizations === 'object'
      ? (options.localizations as Record<string, Record<string, unknown>>)
      : {};
  return (
    <section
      aria-label='Exact YouTube publishing details'
      className='grid gap-3 rounded-md border p-3'
    >
      <p className='text-sm font-medium'>Exact YouTube publishing choices</p>
      <p className='text-muted-foreground text-xs'>
        Upload begins privately. Processing and creator attachments are verified before the approved
        visibility or native schedule is applied. Shorts classification remains a YouTube decision.
      </p>
      <dl className='grid gap-2 text-sm'>
        {Object.entries(labels)
          .filter(([key]) => key in options)
          .map(([key, label]) => (
            <div key={key}>
              <dt className='text-muted-foreground text-xs'>{label}</dt>
              <dd className='whitespace-pre-wrap break-words'>{show(options[key])}</dd>
            </div>
          ))}
      </dl>
      {Object.entries(localizations).map(([language, text]) => (
        <details key={language}>
          <summary>Translation: {language}</summary>
          <p className='whitespace-pre-wrap text-sm'>{show(text.title)}</p>
          <p className='whitespace-pre-wrap text-sm'>{show(text.description)}</p>
        </details>
      ))}
      {captions.map((track, index) => (
        <details key={index}>
          <summary>
            Caption {index + 1}: {show(track.name)} · {show(track.language)} ·{' '}
            {track.isDraft ? 'Draft' : 'Visible when served'}
          </summary>
          <pre className='max-h-60 overflow-auto whitespace-pre-wrap text-xs'>
            {show(track.text)}
          </pre>
        </details>
      ))}
    </section>
  );
}
