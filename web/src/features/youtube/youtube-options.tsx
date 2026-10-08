'use client';

import { useEffect, useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSnapshot } from '@/lib/api/hooks';
import type { Asset } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { YouTubeResource } from '@/lib/youtube/types';

const control = 'border-input bg-background w-full rounded-md border px-3 py-2 text-sm';
interface Props {
  channelId: string;
  asset?: Asset;
  text: string;
  onChange: (options: Record<string, unknown> | null) => void;
}

export function YouTubeOptions({ channelId, asset, text, onChange }: Props) {
  const { api, workspaceId } = useWorkspaceApi();
  const uid = useId();
  const [mode, setMode] = useState<'video' | 'short'>('video');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState(text);
  const [privacy, setPrivacy] = useState('');
  const [publicationMode, setPublicationMode] = useState<'now' | 'schedule'>('now');
  const [audience, setAudience] = useState('');
  const [synthetic, setSynthetic] = useState('');
  const [tags, setTags] = useState('');
  const [category, setCategory] = useState('22');
  const [language, setLanguage] = useState('');
  const [audioLanguage, setAudioLanguage] = useState('');
  const [license, setLicense] = useState('youtube');
  const [embeddable, setEmbeddable] = useState(true);
  const [publicStats, setPublicStats] = useState(true);
  const [recordingDate, setRecordingDate] = useState('');
  const [notify, setNotify] = useState(true);
  const [thumbnail, setThumbnail] = useState('');
  const [playlists, setPlaylists] = useState<string[]>([]);
  const [caption, setCaption] = useState('');
  const [fileError, setFileError] = useState('');
  const [captionLanguage, setCaptionLanguage] = useState('en');
  const [captionName, setCaptionName] = useState('');
  const [captionDraft, setCaptionDraft] = useState(false);
  const [translations, setTranslations] = useState<
    { language: string; title: string; description: string }[]
  >([]);
  const overview = useQuery({
    queryKey: ['youtube', workspaceId, channelId],
    queryFn: () => api.youtubeOverview(workspaceId, channelId),
    enabled: Boolean(channelId),
    retry: false,
    staleTime: 60_000
  });
  const snapshot = useSnapshot();
  const images =
    snapshot.data?.state.phase2?.assets.filter((a) => !a.deleted && a.mime.startsWith('image/')) ??
    [];
  const capabilities = overview.data?.capabilities;
  const allowed = (name: string) => capabilities?.[name]?.canExecute === true;
  const lists = useQuery({
    queryKey: ['youtube-playlists', workspaceId, channelId],
    queryFn: () => api.youtubeRead(workspaceId, channelId, 'playlists'),
    enabled: allowed('playlists'),
    staleTime: 60_000,
    retry: false
  });
  const categoryData = useQuery({
    queryKey: ['youtube-categories', workspaceId, channelId],
    queryFn: () => api.youtubeRead(workspaceId, channelId, 'categories'),
    enabled: allowed('identity'),
    staleTime: 86400_000,
    retry: false
  });
  const shortProblem =
    mode === 'short' &&
    (!asset?.width ||
      !asset.height ||
      !asset.duration ||
      asset.width > asset.height ||
      asset.duration > 180);
  const titleProblem = !title.trim() || title.length > 100 || /[<>]/.test(title);
  const descriptionProblem =
    new TextEncoder().encode(description).length > 5000 || /[<>]/.test(description);

  useEffect(() => {
    const translationInvalid = translations.some(
      (t) =>
        !t.language ||
        !t.title ||
        t.title.length > 100 ||
        new TextEncoder().encode(t.description).length > 5000
    );
    if (
      !capabilities?.upload?.canExecute ||
      !asset?.mime.startsWith('video/') ||
      titleProblem ||
      descriptionProblem ||
      !privacy ||
      fileError ||
      !audience ||
      !synthetic ||
      shortProblem ||
      translationInvalid ||
      (translations.length > 0 && !language) ||
      (caption && !caption.includes('-->'))
    ) {
      onChange(null);
      return;
    }
    const chosen = playlists.filter((id) => lists.data?.items?.some((p) => p.id === id));
    const podcast = lists.data?.items?.find(
      (p) => chosen.includes(p.id) && p.status?.podcastStatus === 'enabled'
    );
    onChange({
      mode,
      title,
      description,
      privacyStatus: privacy,
      publicationMode,
      madeForKids: audience === 'kids',
      containsSyntheticMedia: synthetic === 'yes',
      tags: tags
        ? tags
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean)
        : [],
      categoryId: category,
      license,
      embeddable,
      publicStatsViewable: publicStats,
      notifySubscribers: notify,
      ...(recordingDate ? { recordingDate: new Date(recordingDate).toISOString() } : {}),
      ...(language ? { defaultLanguage: language } : {}),
      ...(audioLanguage ? { defaultAudioLanguage: audioLanguage } : {}),
      ...(translations.length
        ? {
            localizations: Object.fromEntries(
              translations.map((t) => [t.language, { title: t.title, description: t.description }])
            )
          }
        : {}),
      ...(thumbnail && capabilities.thumbnail?.canExecute ? { thumbnailAssetId: thumbnail } : {}),
      ...(chosen.length
        ? { playlistIds: chosen, ...(podcast ? { podcastPlaylistId: podcast.id } : {}) }
        : {}),
      ...(caption && capabilities.captions?.canExecute
        ? {
            captionTracks: [
              {
                language: captionLanguage,
                name: captionName,
                isDraft: captionDraft,
                format: caption.startsWith('WEBVTT') ? 'vtt' : 'srt',
                text: caption
              }
            ]
          }
        : {})
    });
  }, [
    capabilities,
    asset,
    mode,
    title,
    description,
    privacy,
    publicationMode,
    fileError,
    audience,
    synthetic,
    tags,
    category,
    license,
    embeddable,
    publicStats,
    notify,
    recordingDate,
    language,
    audioLanguage,
    translations,
    thumbnail,
    playlists,
    lists.data,
    caption,
    captionLanguage,
    captionName,
    captionDraft,
    shortProblem,
    titleProblem,
    descriptionProblem,
    onChange
  ]);

  function field(label: string, value: string, change: (v: string) => void, multiline = false) {
    const id = `${uid}-${label.replaceAll(' ', '-')}`;
    return (
      <div className='grid gap-1.5'>
        <Label htmlFor={id}>{label}</Label>
        {multiline ? (
          <textarea
            aria-label={label}
            id={id}
            className={control}
            rows={4}
            value={value}
            onChange={(e) => change(e.target.value)}
          />
        ) : (
          <Input id={id} value={value} onChange={(e) => change(e.target.value)} />
        )}
      </div>
    );
  }
  return (
    <section className='grid gap-4 rounded-md border p-4' aria-label='YouTube publishing choices'>
      <div className='flex flex-wrap items-center justify-between gap-2'>
        <h3 className='font-medium'>YouTube</h3>
        <Link
          className='text-sm underline'
          href={`/app/youtube?channel=${encodeURIComponent(channelId)}`}
        >
          Creator tools and capability status
        </Link>
      </div>
      {overview.isError && (
        <p role='alert' className='text-sm text-destructive'>
          YouTube capabilities could not be checked. Reconnect or open creator tools before
          approval.
        </p>
      )}
      {!asset?.mime.startsWith('video/') && (
        <p className='text-sm'>
          Choose an inspected video from the Library. An article or image needs an explicit video
          conversion first.
        </p>
      )}
      <Label htmlFor={`${uid}-mode`}>Format</Label>
      <select
        id={`${uid}-mode`}
        className={control}
        value={mode}
        onChange={(e) => setMode(e.target.value as 'video' | 'short')}
      >
        <option value='video'>Video</option>
        <option value='short'>Short</option>
      </select>
      {shortProblem && (
        <p role='alert' className='text-sm text-destructive'>
          A Short needs a square or vertical video up to three minutes. YouTube confirms
          classification; #Shorts does not force it.
        </p>
      )}
      {field('Video title', title, setTitle)}
      {title.length > 100 && (
        <p role='alert' className='text-sm text-destructive'>
          Title exceeds 100 characters. Shorten it explicitly.
        </p>
      )}
      {field('Description', description, setDescription, true)}
      <p className='text-muted-foreground text-xs'>
        Line breaks, links, chapters, hashtags and credits are preserved.{' '}
        {new TextEncoder().encode(description).length}/5000 UTF-8 bytes
      </p>
      <Label htmlFor={`${uid}-privacy`}>Visibility</Label>
      <select
        id={`${uid}-privacy`}
        className={control}
        value={privacy}
        onChange={(e) => setPrivacy(e.target.value)}
      >
        <option value=''>Choose visibility</option>
        <option value='private' disabled={!allowed('private_publish')}>
          Private
        </option>
        {allowed('unlisted_publish') && <option value='unlisted'>Unlisted</option>}
        {allowed('public_publish') && <option value='public'>Public</option>}
      </select>
      {!allowed('public_publish') && (
        <p className='text-muted-foreground text-xs'>
          Public and unlisted publishing require verified Google approval and channel permissions.
          Private upload does not prove those gates.
        </p>
      )}
      <Label htmlFor={`${uid}-publication-mode`}>Publication</Label>
      <select
        id={`${uid}-publication-mode`}
        className={control}
        value={publicationMode}
        onChange={(e) => setPublicationMode(e.target.value as 'now' | 'schedule')}
      >
        <option value='now'>Publish after upload and verified processing</option>
        <option value='schedule'>Schedule for the selected time</option>
      </select>
      {publicationMode === 'now' && (
        <p className='text-sm'>
          Upload starts after approval. Actual publication follows YouTube processing and verified
          creator attachments.
        </p>
      )}
      {privacy === 'public' && publicationMode === 'schedule' && (
        <p className='text-sm'>
          The publication time selected below is scheduled directly on YouTube after processing and
          attachments are verified.
        </p>
      )}
      <Label htmlFor={`${uid}-kids`}>Made for Kids</Label>
      <select
        id={`${uid}-kids`}
        className={control}
        value={audience}
        onChange={(e) => setAudience(e.target.value)}
      >
        <option value=''>Declare the audience</option>
        <option value='not-kids'>No, this video is not made for kids</option>
        <option value='kids'>Yes, this video is made for kids</option>
      </select>
      <Label htmlFor={`${uid}-synthetic`}>Realistic altered or synthetic media</Label>
      <select
        id={`${uid}-synthetic`}
        className={control}
        value={synthetic}
        onChange={(e) => setSynthetic(e.target.value)}
      >
        <option value=''>Choose a declaration</option>
        <option value='no'>No</option>
        <option value='yes'>Yes</option>
      </select>
      <p className='text-muted-foreground text-xs'>
        Declare realistic altered scenes, people or events under{' '}
        <a
          href='https://support.google.com/youtube/answer/14328491'
          target='_blank'
          rel='noreferrer'
          className='underline'
        >
          YouTube’s policy
        </a>
        . Ordinary AI help writing a script does not itself require this disclosure.
      </p>
      <details>
        <summary className='cursor-pointer text-sm font-medium'>
          Metadata and creator attachments
        </summary>
        <div className='mt-4 grid gap-4'>
          {field('Tags separated by commas', tags, setTags)}
          <Label htmlFor={`${uid}-category`}>Category</Label>
          <select
            id={`${uid}-category`}
            className={control}
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            {(categoryData.data?.items?.length
              ? categoryData.data.items
              : ([{ id: '22', snippet: { title: 'People & Blogs' } }] as YouTubeResource[])
            ).map((c) => (
              <option key={c.id} value={c.id}>
                {c.snippet?.title}
              </option>
            ))}
          </select>
          {field('Metadata language', language, setLanguage)}
          {field('Audio language', audioLanguage, setAudioLanguage)}
          {allowed('localization') && (
            <>
              <p className='text-sm'>Localized titles and descriptions</p>
              {translations.map((t, i) => (
                <div className='grid gap-2 rounded-md border p-3' key={i}>
                  {(['language', 'title', 'description'] as const).map((k) =>
                    field(
                      `Translation ${i + 1} ${k}`,
                      t[k],
                      (value) =>
                        setTranslations((old) =>
                          old.map((item, at) => (at === i ? { ...item, [k]: value } : item))
                        ),
                      k === 'description'
                    )
                  )}
                  <button
                    type='button'
                    className='text-left text-sm underline'
                    onClick={() => setTranslations((old) => old.filter((_, at) => at !== i))}
                  >
                    Remove translation
                  </button>
                </div>
              ))}
              <button
                type='button'
                className='text-left text-sm underline'
                onClick={() =>
                  setTranslations((old) => [...old, { language: '', title: '', description: '' }])
                }
              >
                Add translation
              </button>
            </>
          )}
          <Label htmlFor={`${uid}-license`}>License</Label>
          <select
            id={`${uid}-license`}
            className={control}
            value={license}
            onChange={(e) => setLicense(e.target.value)}
          >
            <option value='youtube'>Standard YouTube license</option>
            <option value='creativeCommon'>Creative Commons</option>
          </select>
          <Label className='flex items-center gap-2'>
            <input
              aria-label='Allow embedding'
              type='checkbox'
              checked={embeddable}
              onChange={(e) => setEmbeddable(e.target.checked)}
            />
            Allow embedding
          </Label>
          <Label className='flex items-center gap-2'>
            <input
              aria-label='Allow public statistics'
              type='checkbox'
              checked={publicStats}
              onChange={(e) => setPublicStats(e.target.checked)}
            />
            Allow public statistics
          </Label>
          <Label htmlFor={`${uid}-recording`}>Recording date</Label>
          <input
            aria-label='Recording date'
            id={`${uid}-recording`}
            type='datetime-local'
            className={control}
            value={recordingDate}
            onChange={(e) => setRecordingDate(e.target.value)}
          />
          {allowed('subscriber_notifications') && (
            <Label className='flex items-center gap-2'>
              <input
                type='checkbox'
                aria-label='Notify subscribers'
                checked={notify}
                onChange={(e) => setNotify(e.target.checked)}
              />
              Notify subscribers when YouTube publishes this video
            </Label>
          )}
          {allowed('thumbnail') && (
            <>
              <Label htmlFor={`${uid}-thumbnail`}>Custom thumbnail</Label>
              <select
                id={`${uid}-thumbnail`}
                className={control}
                value={thumbnail}
                onChange={(e) => setThumbnail(e.target.value)}
              >
                <option value=''>YouTube’s default thumbnail</option>
                {images.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.id} · {a.width} × {a.height}
                  </option>
                ))}
              </select>
            </>
          )}
          {allowed('playlists') && (
            <fieldset className='grid gap-2'>
              <legend className='mb-2 text-sm'>Playlists and podcasts</legend>
              {lists.data?.items?.map((p) => (
                <Label key={p.id} className='flex items-center gap-2'>
                  <input
                    aria-label={p.snippet?.title || p.id}
                    type='checkbox'
                    checked={playlists.includes(p.id)}
                    onChange={(e) =>
                      setPlaylists((old) =>
                        e.target.checked ? [...old, p.id] : old.filter((id) => id !== p.id)
                      )
                    }
                  />
                  {p.snippet?.title}
                  {p.status?.podcastStatus === 'enabled' ? ' · Podcast' : ''}
                </Label>
              ))}
            </fieldset>
          )}
          {allowed('captions') && (
            <>
              <Label htmlFor={`${uid}-caption-file`}>Caption file (SRT or WebVTT)</Label>
              <input
                aria-label='Caption file (SRT or WebVTT)'
                id={`${uid}-caption-file`}
                type='file'
                accept='.srt,.vtt'
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  setFileError('');
                  if (!file) return;
                  if (file.size > 1_000_000) {
                    setFileError(
                      'Caption file exceeds Rafii’s 1 MB limit. Choose a smaller file explicitly.'
                    );
                    return;
                  }
                  try {
                    setCaption(
                      new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
                    );
                  } catch {
                    setFileError('Use an SRT or WebVTT file encoded as UTF-8.');
                  }
                }}
              />
              {fileError && (
                <p role='alert' className='text-destructive text-sm'>
                  {fileError}
                </p>
              )}
              {field('Caption text', caption, setCaption, true)}
              {field('Caption language', captionLanguage, setCaptionLanguage)}
              {field('Caption name', captionName, setCaptionName)}
              <Label className='flex items-center gap-2'>
                <input
                  aria-label='Save caption as draft'
                  type='checkbox'
                  checked={captionDraft}
                  onChange={(e) => setCaptionDraft(e.target.checked)}
                />
                Save caption as a draft
              </Label>
              <p className='text-xs text-muted-foreground'>
                Rafii manages supplied caption tracks. YouTube’s automatic caption generation is not
                controlled here.
              </p>
            </>
          )}
        </div>
      </details>
      <div className='rounded-md bg-muted/40 p-3' aria-label='YouTube metadata preview'>
        <p className='font-medium'>{title || 'Video title preview'}</p>
        <p className='mt-1 whitespace-pre-wrap text-sm'>{description}</p>
        <p className='mt-2 text-xs'>
          {mode === 'short' ? 'Short format candidate' : 'Video'} · {privacy || 'Choose visibility'}{' '}
          · {asset ? `${asset.width} × ${asset.height} · ${asset.duration}s` : 'No video selected'}
        </p>
      </div>
    </section>
  );
}
