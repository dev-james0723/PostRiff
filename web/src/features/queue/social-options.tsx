'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { Asset } from '@/lib/api/types';
import type { PublishOptionsValue } from './publish-options';

export function SocialOptions({ platform, channelId, media, onChange }: {
  platform: string; channelId: string; media: Asset[]; onChange: (value: PublishOptionsValue) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const [destination, setDestination] = useState('');
  const [mode, setMode] = useState('standard');
  const [link, setLink] = useState('');
  const [parent, setParent] = useState('');
  const [quote, setQuote] = useState('');
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [choices, setChoices] = useState(['', '']);
  const [duration, setDuration] = useState('SEVEN_DAYS');
  const [attachment, setAttachment] = useState('');
  const [ghost, setGhost] = useState(false);
  const [thread, setThread] = useState('');
  const [gifId, setGifId] = useState('');
  const [locationId, setLocationId] = useState('');
  const [replyApprovals, setReplyApprovals] = useState(false);
  const [mediaSpoiler, setMediaSpoiler] = useState(false);
  const destinations = useQuery({ queryKey: ['social-destinations', workspaceId, channelId], queryFn: () => api.channelDestinations(workspaceId, channelId), enabled: platform === 'LinkedIn', retry: false });
  const inferred = media.length > 1 ? 'carousel' : media[0]?.mime.startsWith('video/') ? 'reel' : 'image';
  const selectedFormat = mode === 'standard' ? inferred : mode;
  const mediaKey = media.map((asset) => asset.id).join(',');

  useEffect(() => {
    const result: Record<string, unknown> = {};
    if (platform === 'LinkedIn') {
      const selected = destinations.data?.destinations.find((item) => item.id === destination);
      if (!selected) { onChange(null); return; }
      result.destinationType = selected.kind === 'organization' ? 'organization' : 'member';
      result.authorUrn = selected.id;
      if (title) result.title = title;
      if (mode === 'link') { if (!link.startsWith('https://')) { onChange(null); return; } result.link = link; }
      if (mode === 'poll') {
        if (!question || choices.some((choice) => !choice)) { onChange(null); return; }
        result.poll = { question, options: choices.map((text) => ({ text })), settings: { duration } };
      }
    }
    if (platform === 'Threads') {
      if (gifId) result.gif_attachment = { provider:'TENOR', gif_id:gifId };
      if (locationId) result.location_id = locationId;
      if (replyApprovals) result.enable_reply_approvals = true;
      if (mediaSpoiler) result.is_spoiler_media = true;
      if (parent) result.reply_to_id = parent;
      if (quote) result.quote_post_id = quote;
      if (link) result.link_attachment = link;
      if (ghost) result.is_ghost_post = true;
      if (mode === 'poll') {
        if (choices.some((choice) => !choice)) { onChange(null); return; }
        result.poll_attachment = Object.fromEntries(choices.map((text, index) => [`option_${String.fromCharCode(97+index)}`, text]));
      }
      if (mode === 'attachment') { if (!attachment) { onChange(null); return; } result.text_attachment = { plaintext: attachment }; }
    }
    if (platform === 'Instagram') result.format = selectedFormat;
    if (platform === 'Facebook') { result.format = mode === 'standard' ? 'feed' : mode; if (link) result.link = link; }
    if (platform === 'X') {
      if (parent) result.replyToId = parent;
      if (quote) result.quoteId = quote;
      if (thread.trim()) result.thread = thread.split('\n\n').map((post) => post.trim()).filter(Boolean);
      if (mode === 'poll') {
        if (choices.some((choice) => !choice)) { onChange(null); return; }
        result.poll = { options: choices, duration_minutes: 1440 };
      }
    }
    onChange(result);
  }, [platform, destination, destinations.data, mode, link, parent, quote, title, question, choices, duration, attachment, ghost, thread, gifId, locationId, replyApprovals, mediaSpoiler, selectedFormat, mediaKey, onChange]);

  const formats = platform === 'Instagram' ? [['standard', 'Automatic format'], ['image', 'Image'], ['carousel', 'Carousel'], ['reel', 'Reel'], ['story', 'Story']]
    : platform === 'Facebook' ? [['standard', 'Page feed'], ['reel', 'Reel'], ['story', 'Story']]
      : platform === 'Threads' ? [['standard', 'Text or media'], ['poll', 'Poll'], ['attachment', 'Long text attachment']]
        : platform === 'LinkedIn' ? [['standard', 'Text or media'], ['link', 'Link'], ['poll', 'Poll']]
          : [['standard', 'Post'], ['poll', 'Poll']];
  return (
    <section className='flex flex-col gap-3 rounded-xl border p-3' aria-label={`${platform} publishing choices`}>
      <h3 className='text-sm font-medium'>{platform} choices</h3>
      {platform === 'LinkedIn' && <div className='flex flex-col gap-1.5'><Label htmlFor='social-destination'>Publish as</Label><Select value={destination} onValueChange={(value) => setDestination(value ?? '')}><SelectTrigger id='social-destination'><SelectValue placeholder='Choose member or Organization' /></SelectTrigger><SelectContent>{destinations.data?.destinations.map((item) => <SelectItem key={item.id} value={item.id}>{item.name} · {item.kind}</SelectItem>)}</SelectContent></Select>{destinations.isError && <p role='alert' className='text-xs'>Could not verify destinations. Enable organization discovery separately if needed.</p>}</div>}
      <div className='flex flex-col gap-1.5'><Label htmlFor='social-format'>Format</Label><Select value={mode} onValueChange={(value) => setMode(value ?? 'standard')}><SelectTrigger id='social-format'><SelectValue /></SelectTrigger><SelectContent>{formats.map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select></div>
      {(platform === 'LinkedIn' && mode === 'link' || platform === 'Threads' && mode === 'standard' || platform === 'Facebook' && mode === 'standard') && <div><Label htmlFor='social-link'>Link {platform === 'LinkedIn' ? '' : '(optional)'}</Label><Input id='social-link' type='url' value={link} onChange={(event) => setLink(event.target.value)} /></div>}
      {platform === 'LinkedIn' && <div><Label htmlFor='social-title'>Media or link title (optional)</Label><Input id='social-title' value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} /></div>}
      {mode === 'poll' && <div className='flex flex-col gap-2'>
        {platform === 'LinkedIn' && <div><Label htmlFor='poll-question'>Poll question</Label><Input id='poll-question' value={question} maxLength={140} onChange={(event) => setQuestion(event.target.value)} /></div>}
        {choices.map((choice, index) => <div key={index}><Label htmlFor={`poll-option-${index}`}>Option {index+1}</Label><Input id={`poll-option-${index}`} value={choice} maxLength={platform === 'LinkedIn' ? 30 : 25} onChange={(event) => setChoices((old) => old.map((value, at) => at === index ? event.target.value : value))} /></div>)}
        <div className='flex gap-3'>{choices.length < 4 && <button type='button' className='rafii-focus text-sm underline' onClick={() => setChoices([...choices, ''])}>Add option</button>}{choices.length > 2 && <button type='button' className='rafii-focus text-sm underline' onClick={() => setChoices(choices.slice(0,-1))}>Remove last option</button>}</div>
        {platform === 'LinkedIn' && <Select value={duration} onValueChange={(value) => setDuration(value ?? 'SEVEN_DAYS')}><SelectTrigger aria-label='Poll duration'><SelectValue /></SelectTrigger><SelectContent>{[['ONE_DAY','1 day'],['THREE_DAYS','3 days'],['SEVEN_DAYS','7 days'],['FOURTEEN_DAYS','14 days']].map(([value,label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent></Select>}
        <p className='text-muted-foreground text-xs'>Polls cannot include media. X polls here run for one day.</p>
      </div>}
      {['Threads','X'].includes(platform) && <><div><Label htmlFor='social-parent'>Reply to post ID (optional)</Label><Input id='social-parent' value={parent} onChange={(event) => setParent(event.target.value)} /></div><div><Label htmlFor='social-quote'>Quote post ID (optional)</Label><Input id='social-quote' value={quote} onChange={(event) => setQuote(event.target.value)} /></div></>}
      {platform === 'Threads' && mode === 'attachment' && <div><Label htmlFor='threads-attachment'>Long text attachment</Label><Textarea id='threads-attachment' value={attachment} maxLength={10000} onChange={(event) => setAttachment(event.target.value)} /></div>}
      {platform === 'Threads' && <Label className='flex items-center gap-2'><Checkbox checked={ghost} onCheckedChange={(value) => setGhost(value === true)} />Ghost post · disappears after 24 hours</Label>}
      {platform === 'Threads' && <details><summary className='text-sm'>Additional Threads options</summary><div className='mt-3 flex flex-col gap-3'><div><Label htmlFor='threads-gif'>Tenor GIF ID (text posts)</Label><Input id='threads-gif' value={gifId} onChange={(event) => setGifId(event.target.value)} /></div><div><Label htmlFor='threads-location'>Threads location ID (separate permission)</Label><Input id='threads-location' value={locationId} onChange={(event) => setLocationId(event.target.value)} /></div><Label className='flex items-center gap-2'><Checkbox checked={replyApprovals} onCheckedChange={(value) => setReplyApprovals(value === true)} />Approve replies before they appear</Label>{media.length > 0 && <Label className='flex items-center gap-2'><Checkbox checked={mediaSpoiler} onCheckedChange={(value) => setMediaSpoiler(value === true)} />Mark attached media as a spoiler</Label>}</div></details>}
      {platform === 'X' && <div><Label htmlFor='x-thread'>Additional thread posts (optional)</Label><Textarea id='x-thread' value={thread} onChange={(event) => setThread(event.target.value)} /><p className='text-muted-foreground text-xs'>Separate each post with a blank line. Each requires a paid API request.</p></div>}
      {selectedFormat === 'story' && ['Instagram','Facebook'].includes(platform) && <p className='text-muted-foreground text-xs'>The review will publish media without the draft caption. Instagram Stories require an eligible Business account.</p>}
    </section>
  );
}
