'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ApiError } from '@/lib/api/client';
import type { Asset } from '@/lib/api/types';
import {
  commercialLabel,
  consentText,
  initialChoice,
  interactionDisabled,
  PRIVACY_LABELS,
  privacyDisabled,
  problems,
  PROCESSING_NOTICE,
  toOptions,
  UNAUDITED_NOTICE,
  withCommercial,
  type TikTokChoice,
  type TikTokPrivacy
} from '@/lib/channels/tiktok-rules';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/** Platforms whose review carries per-post choices; the server refuses a review without them. */
export const NEEDS_OPTIONS = new Set(['TikTok', 'YouTube', 'Pinterest']);

export type PublishOptionsValue = Record<string, unknown> | null;

interface Props {
  platform: string;
  channelId: string;
  asset: Asset | undefined;
  text: string;
  /** Called with the complete options, or null while something is still missing. */
  onChange: (options: PublishOptionsValue) => void;
}

function Caution({ children }: { children: ReactNode }) {
  return (
    <p className='text-muted-foreground flex items-start gap-1.5 text-xs'>
      <Icons.warning aria-hidden className='mt-0.5 size-3.5 shrink-0' />
      <span className='min-w-0'>{children}</span>
    </p>
  );
}

export function PublishOptions(props: Props) {
  if (props.platform === 'TikTok') return <TikTokFields {...props} />;
  if (props.platform === 'YouTube') return <YouTubeFields {...props} />;
  if (props.platform === 'Pinterest') return <PinterestFields {...props} />;
  return null;
}

const isVideo = (asset: Asset | undefined) => Boolean(asset && asset.mime.startsWith('video/'));

