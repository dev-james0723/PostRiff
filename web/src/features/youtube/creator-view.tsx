'use client';

import { useId, useState, type ReactNode } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useQueryState } from 'nuqs';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useChannels, useSnapshot } from '@/lib/api/hooks';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { YouTubeActionReview, YouTubeData, YouTubeResource } from '@/lib/youtube/types';
import { LiveCreatorControls, MetadataControls } from './creator-controls';
import { CreatorReceipts } from './creator-receipts';
import { UploadRecovery, StreamConfiguration } from './creator-recovery';
import { YouTubeResourceList } from './resource-list';
import { YouTubeAgentControls } from './agent-controls';
import { YouTubeQuotaControls } from './quota-controls';

const control = 'border-input bg-background w-full rounded-md border px-3 py-2 text-sm';
const actionLabels: Record<string, string> = {
  'video.edit': 'Edit video',
  'video.schedule': 'Schedule on YouTube',
  'video.cancel_schedule': 'Cancel YouTube schedule',
  'video.delete': 'Delete video',
  'thumbnail.set': 'Set thumbnail',
  'caption.insert': 'Add caption',
  'caption.update': 'Replace caption',
  'caption.delete': 'Delete caption',
  'playlist.create': 'Create playlist',
  'playlist.edit': 'Edit playlist',
  'playlist.delete': 'Delete playlist',
  'playlist.add': 'Add episode',
  'playlist.remove': 'Remove video from playlist',
  'playlist.reorder': 'Move playlist video',
  'playlist.image': 'Set podcast artwork',
  'podcast.enable': 'Enable podcast',
  'podcast.disable': 'Disable podcast',
  'comment.create': 'Post comment',
  'comment.reply': 'Reply to comment',
  'comment.edit': 'Edit own comment',
  'comment.delete': 'Delete own comment',
  'comment.moderate': 'Moderate comment',
  'broadcast.create': 'Schedule Live broadcast',
  'stream.create': 'Create Live stream',
  'broadcast.bind': 'Bind stream to broadcast',
  'broadcast.transition': 'Change Live state',
  'broadcast.delete': 'Delete broadcast',
  'chat.send': 'Send Live Chat message',
  'chat.delete': 'Delete Live Chat message',
  'chat.ban': 'Timeout Live Chat participant',
  'reporting.create': 'Create bulk reporting job',
  'reporting.delete': 'Delete reporting job'
};
function Field({
  label,
  value,
  change,
  type = 'text',
  multiline = false
}: {
  label: string;
  value: string;
  change: (v: string) => void;
  type?: string;
  multiline?: boolean;
}) {
  const id = useId();
  return (
    <div className='grid gap-1.5'>
      <Label htmlFor={id}>{label}</Label>
      {multiline ? (
        <textarea
          aria-label={label}
          id={id}
          rows={4}
          className={control}
          value={value}
          onChange={(e) => change(e.target.value)}
        />
      ) : (
        <Input id={id} type={type} value={value} onChange={(e) => change(e.target.value)} />
      )}
    </div>
  );
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className='grid gap-4 rounded-lg border p-4'>
      <h2 className='font-medium'>{title}</h2>
      {children}
    </section>
  );
}
// Uploads are playlistItem resources: their own ID must remain available for playlist operations.
function videoSelectionId(item: YouTubeResource): string | undefined {
  const details = item.contentDetails;
  const candidates: unknown[] = [];
  if (details && 'videoId' in details) candidates.push(details.videoId);
  if (item.snippet?.resourceId) candidates.push(item.snippet.resourceId.videoId);
  if (!candidates.length && 'kind' in item && item.kind === 'youtube#video') {
    candidates.push(item.id);
  }
  const id = candidates[0];
  return typeof id === 'string' && /^[A-Za-z0-9_-]{11}$/.test(id) &&
    candidates.every((candidate) => candidate === id) ? id : undefined;
}
/** Preserve the selected grant; an Analytics upgrade never substitutes the manual OAuth client. */
function creatorOAuthInput(
  connection: { id: string; authorizationLane?: string } | undefined,
  feature: string,
  agenticAnalyticsConsent: boolean,
  sensitive = false
): Record<string, unknown> {
  if (!connection) throw new Error('Select an available YouTube connection first.');
  const lane = connection.authorizationLane ?? 'standard';
  if (lane !== 'standard' && lane !== 'agentic') throw new Error('Reconnect this YouTube authorization before upgrading permissions.');
  if (lane === 'agentic' && (feature !== 'analytics' || !agenticAnalyticsConsent)) {
    throw new Error('Explicitly approve the separate agentic Analytics authorization before continuing. Other agentic permissions require their own consent flow.');
  }
  return {
    connectionId: connection.id,
    authorizationLane: lane,
    ...(lane === 'agentic' ? { agenticConsent: true } : {}),
    ...(sensitive ? { enableSensitive: true } : {})
  };
}
function Items({ data, select }: { data?: YouTubeData; select: (x: YouTubeResource) => void }) {
  return (
    <ul className='grid gap-2'>
      {data?.items?.map((item) => (
        <li key={item.id}>
          <button
            type='button'
            className='rafii-focus w-full rounded-md border p-3 text-left text-sm hover:bg-muted'
            onClick={() => select(item)}
          >
            {item.snippet?.title ||
              item.snippet?.textDisplay ||
              item.snippet?.displayMessage ||
              item.snippet?.topLevelComment?.snippet?.textDisplay ||
              item.id}
            <span className='text-muted-foreground mt-1 block text-xs'>
              {item.id}
              {item.status?.privacyStatus ? ` · ${item.status.privacyStatus}` : ''}
              {item.status?.podcastStatus === 'enabled' ? ' · Podcast' : ''}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function YouTubeCreatorView() {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { role: 'owner' });
  const canManage = checkAccess(access, { permission: 'manage_connections' });
  const client = useQueryClient();
  const channels = useChannels();
  const snapshot = useSnapshot();
  const yt = channels.data?.channels.filter((c) => c.platform === 'YouTube') ?? [];
  const [selected, setSelected] = useQueryState('channel', { defaultValue: '' });
  const channel = selected ? (yt.some((c) => c.id === selected) ? selected : '') : yt[0]?.id || '';
  const agenticConnection = yt.find((c) => c.id === channel)?.authorizationLane === 'agentic';
  const overview = useQuery({
    queryKey: ['youtube', workspaceId, channel],
    queryFn: () => api.youtubeOverview(workspaceId, channel),
    enabled: Boolean(channel),
    retry: false,
    staleTime: 60_000
  });
  const [tab, setTab] = useState('videos');
  const [result, setResult] = useState<YouTubeData>();
  const [lastRead, setLastRead] = useState<{ resource: string; query: Record<string, unknown> }>();
  const [review, setReview] = useState<YouTubeActionReview>();
  const [reviewSummary, setReviewSummary] = useState('');
  const [confirmTarget, setConfirmTarget] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [videoId, setVideoId] = useState('');
  const [playlistId, setPlaylistId] = useState('');
  const [itemId, setItemId] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [privacy, setPrivacy] = useState('private');
  const [date, setDate] = useState('');
  const [endTime, setEndTime] = useState('');
  const [liveCategory, setLiveCategory] = useState('22');
  const [caption, setCaption] = useState('');
  const [captionLanguage, setCaptionLanguage] = useState('en');
  const [captionName, setCaptionName] = useState('');
  const [captionId, setCaptionId] = useState('');
  const [image, setImage] = useState('');
  const [commentId, setCommentId] = useState('');
  const [commentText, setCommentText] = useState('');
  const [moderation, setModeration] = useState('published');
  const [position, setPosition] = useState('0');
  const [start, setStart] = useState(
    new Date(Date.now() - 28 * 86400_000).toISOString().slice(0, 10)
  );
  const [end, setEnd] = useState(new Date().toISOString().slice(0, 10));
  const [report, setReport] = useState('daily');
  const [broadcast, setBroadcast] = useState('');
  const [stream, setStream] = useState('');
  const [chatId, setChatId] = useState('');
  const [kids, setKids] = useState('');
  const [dvr, setDvr] = useState(true);
  const [recording, setRecording] = useState(true);
  const [autoStart, setAutoStart] = useState(false);
  const [autoStop, setAutoStop] = useState(false);
  const [probe, setProbe] = useState(false);
  const [ingestion, setIngestion] = useState('rtmp');
  const [resolution, setResolution] = useState('1080p');
  const [frameRate, setFrameRate] = useState('30fps');
  const [liveState, setLiveState] = useState('testing');
  const [reportType, setReportType] = useState('');
  const [includeFinancialReports, setIncludeFinancialReports] = useState(false);
  const [agenticAnalyticsConsent, setAgenticAnalyticsConsent] = useState(false);
  const [jobId, setJobId] = useState('');
  const [reportId, setReportId] = useState('');
  const [streamActionId, setStreamActionId] = useState('');
  const [streamKey, setStreamKey] = useState('');
  const [stateScope, setStateScope] = useState(`${workspaceId}:${channel}`);
  if (stateScope !== `${workspaceId}:${channel}`) {
    setStateScope(`${workspaceId}:${channel}`);
    setResult(undefined);
    setLastRead(undefined);
    setReview(undefined);
    setReviewSummary('');
    setVideoId('');
    setPlaylistId('');
    setItemId('');
    setCommentId('');
    setCaptionId('');
    setBroadcast('');
    setStream('');
    setChatId('');
    setStreamActionId('');
    setStreamKey('');
    setTitle('');
    setDescription('');
    setDate('');
    setEndTime('');
    setImage('');
    setProbe(false);
    setPrivacy('private');
    setKids('');
    setNotice('');
    setError('');
    setIncludeFinancialReports(false);
    setAgenticAnalyticsConsent(false);
  }
  const capabilities = overview.data?.capabilities;
  const can = (key: string) => capabilities?.[key]?.canExecute === true;
  const images =
    snapshot.data?.state.phase2?.assets.filter((a) => !a.deleted && a.mime.startsWith('image/')) ??
    [];
  async function run(operation: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await operation();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Creator operation unavailable.');
    } finally {
      setBusy(false);
    }
  }
  async function read(resource: string, query: Record<string, unknown> = {}) {
    await run(async () => {
      setResult(await api.youtubeRead(workspaceId, channel, resource, query));
      setLastRead({ resource, query });
    });
  }
  async function prepare(
    action: string,
    inputs: Record<string, unknown>,
    summary: string,
    options: Record<string, unknown> = {}
  ) {
    await run(async () => {
      setReview(await api.youtubePreview(workspaceId, channel, { action, inputs, ...options }));
      setReviewSummary(summary);
      setConfirmTarget('');
      setNotice('Review prepared. Nothing has been changed on YouTube.');
    });
  }
  async function approve() {
    if (!review) return;
    await run(async () => {
      const receipt = await api.youtubeApprove(workspaceId, channel, review.id, {
        digest: review.digest,
        confirmed: true,
        confirmationTarget: confirmTarget
      });
      setNotice(
        `${actionLabels[review.manifest.action] || 'Creator action'}: ${receipt.status}. ${receipt.receipt?.verification?.note || receipt.receipt?.message || ''}`
      );
      if (review.manifest.action === 'stream.create') setStreamActionId(receipt.id);
      setReview(undefined);
      await client.invalidateQueries({ queryKey: ['youtube', workspaceId, channel] });
    });
  }
  async function connect(feature: string, sensitive = false) {
    await run(async () => {
      const input = creatorOAuthInput(yt.find((c) => c.id === channel), feature, agenticAnalyticsConsent, sensitive);
      setAgenticAnalyticsConsent(false);
      const grant = await api.oauthStart(workspaceId, 'youtube', feature, input);
      if (!grant.authorizeUrl) throw new Error('Google authorization is unavailable.');
      window.location.assign(grant.authorizeUrl);
    });
  }
  function pick(item: YouTubeResource) {
    if (tab === 'videos') {
      const selectedVideoId = videoSelectionId(item);
      if (!selectedVideoId) {
        setVideoId('');
        setError('This item has no valid YouTube video ID. Refresh videos and select an available video.');
        return;
      }
      setVideoId(selectedVideoId);
      setTitle(item.snippet?.title || '');
      setDescription(item.snippet?.description || '');
    }
    if (tab === 'playlists') {
      if (lastRead?.resource === 'playlist_items') {
        const selectedVideoId = videoSelectionId(item);
        if (!selectedVideoId || typeof item.id !== 'string' || !/^[A-Za-z0-9_.:-]{1,256}$/.test(item.id)) {
          setItemId('');
          setVideoId('');
          setError('This playlist item has no valid item or video ID. Refresh the playlist and select an available item.');
          return;
        }
        setItemId(item.id);
        setVideoId(selectedVideoId);
        return;
      }
      setPlaylistId(item.id);
      setTitle(item.snippet?.title || '');
      setDescription(item.snippet?.description || '');
      setPrivacy(item.status?.privacyStatus || 'private');
    }
    if (tab === 'comments') {
      setCommentId(item.snippet?.topLevelComment?.id || item.snippet?.parentId || item.id);
    }
    if (tab === 'live') {
      if (lastRead?.resource === 'streams') setStream(item.id);
      else {
        setBroadcast(item.id);
        setChatId(item.snippet?.liveChatId || '');
      }
    }
  }
  const command = (label: string, enabled: boolean, click: () => void) => (
    <Button type='button' variant='outline' disabled={busy || !enabled} onClick={click}>
      {label}
    </Button>
  );
  const visibility = (
    <div className='grid gap-1.5'>
      <Label htmlFor='creator-visibility'>Visibility</Label>
      <select
        id='creator-visibility'
        className={control}
        value={privacy}
        onChange={(e) => setPrivacy(e.target.value)}
      >
        <option value='private'>Private</option>
        {can('unlisted_publish') && <option value='unlisted'>Unlisted</option>}
        {can('public_publish') && <option value='public'>Public</option>}
      </select>
    </div>
  );

  return (
    <PageContainer>
      <div className='mx-auto grid min-w-0 w-full max-w-6xl gap-6 pb-10 [&_button]:h-auto [&_button]:min-h-9 [&_button]:max-w-full [&_button]:whitespace-normal [&_button]:break-words [&_p]:break-words'>
        <div className='flex flex-wrap items-end justify-between gap-3'>
          <div>
            <h1 className='text-2xl font-semibold'>YouTube creator</h1>
            <p className='text-muted-foreground mt-1 text-sm'>
              Videos, Shorts, podcasts and Live, with separate permissions and verified receipts.
            </p>
          </div>
          <Link href='/app/channels' className='text-sm underline'>
            Connect YouTube
          </Link>
        </div>
        {!channel ? (
          <Panel title='Connect your creator channel'>
            <p className='text-sm'>
              Connect the intended YouTube channel in Channels. OAuth alone will not grant every
              creator capability.
            </p>
            <Link href='/app/channels' className='text-sm underline'>
              Open Channels
            </Link>
          </Panel>
        ) : (
          <>
            <Label htmlFor='creator-channel'>YouTube channel</Label>
            <select
              id='creator-channel'
              className={control}
              value={channel}
              onChange={(e) => {
                setSelected(e.target.value);
                setResult(undefined);
                setLastRead(undefined);
                setReview(undefined);
                setVideoId('');
                setPlaylistId('');
                setBroadcast('');
                setStream('');
                setChatId('');
                setStreamKey('');
              }}
            >
              {yt.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.account} {c.authorizationLane === 'agentic' ? '(autopilot authorization)' : '(manual authorization)'}
                </option>
              ))}
            </select>
            {overview.isError && (
              <p role='alert' className='text-destructive text-sm'>
                {overview.error instanceof Error
                  ? overview.error.message
                  : 'Creator capabilities unavailable.'}
              </p>
            )}
            <YouTubeAgentControls key={`youtube-agent:${workspaceId}:${channel}`} channel={channel} canPublic={Boolean(overview.data?.capabilities.schedule?.canExecute)} />
            {overview.data && (
              <Panel title={overview.data.identity.snippet?.title || 'Channel identity'}>
                <p className='text-sm'>Channel ID: {overview.data.channelId}</p>
                <p className='text-sm'>
                  {Object.entries(overview.data.identity.statistics || {})
                    .map(([key, value]) => `${key}: ${value}`)
                    .join(' · ')}
                </p>
                <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-4'>
                  {Object.entries(overview.data.readiness).map(([key, value]) => (
                    <div className='rounded-md border p-3 text-sm' key={key}>
                      <p className='font-medium'>
                        {
                          (
                            {
                              implementation: 'Implementation',
                              googleApproval: 'Google approval',
                              realE2E: 'Creator acceptance',
                              production: 'Production'
                            } as Record<string, string>
                          )[key]
                        }
                      </p>
                      <p className='text-muted-foreground mt-1'>{value}</p>
                    </div>
                  ))}
                </div>
              </Panel>
            )}
            <nav aria-label='YouTube creator tools' className='flex flex-wrap gap-2'>
              {[
                'videos',
                'playlists',
                'comments',
                'analytics',
                'live',
                'reporting',
                'capabilities'
              ].map((t) => (
                <Button
                  key={t}
                  variant={tab === t ? 'default' : 'outline'}
                  onClick={() => {
                    setTab(t);
                    setResult(undefined);
                  }}
                  aria-pressed={tab === t}
                >
                  {t === 'playlists' ? 'Playlists & podcasts' : t[0].toUpperCase() + t.slice(1)}
                </Button>
              ))}
            </nav>
            {notice && (
              <p role='status' className='rounded-md border p-3 text-sm'>
                {notice}
              </p>
            )}
            {error && (
              <p role='alert' className='text-destructive text-sm'>
                {error}
              </p>
            )}
            {review && (
              <Panel title='Approve this exact YouTube action'>
                <p className='font-medium'>
                  {actionLabels[review.manifest.action] || review.manifest.action}
                </p>
                <p className='whitespace-pre-wrap text-sm'>{reviewSummary}</p>
                <p className='text-xs text-muted-foreground'>
                  Connected channel: {review.manifest.channelId}. This approval expires in ten
                  minutes.
                </p>
                {review.manifest.destructive && (
                  <>
                    <p className='text-sm'>
                      This action is destructive and is never automatically retried. Confirm
                      resource ID: {review.confirmationTarget}
                    </p>
                    <Field
                      label='Confirm resource ID'
                      value={confirmTarget}
                      change={setConfirmTarget}
                    />
                  </>
                )}
                <div className='flex flex-wrap gap-2'>
                  <Button
                    onClick={approve}
                    disabled={
                      busy ||
                      (review.manifest.destructive && confirmTarget !== review.confirmationTarget)
                    }
                  >
                    Approve exact action
                  </Button>
                  <Button variant='outline' onClick={() => setReview(undefined)}>
                    Discard review
                  </Button>
                </div>
              </Panel>
            )}
            {tab === 'videos' && (
              <>
                <Panel title='Video or Short'>
                  <p className='text-sm'>
                    The Queue composer supports Video and Short with inspected media, descriptions,
                    declarations, caption tracks and YouTube-native public scheduling.
                  </p>
                  <div className='flex flex-wrap gap-3'>
                    <Link
                      className='text-sm underline'
                      href={`/app/queue?channel=${encodeURIComponent(channel)}`}
                    >
                      Open YouTube composer
                    </Link>
                    <Link className='text-sm underline' href='/app/library'>
                      Upload or select a video
                    </Link>
                    {command('Refresh videos', can('identity'), () => read('videos'))}
                  </div>
                  {lastRead?.resource === 'videos' ? (
                    <YouTubeResourceList
                      data={result}
                      resourceType='video'
                      select={pick}
                      getIdentifier={videoSelectionId}
                      isSelected={(item) => videoSelectionId(item) === videoId}
                    />
                  ) : (
                    <Items data={result} select={pick} />
                  )}
                </Panel>
                <Panel title='Manage an existing video'>
                  <Field label='Video ID' value={videoId} change={setVideoId} />
                  <Field label='Title' value={title} change={setTitle} />
                  <Field
                    label='Description'
                    value={description}
                    change={setDescription}
                    multiline
                  />
                  {visibility}
                  <div className='flex flex-wrap gap-2'>
                    {command(
                      'Review metadata change',
                      can('metadata_edit') && Boolean(videoId && title),
                      () =>
                        prepare(
                          'video.edit',
                          {
                            id: videoId,
                            patch: {
                              snippet: { title, description },
                              status: { privacyStatus: privacy }
                            }
                          },
                          `${title}\n${description}\nVisibility: ${privacy}`
                        )
                    )}
                    {command('Inspect video processing', Boolean(videoId), () =>
                      read('videos', { id: videoId })
                    )}
                    {command('Review deletion', can('delete') && Boolean(videoId), () =>
                      prepare(
                        'video.delete',
                        { id: videoId },
                        `Permanently delete video ${videoId}.`
                      )
                    )}
                  </div>
                  <Field
                    label='Future publication time'
                    value={date}
                    change={setDate}
                    type='datetime-local'
                  />
                  <div className='flex flex-wrap gap-2'>
                    {command(
                      'Review native schedule',
                      can('schedule') && Boolean(videoId && date),
                      () =>
                        prepare(
                          'video.schedule',
                          { id: videoId, publishAt: new Date(date).toISOString() },
                          `YouTube publishes ${videoId} at ${new Date(date).toLocaleString()}. The video must be private and never published.`
                        )
                    )}
                    {command(
                      'Review schedule cancellation',
                      can('schedule') && Boolean(videoId),
                      () =>
                        prepare(
                          'video.cancel_schedule',
                          { id: videoId },
                          `Cancel YouTube’s schedule and keep ${videoId} private.`
                        )
                    )}
                  </div>
                  {videoId && (
                    <a
                      href={`https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`}
                      target='_blank'
                      rel='noreferrer'
                      className='text-sm underline'
                    >
                      Open original video
                    </a>
                  )}
                  {can('metadata_edit') && (
                    <MetadataControls
                      key={channel + videoId}
                      kind='video'
                      identifier={videoId}
                      busy={busy}
                      prepare={prepare}
                    />
                  )}
                </Panel>
                <Panel title='Captions and thumbnail'>
                  <Label htmlFor='creator-image'>Private workspace image</Label>
                  <select
                    id='creator-image'
                    className={control}
                    value={image}
                    onChange={(e) => setImage(e.target.value)}
                  >
                    <option value=''>Select a rights-cleared image</option>
                    {images.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.id} · {a.width} × {a.height}
                      </option>
                    ))}
                  </select>
                  {owner && (
                    <Label className='flex gap-2 text-sm'>
                      <input
                        aria-label='Allow one explicit eligibility test'
                        type='checkbox'
                        checked={probe}
                        onChange={(e) => setProbe(e.target.checked)}
                      />
                      Allow one explicit eligibility test for this channel
                    </Label>
                  )}
                  {command(
                    'Review thumbnail update',
                    Boolean(videoId && image) &&
                      (can('thumbnail') ||
                        (owner &&
                          probe &&
                          capabilities?.thumbnail?.state === 'BLOCKED — ACCOUNT ELIGIBILITY')),
                    () =>
                      prepare(
                        'thumbnail.set',
                        { id: videoId, assetId: image },
                        `Set image ${image} as the thumbnail for ${videoId}. I confirm rights to this image.`,
                        { rightsConfirmed: true, eligibilityProbe: probe }
                      )
                  )}
                  <Field
                    label='Caption language'
                    value={captionLanguage}
                    change={setCaptionLanguage}
                  />
                  <Field label='Caption name' value={captionName} change={setCaptionName} />
                  <Field
                    label='Timed SRT or WebVTT caption'
                    value={caption}
                    change={setCaption}
                    multiline
                  />
                  <Field
                    label='Existing caption ID to replace or delete'
                    value={captionId}
                    change={setCaptionId}
                  />
                  <div className='flex flex-wrap gap-2'>
                    {command('List captions', can('captions') && Boolean(videoId), () =>
                      read('captions', { videoId })
                    )}
                    {command(
                      'Review caption upload',
                      can('captions') && Boolean(videoId && caption),
                      () =>
                        prepare(
                          captionId ? 'caption.update' : 'caption.insert',
                          {
                            id: captionId || undefined,
                            videoId,
                            track: {
                              language: captionLanguage,
                              name: captionName,
                              text: caption,
                              format: caption.startsWith('WEBVTT') ? 'vtt' : 'srt',
                              isDraft: false
                            }
                          },
                          `${captionLanguage} · ${captionName}\n${caption}`
                        )
                    )}
                    {command(
                      'Review caption deletion',
                      can('captions') && Boolean(videoId && captionId),
                      () =>
                        prepare(
                          'caption.delete',
                          { id: captionId, videoId },
                          `Delete caption ${captionId} from ${videoId}.`
                        )
                    )}
                  </div>
                </Panel>
                <Panel title='Upload lifecycle'>
                  {overview.data?.uploads.map((u) => (
                    <div key={u.operationKey} className='grid gap-1 border-b pb-3 text-sm'>
                      <p>
                        {u.videoId || 'Upload in progress'} · {u.stage}
                      </p>
                      <progress
                        className='w-full'
                        aria-label='Video bytes acknowledged by YouTube'
                        max={u.totalBytes || 1}
                        value={u.bytesSent}
                      />
                      <p className='text-xs text-muted-foreground'>
                        {u.bytesSent}/{u.totalBytes} bytes acknowledged
                        {u.errorCategory ? ` · ${u.errorCategory}` : ''}
                        {u.publishAt ? ` · YouTube publication ${u.publishAt}` : ''}
                      </p>
                      <UploadRecovery
                        key={channel + u.operationKey}
                        channel={channel}
                        operationKey={u.operationKey}
                        stage={u.stage}
                      />
                    </div>
                  ))}
                </Panel>
              </>
            )}
            {tab === 'playlists' && (
              <Panel title='Playlists and podcast shows'>
                <div className='flex flex-wrap gap-2'>
                  {command('List playlists', can('identity'), () => read('playlists'))}
                </div>
                <YouTubeResourceList
                  data={result}
                  resourceType={lastRead?.resource === 'playlist_items' ? 'video' : 'playlist'}
                  select={pick}
                  getIdentifier={lastRead?.resource === 'playlist_items' ? videoSelectionId : undefined}
                  isSelected={(item) => lastRead?.resource === 'playlist_items'
                    ? item.id === itemId
                    : item.id === playlistId}
                />
                <Field label='Playlist ID' value={playlistId} change={setPlaylistId} />
                <Field label='Playlist title' value={title} change={setTitle} />
                <Field
                  label='Playlist description'
                  value={description}
                  change={setDescription}
                  multiline
                />
                {visibility}
                <div className='flex flex-wrap gap-2'>
                  {command('Review new playlist', can('playlists') && Boolean(title), () =>
                    prepare(
                      'playlist.create',
                      { snippet: { title, description }, privacyStatus: privacy },
                      `${title}\n${description}\n${privacy}`
                    )
                  )}
                  {command(
                    'Review playlist edit',
                    can('playlists') && Boolean(playlistId && title),
                    () =>
                      prepare(
                        'playlist.edit',
                        {
                          id: playlistId,
                          patch: {
                            snippet: { title, description },
                            status: { privacyStatus: privacy }
                          }
                        },
                        `${playlistId}\n${title}\n${description}\n${privacy}`
                      )
                  )}
                  {command(
                    'Review playlist deletion',
                    can('playlists') && Boolean(playlistId),
                    () =>
                      prepare(
                        'playlist.delete',
                        { id: playlistId },
                        `Delete playlist ${playlistId}.`
                      )
                  )}
                </div>
                <Field
                  label='Video ID for episode membership'
                  value={videoId}
                  change={setVideoId}
                />
                <Field
                  label='Playlist item ID for removal or reorder'
                  value={itemId}
                  change={setItemId}
                />
                <Field
                  label='Playlist position (starting at zero)'
                  value={position}
                  change={setPosition}
                />
                <div className='flex flex-wrap gap-2'>
                  {command('List playlist videos', Boolean(playlistId), () =>
                    read('playlist_items', { playlistId })
                  )}
                  {command(
                    'Review episode insertion',
                    can('playlists') && Boolean(videoId && playlistId),
                    () =>
                      prepare(
                        'playlist.add',
                        { playlistId, videoId },
                        `Add ${videoId} to ${playlistId}. The existing video will not be uploaded again.`
                      )
                  )}
                  {command(
                    'Review removal',
                    can('playlists') && Boolean(itemId && playlistId),
                    () =>
                      prepare(
                        'playlist.remove',
                        { playlistId, id: itemId },
                        `Remove item ${itemId} from ${playlistId}.`
                      )
                  )}
                  {command(
                    'Review reorder',
                    can('playlists') && Boolean(itemId && playlistId),
                    () =>
                      prepare(
                        'playlist.reorder',
                        { playlistId, id: itemId, position: Number(position) },
                        `Move ${itemId} to position ${position} in ${playlistId}.`
                      )
                  )}
                </div>
                <Label htmlFor='podcast-artwork'>Square podcast artwork</Label>
                <select
                  id='podcast-artwork'
                  className={control}
                  value={image}
                  onChange={(e) => setImage(e.target.value)}
                >
                  <option value=''>Select a rights-cleared square image</option>
                  {images
                    .filter((a) => a.width === a.height)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.id}
                      </option>
                    ))}
                </select>
                <div className='flex flex-wrap gap-2'>
                  {command('Review artwork', can('podcasts') && Boolean(image && playlistId), () =>
                    prepare(
                      'playlist.image',
                      { playlistId, assetId: image },
                      `Set square artwork ${image} for ${playlistId}. I confirm rights to this image.`,
                      { rightsConfirmed: true }
                    )
                  )}
                  {command(
                    'Review podcast enablement',
                    can('podcasts') && Boolean(playlistId),
                    () =>
                      prepare(
                        'podcast.enable',
                        { id: playlistId },
                        `Enable podcast status on ${playlistId}. Artwork is required.`
                      )
                  )}
                  {command(
                    'Review podcast disablement',
                    can('podcasts') && Boolean(playlistId),
                    () =>
                      prepare(
                        'podcast.disable',
                        { id: playlistId },
                        `Disable podcast status on ${playlistId}.`
                      )
                  )}
                </div>
                {can('playlists') && (
                  <MetadataControls
                    key={channel + playlistId}
                    kind='playlist'
                    identifier={playlistId}
                    busy={busy}
                    prepare={prepare}
                  />
                )}
              </Panel>
            )}
            {tab === 'comments' && (
              <Panel title='YouTube Comment Inbox'>
                <Field label='Filter by video ID (optional)' value={videoId} change={setVideoId} />
                <Label htmlFor='comment-moderation'>Moderation filter</Label>
                <select
                  id='comment-moderation'
                  className={control}
                  value={moderation}
                  onChange={(e) => setModeration(e.target.value)}
                >
                  <option value='published'>Published</option>
                  {can('moderation') && <option value='heldForReview'>Held for review</option>}
                </select>
                <div className='flex flex-wrap gap-2'>
                  {owner &&
                    capabilities?.moderation?.state === 'BLOCKED — ACCOUNT ELIGIBILITY' &&
                    command('Check held-for-review authority', can('comment_read'), () =>
                      read('comments', {
                        ...(videoId ? { videoId } : {}),
                        moderationStatus: 'heldForReview',
                        eligibilityProbe: true
                      })
                    )}
                  {command('Newest comments', can('comment_read'), () =>
                    read('comments', {
                      ...(videoId ? { videoId } : {}),
                      ...(can('moderation') ? { moderationStatus: moderation } : {})
                    })
                  )}
                  {command('Unanswered', can('comment_read'), () =>
                    read('comments', { ...(videoId ? { videoId } : {}), unanswered: true })
                  )}
                  <Link href='/app/inbox' className='self-center text-sm underline'>
                    Shared Inbox and AI draft suggestions
                  </Link>
                </div>
                <Items data={result} select={pick} />
                <Field label='Top-level comment ID' value={commentId} change={setCommentId} />
                <Field
                  label='Exact comment or reply text'
                  value={commentText}
                  change={setCommentText}
                  multiline
                />
                <div className='flex flex-wrap gap-2'>
                  {command('Read replies', Boolean(commentId), () =>
                    read('replies', { parentId: commentId })
                  )}
                  {command('Review reply', can('reply') && Boolean(commentId && commentText), () =>
                    prepare(
                      'comment.reply',
                      { id: commentId, text: commentText },
                      `Reply to ${commentId}:\n${commentText}`
                    )
                  )}
                  {command(
                    'Review top-level comment',
                    can('top_level_comment') && Boolean(videoId && commentText),
                    () =>
                      prepare(
                        'comment.create',
                        { videoId, text: commentText },
                        `Comment on ${videoId}:\n${commentText}`
                      )
                  )}
                  {command(
                    'Review own-comment edit',
                    can('comment_edit') && Boolean(commentId && commentText),
                    () =>
                      prepare(
                        'comment.edit',
                        { id: commentId, text: commentText },
                        `Edit own comment ${commentId}:\n${commentText}`
                      )
                  )}
                  {command(
                    'Review own-comment deletion',
                    can('comment_delete') && Boolean(commentId),
                    () =>
                      prepare(
                        'comment.delete',
                        { id: commentId },
                        `Delete own comment ${commentId}.`
                      )
                  )}
                  {['published', 'heldForReview', 'rejected'].map((status) => (
                    <span key={status}>
                      {command(`Review ${status}`, can('moderation') && Boolean(commentId), () =>
                        prepare(
                          'comment.moderate',
                          { id: commentId, moderationStatus: status },
                          `Set comment ${commentId} to ${status}.`
                        )
                      )}
                    </span>
                  ))}
                </div>
                <p className='text-xs text-muted-foreground'>
                  AI suggestions remain drafts until a person approves the exact text. Each comment
                  action has its own receipt.
                </p>
              </Panel>
            )}
            {tab === 'analytics' && (
              <Panel title='Creator analytics'>
                <div className='grid gap-3 sm:grid-cols-2'>
                  <Field label='Start date' value={start} change={setStart} type='date' />
                  <Field label='End date' value={end} change={setEnd} type='date' />
                </div>
                <Label htmlFor='creator-report'>Report</Label>
                <select
                  id='creator-report'
                  className={control}
                  value={report}
                  onChange={(e) => setReport(e.target.value)}
                >
                  {Object.entries({
                    daily: 'Daily performance',
                    content_type: 'Shorts, video and Live content types',
                    geography: 'Geography',
                    traffic: 'Traffic sources',
                    device: 'Devices',
                    playback_location: 'Playback locations',
                    demographics: 'Demographics',
                    retention: 'Video retention',
                    playlist: 'Playlist performance',
                    live: 'Live versus on demand'
                  }).map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                </select>
                <Field
                  label='Video ID for retention or video filtering'
                  value={videoId}
                  change={setVideoId}
                />
                <Field
                  label='Playlist ID for playlist performance'
                  value={playlistId}
                  change={setPlaylistId}
                />
                <div className='flex flex-wrap gap-2'>
                  {command('Read creator analytics', can('analytics'), () =>
                    read('analytics', {
                      report,
                      startDate: start,
                      endDate: end,
                      ...(videoId ? { videoId } : {}),
                      ...(playlistId ? { playlistId } : {})
                    })
                  )}
                  {can('monetary_analytics') &&
                    command('Read revenue analytics', true, () =>
                      read('revenue', { startDate: start, endDate: end })
                    )}
                </div>
                {result?.data && (
                  <div className='overflow-x-auto'>
                    <p className='mb-2 text-xs text-muted-foreground'>
                      Source: {result.source}. Empty or withheld rows are unavailable, not zero.
                    </p>
                    {result.limitation && (
                      <p className='mb-2 text-xs text-amber-700'>{result.limitation}</p>
                    )}
                    <table className='w-full text-left text-sm'>
                      <thead>
                        <tr>
                          {result.data.columnHeaders?.map((h) => (
                            <th key={h.name} className='border-b p-2'>
                              {h.name}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.data.rows?.map((r, i) => (
                          <tr key={i}>
                            {r.map((v, k) => (
                              <td className='border-b p-2' key={k}>
                                {v}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            )}
            {tab === 'live' && (
              <>
                <Panel title='Schedule Live'>
                  <Field label='Live title' value={title} change={setTitle} />
                  <Field
                    label='Live description'
                    value={description}
                    change={setDescription}
                    multiline
                  />
                  <Field
                    label='Scheduled start'
                    value={date}
                    change={setDate}
                    type='datetime-local'
                  />
                  {visibility}
                  <Field
                    label='Scheduled end (optional)'
                    value={endTime}
                    change={setEndTime}
                    type='datetime-local'
                  />
                  <Field label='Live category ID' value={liveCategory} change={setLiveCategory} />
                  <Label htmlFor='live-kids'>Made for Kids</Label>
                  <select
                    id='live-kids'
                    className={control}
                    value={kids}
                    onChange={(e) => setKids(e.target.value)}
                  >
                    <option value=''>Declare the audience</option>
                    <option value='no'>Not made for kids</option>
                    <option value='yes'>Made for kids</option>
                  </select>
                  {[
                    ['DVR', dvr, setDvr],
                    ['Record from start', recording, setRecording],
                    ['Automatic start', autoStart, setAutoStart],
                    ['Automatic stop', autoStop, setAutoStop],
                    ...(owner
                      ? [['Allow one explicit Live eligibility test', probe, setProbe]]
                      : [])
                  ].map(([label, value, setter]) => (
                    <Label className='flex flex-wrap gap-2' key={String(label)}>
                      <input
                        aria-label={String(label)}
                        type='checkbox'
                        checked={Boolean(value)}
                        onChange={(e) => (setter as (v: boolean) => void)(e.target.checked)}
                      />
                      {String(label)}
                    </Label>
                  ))}
                  {command(
                    'Review Live scheduling',
                    Boolean(title && date && kids) &&
                      (can('live_broadcast') ||
                        (owner &&
                          probe &&
                          capabilities?.live_broadcast?.state === 'BLOCKED — ACCOUNT ELIGIBILITY')),
                    () =>
                      prepare(
                        'broadcast.create',
                        {
                          body: {
                            snippet: {
                              title,
                              description,
                              scheduledStartTime: new Date(date).toISOString(),
                              categoryId: liveCategory,
                              ...(endTime
                                ? { scheduledEndTime: new Date(endTime).toISOString() }
                                : {})
                            },
                            status: {
                              privacyStatus: privacy,
                              selfDeclaredMadeForKids: kids === 'yes'
                            },
                            contentDetails: {
                              enableDvr: dvr,
                              recordFromStart: recording,
                              enableAutoStart: autoStart,
                              enableAutoStop: autoStop
                            }
                          }
                        },
                        `${title}\n${description}\n${new Date(date).toLocaleString()} · ${privacy} · Made for Kids: ${kids}\nDVR: ${dvr}; Record from start: ${recording}; Automatic start: ${autoStart}; Automatic stop: ${autoStop}`,
                        { eligibilityProbe: probe }
                      )
                  )}
                  {command('List broadcasts', Boolean(channel), () => read('broadcasts'))}
                  {command('List streams', can('identity'), () => read('streams'))}
                  {command(
                    'Review existing broadcast time and DVR settings',
                    can('live_broadcast') && Boolean(broadcast && date),
                    () =>
                      prepare(
                        'broadcast.edit',
                        {
                          id: broadcast,
                          patch: {
                            snippet: {
                              scheduledStartTime: new Date(date).toISOString(),
                              ...(endTime
                                ? { scheduledEndTime: new Date(endTime).toISOString() }
                                : {})
                            },
                            contentDetails: {
                              enableDvr: dvr,
                              recordFromStart: recording,
                              enableAutoStart: autoStart,
                              enableAutoStop: autoStop
                            }
                          }
                        },
                        `Update broadcast ${broadcast}:\nStart ${date}; End ${endTime || 'preserve existing end'}\nDVR ${dvr}; recording ${recording}; automatic start ${autoStart}; automatic stop ${autoStop}.`
                      )
                  )}
                  {can('thumbnail') && (
                    <div className='grid gap-2'>
                      <Label htmlFor='live-thumbnail'>
                        Existing workspace thumbnail (rights confirmed when reviewed)
                      </Label>
                      <select
                        id='live-thumbnail'
                        className={control}
                        value={image}
                        onChange={(event) => setImage(event.target.value)}
                      >
                        <option value=''>Choose a thumbnail</option>
                        {images.map((asset) => (
                          <option value={asset.id} key={asset.id}>
                            {asset.id}
                          </option>
                        ))}
                      </select>
                      {command('Review Live thumbnail', Boolean(broadcast && image), () =>
                        prepare(
                          'thumbnail.set',
                          { id: broadcast, assetId: image },
                          `Apply workspace image ${image} to broadcast ${broadcast}.`,
                          { rightsConfirmed: true }
                        )
                      )}
                    </div>
                  )}
                  <Items data={result} select={pick} />
                </Panel>
                <Panel title='Stream and broadcast lifecycle'>
                  <Field label='Broadcast ID' value={broadcast} change={setBroadcast} />
                  <Field label='Stream ID' value={stream} change={setStream} />
                  <Label htmlFor='ingestion-type'>Ingestion</Label>
                  <select
                    id='ingestion-type'
                    value={ingestion}
                    className={control}
                    onChange={(e) => setIngestion(e.target.value)}
                  >
                    {['rtmp', 'hls', 'dash'].map((v) => (
                      <option key={v} value={v}>
                        {v.toUpperCase()}
                      </option>
                    ))}
                  </select>
                  <Label htmlFor='live-resolution'>Resolution</Label>
                  <select
                    id='live-resolution'
                    value={resolution}
                    className={control}
                    onChange={(e) => setResolution(e.target.value)}
                  >
                    {['720p', '1080p', '1440p', '2160p', 'variable'].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                  <Label htmlFor='live-frame-rate'>Frame rate</Label>
                  <select
                    id='live-frame-rate'
                    value={frameRate}
                    className={control}
                    onChange={(e) => setFrameRate(e.target.value)}
                  >
                    {['30fps', '60fps', 'variable'].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                  <div className='flex flex-wrap gap-2'>
                    {command(
                      'Review stream creation',
                      Boolean(title) && (can('live_stream') || probe),
                      () =>
                        prepare(
                          'stream.create',
                          {
                            body: {
                              snippet: { title, description },
                              cdn: { ingestionType: ingestion, resolution, frameRate },
                              contentDetails: { isReusable: true }
                            }
                          },
                          `Create ${ingestion} stream: ${title} · ${resolution} · ${frameRate}`,
                          { eligibilityProbe: probe }
                        )
                    )}
                    {command(
                      'Review stream binding',
                      can('live_broadcast') && Boolean(broadcast && stream),
                      () =>
                        prepare(
                          'broadcast.bind',
                          { id: broadcast, streamId: stream },
                          `Bind stream ${stream} to broadcast ${broadcast}.`
                        )
                    )}
                    {command('Inspect stream monitoring', Boolean(stream), () =>
                      read('streams', { id: stream })
                    )}
                    {command('Inspect broadcast and archive', Boolean(broadcast), () =>
                      read('broadcasts', { id: broadcast })
                    )}
                  </div>
                  <Label htmlFor='live-transition'>Next lifecycle state</Label>
                  <select
                    id='live-transition'
                    className={control}
                    value={liveState}
                    onChange={(e) => setLiveState(e.target.value)}
                  >
                    <option value='testing'>Testing</option>
                    <option value='live'>Go live</option>
                    <option value='complete'>End broadcast</option>
                  </select>
                  {command(
                    'Review lifecycle transition',
                    can('live_broadcast') && Boolean(broadcast),
                    () =>
                      prepare(
                        'broadcast.transition',
                        { id: broadcast, broadcastStatus: liveState },
                        `Transition ${broadcast} to ${liveState}. YouTube’s current lifecycle determines whether this is valid.`
                      )
                  )}
                  {owner &&
                    streamActionId &&
                    command('Reveal stream key after fresh owner sign-in', true, () =>
                      run(async () =>
                        setStreamKey(
                          (await api.youtubeStreamKey(workspaceId, channel, streamActionId))
                            .streamKey
                        )
                      )
                    )}
                  {streamKey && (
                    <>
                      <p
                        className='rounded-md border p-3 font-mono text-sm'
                        aria-label='Sensitive stream key'
                      >
                        {streamKey}
                      </p>
                      <Button variant='outline' onClick={() => setStreamKey('')}>
                        Hide stream key
                      </Button>
                    </>
                  )}
                </Panel>
                <Panel title='Live Chat'>
                  <Field label='Live Chat ID' value={chatId} change={setChatId} />
                  {command(
                    'Read ordered Live Chat',
                    Boolean(chatId && broadcast) &&
                      !busy &&
                      !(Number(result?.nextReadAt || 0) > Date.now() / 1000),
                    () => read('chat', { liveChatId: chatId, broadcastId: broadcast })
                  )}
                  <Items data={result} select={(item) => setCommentId(item.id)} />
                  <Field label='Exact chat message' value={commentText} change={setCommentText} />
                  <div className='flex flex-wrap gap-2'>
                    {command(
                      'Review chat message',
                      can('live_chat_write') && Boolean(chatId && broadcast && commentText),
                      () =>
                        prepare(
                          'chat.send',
                          { liveChatId: chatId, broadcastId: broadcast, text: commentText },
                          `Send to Live Chat ${chatId}:\n${commentText}`
                        )
                    )}
                    {command(
                      'Review message deletion',
                      can('live_moderation') && Boolean(commentId),
                      () =>
                        prepare(
                          'chat.delete',
                          { liveChatId: chatId, broadcastId: broadcast, id: commentId },
                          `Delete Live Chat message ${commentId}.`
                        )
                    )}
                  </div>
                  <p className='text-muted-foreground text-xs'>
                    Official streaming delivery is preferred. Reconnect cursors preserve order;
                    fallback reads honor YouTube’s minimum interval.
                  </p>
                </Panel>
                <StreamConfiguration
                  key={'stream-config:' + channel + ':' + stream}
                  channel={channel}
                  streamId={stream}
                />
                <LiveCreatorControls
                  key={'live-controls:' + channel}
                  capabilities={capabilities}
                  broadcast={broadcast}
                  stream={stream}
                  chat={chatId}
                  busy={busy}
                  prepare={prepare}
                  read={read}
                />
              </>
            )}
            {tab === 'reporting' && (
              <Panel title='Bulk historical reports'>
                <p className='text-sm'>
                  Use Analytics for interactive queries. Reporting jobs generate daily datasets with
                  coverage and correction timestamps.
                </p>
                <div className='flex flex-wrap gap-2'>
                  {command('Available report types', can('reporting'), () =>
                    read('report_types', { includeMonetary: includeFinancialReports })
                  )}
                  {command('Existing reporting jobs', can('reporting'), () =>
                    read('report_jobs', { includeMonetary: includeFinancialReports })
                  )}
                </div>
                {owner && overview.data?.sensitiveAuthorizations.monetary && (
                  <Label className='flex items-center gap-2'>
                    <input
                      aria-label='Include separately authorized financial reports'
                      type='checkbox'
                      checked={includeFinancialReports}
                      onChange={(event) => setIncludeFinancialReports(event.target.checked)}
                    />
                    Include separately authorized financial reports (fresh owner sign-in required)
                  </Label>
                )}
                {result?.reportTypes?.map((t) => (
                  <button
                    key={t.id}
                    className='text-left text-sm underline'
                    onClick={() => setReportType(t.id)}
                  >
                    {t.name}
                  </button>
                ))}
                {result?.jobs?.map((j) => (
                  <button
                    key={j.id}
                    className='text-left text-sm underline'
                    onClick={() => setJobId(j.id)}
                  >
                    {j.name} · {j.id}
                  </button>
                ))}
                <Field label='Report type' value={reportType} change={setReportType} />
                <Field label='Reporting job name' value={title} change={setTitle} />
                {command(
                  'Review reporting job',
                  can('reporting') && Boolean(reportType && title),
                  () =>
                    prepare(
                      'reporting.create',
                      { reportTypeId: reportType, name: title },
                      `Create daily reporting job ${title} for ${reportType}.`
                    )
                )}
                <Field label='Job ID' value={jobId} change={setJobId} />
                {command('Generated reports', can('reporting') && Boolean(jobId), () =>
                  read('reports', { jobId })
                )}
                {result?.reports?.map((r) => (
                  <button
                    key={r.id}
                    className='text-left text-sm underline'
                    onClick={() => setReportId(r.id)}
                  >
                    {r.startTime} to {r.endTime} · {r.id}
                  </button>
                ))}
                <Field label='Report ID to ingest' value={reportId} change={setReportId} />
                {command(
                  'Ingest selected official dataset',
                  can('reporting') && Boolean(jobId && reportId),
                  () => read('report_ingest', { jobId, reportId })
                )}
                {command('Review reporting job deletion', can('reporting') && Boolean(jobId), () =>
                  prepare('reporting.delete', { id: jobId }, `Delete daily reporting job ${jobId}.`)
                )}
              </Panel>
            )}
            {tab === 'capabilities' && (
              <>
                <Panel title='Independent creator capabilities'>
                  <div className='grid gap-3 sm:grid-cols-2'>
                    {Object.entries(capabilities || {}).map(([key, cap]) => (
                      <div className='rounded-md border p-3' key={key}>
                        <p className='font-medium text-sm'>{cap.label}</p>
                        <p className='mt-1 text-xs'>{cap.state}</p>
                        <p className='text-muted-foreground mt-1 text-xs'>{cap.reason}</p>
                      </div>
                    ))}
                  </div>
                </Panel>
                <Panel title='Enable a creator permission'>
                  {agenticConnection && (
                    <label className='flex items-start gap-2 text-sm'>
                      <input type='checkbox' aria-label='Approve separate agentic YouTube Analytics consent' checked={agenticAnalyticsConsent} disabled={busy || !owner}
                        onChange={(event) => setAgenticAnalyticsConsent(event.target.checked)} />
                      I authorize a separate Google consent flow to add read-only YouTube Analytics access to this selected autopilot authorization. This lets Rafii read authorized channel reports; it does not activate autopilot or grant revenue access.
                    </label>
                  )}
                  <div className='flex flex-wrap gap-2'>
                    {Object.entries({
                      publish: 'Video uploads',
                      manage_video: 'Video management and scheduling',
                      captions: 'Caption tracks',
                      playlists: 'Playlists and podcasts',
                      comments_read: 'Read comments',
                      reply: 'Comment replies',
                      moderate: 'Comment moderation',
                      analytics: 'Creator analytics',
                      live: 'Live creator tools',
                      reporting: 'Bulk reports'
                    }).map(([feature, label]) => (
                      <Button
                        variant='outline'
                        key={feature}
                        disabled={busy || !canManage || (agenticConnection && (feature !== 'analytics' || !owner || !agenticAnalyticsConsent))}
                        onClick={() => connect(feature)}
                      >
                        {label}
                      </Button>
                    ))}
                  </div>
                  <p className='text-xs text-muted-foreground'>
                    Google grants permissions incrementally. Revenue and memberships are
                    intentionally separate.
                    {agenticConnection && ' Select manual authorization for the other creator permission controls.'}
                  </p>
                  {(['monetary', 'memberships'] as const).map((cap) => (
                    <div className='flex flex-wrap gap-2' key={cap}>
                      <Button
                        variant='outline'
                        disabled={busy || !owner}
                        onClick={() =>
                          run(async () => {
                            await api.youtubeSensitive(
                              workspaceId,
                              channel,
                              cap,
                              !overview.data?.sensitiveAuthorizations[cap]
                            );
                            await client.invalidateQueries({
                              queryKey: ['youtube', workspaceId, channel]
                            });
                          })
                        }
                      >
                        {overview.data?.sensitiveAuthorizations[cap]
                          ? 'Disable'
                          : 'Intentionally enable'}{' '}
                        {cap === 'monetary' ? 'revenue analytics' : 'membership access'}
                      </Button>
                      {overview.data?.sensitiveAuthorizations[cap] && (
                        <Button
                          variant='outline'
                          disabled={busy || !owner || agenticConnection}
                          onClick={() =>
                            connect(cap === 'monetary' ? 'monetary_analytics' : 'memberships', true)
                          }
                        >
                          Grant {cap === 'monetary' ? 'revenue' : 'membership'} permission
                        </Button>
                      )}
                      {owner && overview.data?.sensitiveAuthorizations[cap] && (
                        <Button
                          variant='outline'
                          disabled={busy}
                          onClick={() =>
                            read(cap === 'monetary' ? 'revenue' : 'members', {
                              eligibilityProbe: true,
                              ...(cap === 'monetary' ? { startDate: start, endDate: end } : {})
                            })
                          }
                        >
                          Check authorized {cap === 'monetary' ? 'revenue' : 'membership'}{' '}
                          availability
                        </Button>
                      )}
                    </div>
                  ))}
                </Panel>
                <Panel title='Quota and official support'>
                  {overview.data?.operationalAlerts?.map((alert) => (
                    <p
                      key={alert.category + alert.observedAt}
                      role='status'
                      className='text-sm text-amber-700'
                    >
                      {alert.category}: {alert.method}
                      {alert.retryAt
                        ? ' · retry after ' + new Date(alert.retryAt * 1000).toLocaleString()
                        : ''}
                    </p>
                  ))}
                  <p className='text-sm'>
                    Actual project quota remaining:{' '}
                    {overview.data?.quota.remainingState || 'UNVERIFIED'}. Reset: midnight{' '}
                    {overview.data?.quota.resetTimeZone}.
                  </p>
                  <p className='text-muted-foreground text-xs'>{overview.data?.quota.note}</p>
                  <YouTubeQuotaControls admission={overview.data?.quota.admission} />
                  <p className='text-sm'>
                    Community Post publishing and native YouTube Articles are unsupported by the
                    official public API.
                  </p>
                  <p className='text-xs text-muted-foreground'>
                    Article adaptation requires a video, script conversion or a clearly labelled
                    external link.
                  </p>
                  <div className='flex gap-3 text-sm'>
                    <a
                      className='underline'
                      href='https://www.youtube.com/t/terms'
                      target='_blank'
                      rel='noreferrer'
                    >
                      YouTube Terms
                    </a>
                    <a
                      className='underline'
                      href='https://policies.google.com/privacy'
                      target='_blank'
                      rel='noreferrer'
                    >
                      Google Privacy
                    </a>
                    <Link className='underline' href='/app/account/privacy'>
                      Rafii privacy and disconnect
                    </Link>
                  </div>
                </Panel>
              </>
            )}
            {result?.nextPageToken &&
              lastRead &&
              command('Read next page', true, () =>
                read(lastRead.resource, { ...lastRead.query, pageToken: result.nextPageToken })
              )}
            {tab === 'live' && result?.items && (
              <details className='rounded-md border p-4'>
                <summary className='cursor-pointer text-sm'>
                  Official monitoring or chat event details
                </summary>
                <pre className='mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs'>
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            )}
            <CreatorReceipts key={`youtube-receipts:${channel}`} channel={channel} />
          </>
        )}
      </div>
    </PageContainer>
  );
}
