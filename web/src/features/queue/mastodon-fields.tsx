'use client';

import { useEffect, useId, useState } from 'react';
import type { NativeDraft } from '@/lib/creation/capabilities';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function MastodonFields({ onChange, nativeDraft, text = '' }: { onChange: (options: Record<string, unknown> | null) => void; nativeDraft?: NativeDraft | null; text?: string }) {
  const requiredPoll = nativeDraft?.formatId === 'mastodon.poll';
  const rawAnswers = nativeDraft?.fields?.options;
  const draftAnswers = Array.isArray(rawAnswers) ? rawAnswers.map((choice: unknown, index) => {
    if (typeof choice === 'string') return choice;
    if (choice && typeof choice === 'object' && 'index' in choice && 'text' in choice && choice.index === index + 1 && Object.keys(choice).length === 2 && typeof choice.text === 'string') return choice.text;
    return null;
  }) : [];
  const validDraft = !requiredPoll || (nativeDraft?.fields?.question === text && Array.isArray(rawAnswers) && draftAnswers.every((choice) => typeof choice === 'string' && choice === choice.trim()));
  const answerLabel = requiredPoll ? 'Poll answers (one answer per line)' : 'Poll answers (optional, one answer per line)';
  const fieldId = useId();
  const [visibility, setVisibility] = useState('public');
  const [warning, setWarning] = useState('');
  const [sensitive, setSensitive] = useState(false);
  const [reply, setReply] = useState('');
  const [quote, setQuote] = useState('');
  const [poll, setPoll] = useState(requiredPoll && Array.isArray(draftAnswers) ? draftAnswers.join('\n') : '');
  const [pollSeconds, setPollSeconds] = useState('86400');
  const [multiple, setMultiple] = useState(false);
  const [hideTotals, setHideTotals] = useState(false);
  useEffect(() => {
    if (!validDraft || (requiredPoll && !poll)) { onChange(null); return; }
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
      ...(poll ? { poll: { options: choices, expires_in: seconds, multiple, hide_totals: hideTotals } } : {}) });
  }, [visibility, warning, sensitive, reply, quote, poll, pollSeconds, multiple, hideTotals, onChange, requiredPoll, validDraft]);
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
      <Label htmlFor={fieldId + '-poll'}>{answerLabel}</Label>
      <textarea aria-label={answerLabel} id={fieldId + '-poll'} className='min-h-20 rounded border p-2' value={poll} readOnly={requiredPoll} onChange={(event) => setPoll(event.target.value)} />
      {requiredPoll && <p className='text-muted-foreground text-xs'>{validDraft ? 'These answers come from this native draft. Create a new native draft to change them.' : 'This draft needs an exact question and an ordered answer list before it can be reviewed.'}</p>}
      {poll && <>
        <Label htmlFor={fieldId + '-poll-duration'}>Poll duration in seconds</Label>
        <Input id={fieldId + '-poll-duration'} type='number' min={300} max={2629746} value={pollSeconds} onChange={(event) => setPollSeconds(event.target.value)} />
        <label htmlFor={fieldId + '-poll-multiple'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-poll-multiple'} checked={multiple} onCheckedChange={(value) => setMultiple(value === true)} />Allow multiple answers</label>
        <label htmlFor={fieldId + '-poll-hidden'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-poll-hidden'} checked={hideTotals} onCheckedChange={(value) => setHideTotals(value === true)} />Hide vote totals until the poll ends</label>
        <p className='text-muted-foreground text-xs'>Polls cannot include media. Choose 2–4 answers of up to 50 characters; the server may apply lower limits.</p>
      </>}
      <p className='text-muted-foreground text-xs'>Quote availability and posting limits depend on your server. Private Mentions are visible to mentioned accounts. Federation delivery may take time.</p>
    </section>
  );
}