/** TikTok Content Sharing Guidelines: creator shown, no privacy default, interactions off, disclosure, exact consent. */
function TikTokFields({ channelId, asset, text, onChange }: Props) {
  const { api, workspaceId } = useWorkspaceApi();
  const [choice, setChoice] = useState<TikTokChoice>(initialChoice);
  // Read fresh every time the composer opens: the creator's settings can change on TikTok at any moment.
  const creator = useQuery({
    queryKey: ['tiktok-creator-info', workspaceId, channelId],
    queryFn: () => api.creatorInfo(workspaceId, channelId),
    staleTime: 0,
    refetchOnMount: 'always',
    retry: false
  });
  const info = creator.data ?? null;
  const durationSec = isVideo(asset) ? (asset?.duration ?? null) : null;
  const video = isVideo(asset) ? { durationSec } : null;
  const issues = problems(choice, info, video);
  const branded = choice.commercial.enabled && choice.commercial.brandedContent;

  useEffect(() => {
    onChange(toOptions(choice, info, isVideo(asset) ? { durationSec } : null));
  }, [choice, info, asset, durationSec, onChange]);

  const interaction = (kind: 'comment' | 'duet' | 'stitch', key: 'allowComment' | 'allowDuet' | 'allowStitch', label: string) => (
    <Label className='flex items-center gap-2 text-sm font-normal'>
      <Checkbox
        checked={choice[key]}
        disabled={interactionDisabled(kind, info)}
        onCheckedChange={(value) => setChoice((current) => ({ ...current, [key]: value === true }))}
      />
      <span className={interactionDisabled(kind, info) ? 'text-muted-foreground' : undefined}>{label}</span>
    </Label>
  );

  return (
    <section className='flex flex-col gap-3 rounded-[var(--rafii-radius-control)] border p-3' aria-labelledby='tiktok-options-title'>
      <h3 id='tiktok-options-title' className='text-sm font-medium'>
        TikTok
      </h3>
      {creator.isLoading && <p className='text-muted-foreground text-xs'>Checking your TikTok settings…</p>}
      {creator.isError && <Caution>{creator.error instanceof ApiError ? creator.error.message : 'Couldn’t read your TikTok settings. Try again.'}</Caution>}
      {info && (
        <p className='text-sm'>
          Posting as <span className='font-medium'>{info.nickname || info.username}</span>
          {info.username ? <span className='text-muted-foreground'> (@{info.username})</span> : null}
        </p>
      )}

      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='tiktok-privacy'>Who can see this post</Label>
        <Select value={choice.privacyLevel ?? ''} onValueChange={(value) => setChoice((current) => ({ ...current, privacyLevel: (value || null) as TikTokPrivacy | null }))}>
          <SelectTrigger id='tiktok-privacy' className='w-full'>
            <SelectValue placeholder='Choose who can see it' />
          </SelectTrigger>
          <SelectContent>
            {(info?.privacyLevelOptions ?? []).map((level) => (
              <SelectItem key={level} value={level} disabled={privacyDisabled(level, choice)}>
                {PRIVACY_LABELS[level as TikTokPrivacy] ?? level}
                {privacyDisabled(level, choice) ? ' (not for branded content)' : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <fieldset className='flex flex-col gap-1.5'>
        <legend className='mb-1 text-sm font-medium'>Allow people to</legend>
        {interaction('comment', 'allowComment', 'Comment')}
        {interaction('duet', 'allowDuet', 'Duet')}
        {interaction('stitch', 'allowStitch', 'Stitch')}
      </fieldset>

      <div className='flex flex-col gap-1.5'>
        <Label className='flex items-center gap-2 text-sm font-normal'>
          <Checkbox checked={choice.commercial.enabled} onCheckedChange={(value) => setChoice((current) => withCommercial(current, { enabled: value === true }))} />
          <span>Disclose commercial content</span>
        </Label>
        {choice.commercial.enabled && (
          <div className='flex flex-col gap-1.5 pl-6'>
            <Label className='flex items-start gap-2 text-sm font-normal'>
              <Checkbox checked={choice.commercial.yourBrand} onCheckedChange={(value) => setChoice((current) => withCommercial(current, { yourBrand: value === true }))} />
              <span>
                Your brand
                <span className='text-muted-foreground block text-xs'>You are promoting yourself or your own business.</span>
              </span>
            </Label>
            <Label className='flex items-start gap-2 text-sm font-normal'>
              <Checkbox checked={choice.commercial.brandedContent} onCheckedChange={(value) => setChoice((current) => withCommercial(current, { brandedContent: value === true }))} />
              <span>
                Branded content
                <span className='text-muted-foreground block text-xs'>You are promoting another brand or a third party.</span>
              </span>
            </Label>
            {commercialLabel(choice) && <p className='text-xs'>{commercialLabel(choice)}</p>}
          </div>
        )}
      </div>

      <div className='flex flex-col gap-1'>
        <span className='text-muted-foreground text-xs'>Preview</span>
        <div className='rafii-quiet rounded-md p-2 text-sm whitespace-pre-wrap'>{text || 'No caption'}</div>
        <span className='text-muted-foreground text-xs'>{isVideo(asset) ? `Video${durationSec ? ` · ${Math.round(durationSec)} s` : ''}` : 'No video chosen'}</span>
      </div>

      <Caution>{UNAUDITED_NOTICE}</Caution>
      <p className='text-muted-foreground text-xs'>{PROCESSING_NOTICE}</p>

      <Label className='flex items-start gap-2 text-sm font-normal'>
        <Checkbox checked={choice.consent} onCheckedChange={(value) => setChoice((current) => ({ ...current, consent: value === true }))} />
        <span>{consentText(branded)}</span>
      </Label>

      {issues.length > 0 && (
        <ul className='text-muted-foreground flex flex-col gap-0.5 text-xs' aria-label='Still needed for TikTok'>
          {issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function YouTubeFields({ asset, onChange }: Props) {
  const [title, setTitle] = useState('');
  const [privacy, setPrivacy] = useState('');
  const [audience, setAudience] = useState<'' | 'kids' | 'not-kids'>('');
  const titleOk = title.trim().length > 0 && !/[<>]/.test(title);

  useEffect(() => {
    onChange(isVideo(asset) && titleOk && privacy && audience ? { title: title.trim(), privacyStatus: privacy, madeForKids: audience === 'kids' } : null);
  }, [asset, title, titleOk, privacy, audience, onChange]);

  return (
    <section className='flex flex-col gap-3 rounded-[var(--rafii-radius-control)] border p-3' aria-labelledby='youtube-options-title'>
      <h3 id='youtube-options-title' className='text-sm font-medium'>
        YouTube
      </h3>
      {!isVideo(asset) && <Caution>YouTube needs one video. Rafii can’t upload videos yet.</Caution>}
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='youtube-title'>Title</Label>
        <Input id='youtube-title' className='text-base md:text-sm' value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
        {/[<>]/.test(title) && <Caution>YouTube titles can’t contain &lt; or &gt;.</Caution>}
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='youtube-privacy'>Visibility</Label>
        <Select value={privacy} onValueChange={(value) => setPrivacy(value ?? '')}>
          <SelectTrigger id='youtube-privacy' className='w-full'>
            <SelectValue placeholder='Choose visibility' />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value='private'>Private</SelectItem>
            <SelectItem value='unlisted'>Unlisted</SelectItem>
            <SelectItem value='public'>Public</SelectItem>
          </SelectContent>
        </Select>
        <Caution>Until Google audits Rafii, YouTube keeps every upload private, whatever you choose.</Caution>
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label id='youtube-audience'>Audience</Label>
        <RadioGroup aria-labelledby='youtube-audience' value={audience} onValueChange={(value) => setAudience(value as 'kids' | 'not-kids')}>
          <Label className='flex items-center gap-2 text-sm font-normal'>
            <RadioGroupItem value='not-kids' />
            <span>No, it’s not made for kids</span>
          </Label>
          <Label className='flex items-center gap-2 text-sm font-normal'>
            <RadioGroupItem value='kids' />
            <span>Yes, it’s made for kids</span>
          </Label>
        </RadioGroup>
      </div>
    </section>
  );
}

function PinterestFields({ channelId, asset, onChange }: Props) {
  const { api, workspaceId } = useWorkspaceApi();
  const [board, setBoard] = useState('');
  const [title, setTitle] = useState('');
  const [link, setLink] = useState('');
  const boards = useQuery({
    queryKey: ['pinterest-boards', workspaceId, channelId],
    queryFn: () => api.channelDestinations(workspaceId, channelId),
    retry: false
  });
  const image = Boolean(asset && asset.mime.startsWith('image/'));
  const linkOk = !link || /^https?:\/\/\S+$/i.test(link);

  useEffect(() => {
    onChange(image && board && linkOk ? { boardId: board, title: title.trim(), link: link.trim() } : null);
  }, [image, board, title, link, linkOk, onChange]);

  return (
    <section className='flex flex-col gap-3 rounded-[var(--rafii-radius-control)] border p-3' aria-labelledby='pinterest-options-title'>
      <h3 id='pinterest-options-title' className='text-sm font-medium'>
        Pinterest
      </h3>
      {!image && <Caution>A Pin needs one image. Choose it above.</Caution>}
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='pinterest-board'>Board</Label>
        <Select value={board} onValueChange={(value) => setBoard(value ?? '')}>
          <SelectTrigger id='pinterest-board' className='w-full'>
            <SelectValue placeholder={boards.isLoading ? 'Loading boards…' : 'Choose a board'} />
          </SelectTrigger>
          <SelectContent>
            {(boards.data?.destinations ?? []).map((item) => (
              <SelectItem key={item.id} value={item.id}>
                {item.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {boards.isError && <Caution>{boards.error instanceof ApiError ? boards.error.message : 'Couldn’t load your boards. Try again.'}</Caution>}
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='pinterest-title'>Title (optional)</Label>
        <Input id='pinterest-title' className='text-base md:text-sm' value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div className='flex flex-col gap-1.5'>
        <Label htmlFor='pinterest-link'>Link (optional)</Label>
        <Input id='pinterest-link' className='text-base md:text-sm' value={link} inputMode='url' placeholder='https://' onChange={(e) => setLink(e.target.value)} />
        {!linkOk && <Caution>Use a web address that starts with https://.</Caution>}
      </div>
    </section>
  );
}
