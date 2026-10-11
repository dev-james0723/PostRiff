'use client';

import { useEffect, useId, useState } from 'react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function MastodonFields({ onChange }: { onChange: (options: Record<string, unknown> | null) => void }) {
  const fieldId = useId();
  const [visibility, setVisibility] = useState('public');
  const [warning, setWarning] = useState('');
  const [sensitive, setSensitive] = useState(false);
  const [reply, setReply] = useState('');
  const [quote, setQuote] = useState('');
  const [poll, setPoll] = useState('');
  const [pollSeconds, setPollSeconds] = useState('86400');
  const [multiple, setMultiple] = useState(false);
  useEffect(() => {
    if ((reply && !/^\d{1,40}$/.test(reply)) || (quote && !/^\d{1,40}$/.test(quote))) {
      onChange(null);
      return;
    }
    const choices = poll.split('\n').map((choice) => choice.trim()).filter(Boolean);
    const seconds = Number(pollSeconds);
    if (poll && (choices.length < 2 || choices.length > 4 || choices.some((choice) => choice.length > 50) || !Number.isInteger(seconds) || seconds < 300 || seconds > 2629746)) {
      onChange(null);
      return;
    }
    onChange({ visibility, spoiler_text: warning, sensitive,
      ...(reply ? { in_reply_to_id: reply } : {}), ...(quote ? { quoted_status_id: quote } : {}),
      ...(poll ? { poll: { options: choices, expires_in: seconds, multiple, hide_totals: false } } : {}) });
  }, [visibility, warning, sensitive, reply, quote, poll, pollSeconds, multiple, onChange]);
  return (
    <section className='flex flex-col gap-3 rounded-[var(--rafii-radius-control)] border p-3' aria-label='Mastodon post settings'>
      <Label htmlFor={fieldId + '-visibility'}>Who can see this post</Label>
      <Select value={visibility} onValueChange={(value) => setVisibility(String(value))}>
        <SelectTrigger id={fieldId + '-visibility'}><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value='public'>Public</SelectItem>
          <SelectItem value='unlisted'>Unlisted</SelectItem>
          <SelectItem value='private'>Followers-only</SelectItem>
          <SelectItem value='direct'>Private Mentions</SelectItem>
        </SelectContent>
      </Select>
      <Label htmlFor={fieldId + '-warning'}>Content warning</Label>
      <Input id={fieldId + '-warning'} value={warning} onChange={(event) => setWarning(event.target.value)} maxLength={5000} />
      <label htmlFor={fieldId + '-sensitive'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-sensitive'} checked={sensitive} onCheckedChange={(value) => setSensitive(value === true)} />Sensitive media</label>
      <Label htmlFor={fieldId + '-reply'}>Reply to post ID (optional)</Label>
      <Input id={fieldId + '-reply'} inputMode='numeric' value={reply} onChange={(event) => setReply(event.target.value)} />
      <Label htmlFor={fieldId + '-quote'}>Quote post ID (optional)</Label>
      <Input id={fieldId + '-quote'} inputMode='numeric' value={quote} onChange={(event) => setQuote(event.target.value)} />
      <Label htmlFor={fieldId + '-poll'}>Poll answers (optional, one answer per line)</Label>
      <textarea aria-label='Poll answers (optional, one answer per line)' id={fieldId + '-poll'} className='min-h-20 rounded border p-2' value={poll} onChange={(event) => setPoll(event.target.value)} />
      {poll && <>
        <Label htmlFor={fieldId + '-poll-duration'}>Poll duration in seconds</Label>
        <Input id={fieldId + '-poll-duration'} type='number' min={300} max={2629746} value={pollSeconds} onChange={(event) => setPollSeconds(event.target.value)} />
        <label htmlFor={fieldId + '-poll-multiple'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-poll-multiple'} checked={multiple} onCheckedChange={(value) => setMultiple(value === true)} />Allow multiple answers</label>
        <p className='text-muted-foreground text-xs'>Polls cannot include media. Choose 2–4 answers of up to 50 characters; the server may apply lower limits.</p>
      </>}
      <p className='text-muted-foreground text-xs'>Quote availability and posting limits depend on your server. Private Mentions are visible to mentioned accounts. Federation delivery may take time.</p>
    </section>
  );
}
