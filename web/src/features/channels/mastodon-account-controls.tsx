'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { MastodonProfileFields, type ProfileEdit } from './mastodon-profile-fields';
import { MastodonFields } from '@/features/queue/mastodon-fields';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { MastodonPollView } from '@/lib/api/client';

const actions = [
  ['edit', 'Edit post'], ['delete', 'Delete post'], ['favourite', 'Favourite'], ['unfavourite', 'Undo favourite'],
  ['reblog', 'Boost'], ['unreblog', 'Undo boost'], ['bookmark', 'Bookmark'], ['unbookmark', 'Remove bookmark'],
  ['follow', 'Follow account'], ['unfollow', 'Unfollow account'], ['mute', 'Mute account'], ['unmute', 'Unmute account'],
  ['block', 'Block account'], ['unblock', 'Unblock account'], ['poll_vote', 'Vote on poll'], ['profile_update', 'Edit profile'],
  ['native_schedule', 'Schedule on Mastodon'], ['native_reschedule', 'Reschedule on Mastodon'], ['native_cancel', 'Cancel server schedule'],
  ['list_create', 'Create list'], ['list_update', 'Rename list'], ['list_delete', 'Delete list'],
  ['list_add', 'Add accounts to list'], ['list_remove', 'Remove accounts from list'],
  ['report_account', 'Report account'], ['filter_create', 'Create content filter'],
  ['filter_update', 'Update content filter'], ['filter_delete', 'Delete content filter']
] as const;
type Preview = { actionId: string; digest: string; preview: { accountId: string; instance: string; action: string; targetId?: string; body: Record<string, unknown>; reportRules?: { id: string; text: string }[]; pollSnapshot?: { id: string; multiple: boolean; expiresAt: string | null; options: { index: number; title: string }[] }; media?: Record<string, { id: string; hash: string; bytes: number }> } };

function readable(value: unknown): string {
  if (Array.isArray(value)) return value.map(readable).join(', ');
  if (value && typeof value === 'object') return Object.entries(value).map(([key, entry]) => `${key.replaceAll('_', ' ')}: ${readable(entry)}`).join(' · ');
  return String(value ?? 'Unavailable').replace(/<[^>]*>/g, '');
}

function AccountData({ value }: { value: Record<string, unknown> }) {
  const rows = Array.isArray(value.posts) ? value.posts : Array.isArray(value.data) ? value.data : null;
  const single = value.capabilities ?? (rows ? null : value.data) ?? value;
  return (
    <div className='max-h-64 overflow-auto rounded border p-3 text-xs'>
      {['followers', 'following', 'postCount'].filter((key) => value[key] != null).map((key) => <p key={key}><span className='font-medium'>{key}: </span>{readable(value[key])}</p>)}
      {Boolean(value.coverage) && <p className='mb-2'>{String(value.coverage)}</p>}
      {value.resource === 'live_events' && <p role='status' className='mb-2'>Live updates: {String(value.state ?? 'unavailable')}. {typeof value.reason === 'string' ? value.reason : 'Only this foreground window was read; use notifications for missed events.'}</p>}
      {rows ? rows.length ? rows.map((item, index) => {
        const row = item && typeof item === 'object' ? item as Record<string, unknown> : {};
        const fields = ['id', 'event', 'excerpt', 'title', 'text', 'name', 'username', 'createdAt', 'created_at', 'scheduled_at', 'visibility', 'content', 'poll', 'favourites', 'boosts', 'replies', 'quotes', 'context', 'filter_action', 'keywords', 'expires_at', 'type', 'postId', 'metric', 'value', 'observedAt', 'readOffset'];
        return <div key={String(row.id ?? index)} className='mb-3 border-b pb-2'>{fields.filter((key) => row[key] != null).map((key) => <p key={key}><span className='font-medium'>{key.replaceAll('_', ' ')}: </span>{readable(row[key])}</p>)}</div>;
      }) : <p>No items in this server page.</p> : single && typeof single === 'object' ? Object.entries(single).map(([key, entry]) => <p key={key}><span className='font-medium'>{key.replaceAll('_', ' ')}: </span>{readable(entry)}</p>) : <p>{readable(single)}</p>}
    </div>
  );
}

export function MastodonAccountControls({ connectionId, account }: { connectionId: string; account: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const fieldId = useId();
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const [action, setAction] = useState('favourite');
  const [target, setTarget] = useState('');
  const [text, setText] = useState('');
  const [profileEdit, setProfileEdit] = useState<ProfileEdit>({ profile: {}, profileMedia: {} });
  const [scheduledAt, setScheduledAt] = useState('');
  const [title, setTitle] = useState('');
  const [accountIds, setAccountIds] = useState('');
  const [reportForward, setReportForward] = useState(false);
  const [reportCategory, setReportCategory] = useState('other');
  const [reportRuleIds, setReportRuleIds] = useState('');
  const [filterContexts, setFilterContexts] = useState<string[]>([]);
  const [filterPolicy, setFilterPolicy] = useState('keep');
  const [filterExpiry, setFilterExpiry] = useState('');
  const [filterNeverExpires, setFilterNeverExpires] = useState(false);
  const [wholeWord, setWholeWord] = useState(false);
  const [poll, setPoll] = useState<MastodonPollView | null>(null);
  const [pollChoices, setPollChoices] = useState<number[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [details, setDetails] = useState<Record<string, unknown> | null>(null);
  const [options, setOptions] = useState<Record<string, unknown> | null>({});
  const [url, setUrl] = useState<string | null>(null);
  const needsText = ['edit', 'native_schedule', 'report_account', 'filter_create', 'filter_update'].includes(action);
  const needsTime = ['native_schedule', 'native_reschedule'].includes(action);
  const needsTarget = !['profile_update', 'native_schedule', 'list_create', 'filter_create'].includes(action);
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const actionId = query.get('mastodonAction');
    if (query.get('connection') !== connectionId || !actionId) return;
    let current = true;
    void api.mastodonSavedPreview(workspaceId, connectionId, actionId).then((saved) => {
      if (current) { setPreview(saved); if (detailsRef.current) detailsRef.current.open = true; }
    }).catch((error) => {
      if (current) setMessage(error instanceof Error ? error.message : 'Preview unavailable.');
    });
    return () => { current = false; };
  }, [api, workspaceId, connectionId]);
  async function read(resource: string) {
    setBusy(true); setMessage(''); setUrl(null);
    try { setDetails(await api.mastodonRead(workspaceId, connectionId, resource)); }
    catch (error) { setMessage(error instanceof Error ? error.message : 'Could not read this account.'); }
    finally { setBusy(false); }
  }
  async function prepare() {
    setBusy(true); setMessage(''); setUrl(null);
    try {
      const payload: Record<string, unknown> = { action, targetId: target, text, title, options };
      if (['edit', 'native_schedule'].includes(action) && options === null) throw new Error('Check the Mastodon post settings.');
      if (action === 'profile_update') Object.assign(payload, profileEdit);
      if (action === 'poll_vote') {
        if (!poll || poll.id !== target || poll.expired || poll.voted !== false || !pollChoices.length) throw new Error('Read the exact poll and select your answers first.');
        payload.pollChoices = pollChoices;
      }
      if (action === 'list_add' || action === 'list_remove') payload.account_ids = accountIds.split(',').map((id) => id.trim()).filter(Boolean);
      if (action === 'report_account') Object.assign(payload, {
        reportComment: text, reportForward, reportCategory,
        reportStatusIds: accountIds.split(',').map((id) => id.trim()).filter(Boolean),
        ...(reportCategory === 'violation' ? { reportRuleIds: reportRuleIds.split(',').map((id) => id.trim()).filter(Boolean) } : {})
      });
      if (action === 'filter_create' || action === 'filter_update') payload.filter = {
        ...(title.trim() ? { title } : {}), ...(filterContexts.length ? { context: filterContexts } : {}),
        ...(filterPolicy !== 'keep' ? { filter_action: filterPolicy } : {}),
        ...(filterNeverExpires ? { expires_in: null } : filterExpiry ? { expires_in: Number(filterExpiry) } : {}),
        ...(text.trim() ? { keywords_attributes: text.split('\n').map((keyword) => keyword.trim()).filter(Boolean).map((keyword) => ({ keyword, whole_word: wholeWord })) } : {})
      };
      if (needsTime) {
        const at = new Date(scheduledAt);
        if (!Number.isFinite(at.getTime())) throw new Error('Choose a valid schedule time.');
        payload.scheduled_at = at.toISOString();
      }
      setPreview(await api.mastodonPreview(workspaceId, connectionId, payload));
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not prepare this action.'); }
    finally { setBusy(false); }
  }
  async function approve() {
    if (!preview) return;
    setBusy(true);
    try {
      const result = await api.mastodonApprove(workspaceId, connectionId, preview.actionId, preview.digest);
      setMessage(`${result.state}: ${result.reason ?? result.publication ?? 'Mastodon returned an action receipt.'}${action === 'report_account' ? ' A report receipt is not a moderation decision.' : ''}`);
      setUrl(result.url ?? null); setPreview(null);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Outcome unavailable. Check Mastodon before trying again.'); }
    finally { setBusy(false); }
  }
  async function readPoll() {
    setBusy(true); setMessage(''); setPoll(null); setPollChoices([]);
    try {
      if (!/^[0-9]{1,40}$/.test(target)) throw new Error('Enter the poll ID from a Mastodon status.');
      const result = await api.mastodonPoll(workspaceId, connectionId, target);
      setPoll(result.data); setDetails(result);
    } catch (error) { setMessage(error instanceof Error ? error.message : 'This poll is unavailable.'); }
    finally { setBusy(false); }
  }
  return (
    <details ref={detailsRef} className='rounded-[var(--rafii-radius-control)] border p-3'>
      <summary className='rafii-focus cursor-pointer text-sm'>Mastodon account controls</summary>
      <div className='mt-3 flex flex-col gap-3'>
        <p className='text-muted-foreground text-xs'>All requests use {account}. Private content stays within this workspace. Server schedules publish on your instance; Rafii-managed schedules send at your approved calendar time.</p>
        <div className='flex flex-wrap gap-2'>
          {['health', 'capabilities', 'analytics', 'posts', 'notifications', 'live_events', 'scheduled', 'lists', 'bookmarks', 'profile', 'home', 'preferences', 'favourites', 'mutes', 'blocks', 'filters', 'rules', 'trending_tags', 'trending_statuses'].map((resource) => (
            <Button key={resource} variant='outline' size='sm' disabled={busy} onClick={() => void read(resource)}>{resource === 'live_events' ? 'Read live updates' : resource.replace('_', ' ')}</Button>
          ))}
        </div>
        {details && <AccountData value={details} />}
        {details?.historicalTrends && typeof details.historicalTrends === 'object' ? <AccountData value={{ data: (details.historicalTrends as Record<string, unknown>).readings, coverage: (details.historicalTrends as Record<string, unknown>).coverage }} /> : null}
        {preview ? (
          <div className='flex flex-col gap-2 rounded border p-3'>
            <p className='text-sm'>Approve {preview.preview.action.replaceAll('_', ' ')} for {preview.preview.accountId} on {preview.preview.instance}</p>
            {preview.preview.targetId && <p className='text-sm'>Target ID: {preview.preview.targetId}</p>}
            {preview.preview.action === 'report_account' && <p className='text-sm'>This files a report; it does not apply a moderation decision. {preview.preview.body.forward === true ? 'You are approving forwarding this report to the reported account’s server moderators.' : 'Forwarding to the reported account’s server moderators is off.'} Rafii cannot retract a filed report.</p>}
            <div className='max-h-40 overflow-auto text-sm'>{Object.entries(preview.preview.body).map(([key, value]) => <p key={key}><span className='font-medium'>{key.replaceAll('_', ' ')}: </span>{key === 'expires_in' && value === null ? 'Never expire (clear any current expiry)' : readable(value)}</p>)}</div>
            {preview.preview.reportRules?.map((rule) => <p key={rule.id} className='text-sm'>Instance rule {rule.id}: {rule.text}</p>)}
            {preview.preview.pollSnapshot && <div className='rounded border p-2 text-sm'>
              <p>Your selected poll answers:</p>
              {preview.preview.pollSnapshot.options.filter((option) => Array.isArray(preview.preview.body.choices) && preview.preview.body.choices.includes(option.index)).map((option) => <p key={option.index}>{option.title}</p>)}
              <p>Votes cannot be changed or withdrawn through the Mastodon API. Review these exact answers before approving.</p>
            </div>}
            {preview.preview.media && Object.entries(preview.preview.media).map(([role, image]) => <p key={role} className='break-all text-xs'>{role}: Library image {image.id} · {image.bytes} bytes · SHA256 {image.hash}</p>)}
            <div className='flex gap-2'><Button disabled={busy} onClick={() => void approve()}>Approve exact action</Button><Button variant='outline' disabled={busy} onClick={() => setPreview(null)}>Back</Button></div>
          </div>
        ) : (
          <>
            <Label htmlFor={fieldId + '-action'}>Account action</Label>
            <Select value={action} onValueChange={(value) => { setAction(String(value)); setProfileEdit({ profile: {}, profileMedia: {} }); setText(''); setTarget(''); setMessage(''); setTitle(''); setAccountIds(''); setReportForward(false); setReportCategory('other'); setReportRuleIds(''); setFilterContexts([]); setFilterPolicy('keep'); setFilterExpiry(''); setFilterNeverExpires(false); setWholeWord(false); setPoll(null); setPollChoices([]); }}>
              <SelectTrigger id={fieldId + '-action'} aria-label='Mastodon account action'><SelectValue /></SelectTrigger>
              <SelectContent>{actions.map(([value, label]) => <SelectItem key={value} value={value}>{label}</SelectItem>)}</SelectContent>
            </Select>
            {action === 'profile_update' && <MastodonProfileFields connectionId={connectionId} onChange={setProfileEdit} />}
            {needsTarget && <label htmlFor={fieldId + '-target'} className='flex flex-col gap-1 text-sm'>{action === 'poll_vote' ? 'Poll ID' : 'Post, account, list or schedule ID'}<Input id={fieldId + '-target'} value={target} inputMode='numeric' onChange={(event) => { setTarget(event.target.value); setPoll(null); setPollChoices([]); }} /></label>}
            {action === 'poll_vote' && <>
              <Button variant='outline' disabled={busy} onClick={() => void readPoll()}>Read poll</Button>
              {poll?.id === target && <fieldset className='flex flex-col gap-2' disabled={busy || poll.expired || poll.voted !== false}>
                <legend className='text-sm'>{poll.multiple ? 'Choose one or more answers' : 'Choose one answer'}</legend>
                {poll.options.map((option) => <label key={option.index} htmlFor={fieldId + '-poll-' + option.index} className='flex items-center gap-2 text-sm'>
                  <Checkbox id={fieldId + '-poll-' + option.index} checked={pollChoices.includes(option.index)} onCheckedChange={(checked) => setPollChoices((previous) => checked === true ? poll.multiple ? [...previous.filter((index) => index !== option.index), option.index] : [option.index] : previous.filter((index) => index !== option.index))} />{option.title}
                </label>)}
              </fieldset>}
              {poll?.id === target && (poll.expired || poll.voted !== false) && <p className='text-sm'>This poll has ended, this account already voted, or its voting state could not be confirmed.</p>}
              <p className='text-muted-foreground text-xs'>Find the poll ID in a status&apos;s poll details. Rafii reviews your exact answers before sending one vote.</p>
            </>}
            {needsText && <label htmlFor={fieldId + '-text'} className='flex flex-col gap-1 text-sm'>{action === 'report_account' ? 'Report reason (up to1000 characters)' : action.startsWith('filter_') ? 'Keywords to add (one per line)' : 'Post text'}<textarea aria-label={action === 'report_account' ? 'Report reason (up to1000 characters)' : action.startsWith('filter_') ? 'Keywords to add (one per line)' : 'Post text'} id={fieldId + '-text'} maxLength={action === 'report_account' ? 1000 : action.startsWith('filter_') ? 2100 : undefined} className='min-h-24 rounded border p-2' value={text} onChange={(event) => setText(event.target.value)} /></label>}
            {['edit', 'native_schedule'].includes(action) && <MastodonFields onChange={setOptions} />}
            {needsTime && <label htmlFor={fieldId + '-time'} className='flex flex-col gap-1 text-sm'>Schedule time (your local time)<Input id={fieldId + '-time'} type='datetime-local' value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} /></label>}
            {['list_create', 'list_update', 'filter_create', 'filter_update'].includes(action) && <label htmlFor={fieldId + '-title'} className='flex flex-col gap-1 text-sm'>{action.startsWith('filter_') ? 'Filter title' : 'List title'}<Input id={fieldId + '-title'} value={title} onChange={(event) => setTitle(event.target.value)} /></label>}
            {['list_add', 'list_remove'].includes(action) && <label htmlFor={fieldId + '-accounts'} className='flex flex-col gap-1 text-sm'>Account IDs separated by commas<Input id={fieldId + '-accounts'} value={accountIds} onChange={(event) => setAccountIds(event.target.value)} /></label>}
            {action === 'report_account' && <>
              <Label htmlFor={fieldId + '-report-category'}>Report category</Label>
              <Select value={reportCategory} onValueChange={(value) => setReportCategory(String(value))}><SelectTrigger id={fieldId + '-report-category'}><SelectValue /></SelectTrigger><SelectContent><SelectItem value='other'>Other</SelectItem><SelectItem value='spam'>Spam</SelectItem><SelectItem value='violation'>Rule violation (Mastodon 3.5+)</SelectItem><SelectItem value='legal'>Illegal content (Mastodon 4.2+)</SelectItem></SelectContent></Select>
              {reportCategory === 'violation' && <>
                <Button variant='outline' size='sm' disabled={busy} onClick={() => void read('rules')}>View instance rules</Button>
                <label htmlFor={fieldId + '-report-rules'} className='flex flex-col gap-1 text-sm'>Broken instance rule IDs, separated by commas<Input id={fieldId + '-report-rules'} value={reportRuleIds} onChange={(event) => setReportRuleIds(event.target.value)} /></label>
              </>}
              <label htmlFor={fieldId + '-report-statuses'} className='flex flex-col gap-1 text-sm'>Supporting status IDs (optional, comma-separated)<Input id={fieldId + '-report-statuses'} value={accountIds} onChange={(event) => setAccountIds(event.target.value)} /></label>
              <label htmlFor={fieldId + '-report-forward'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-report-forward'} checked={reportForward} onCheckedChange={(value) => setReportForward(value === true)} />Forward this report to the reported account&apos;s server moderators</label>
              <p className='text-muted-foreground text-xs'>A filed report is not a moderation decision. Rafii cannot retract it. Review the target, reason and forwarding choice before approving.</p>
            </>}
            {['filter_create', 'filter_update'].includes(action) && <>
              <div className='flex flex-wrap gap-3' role='group' aria-label='Filter contexts'>{['home', 'notifications', 'public', 'thread', 'account'].map((context) => <label key={context} htmlFor={fieldId + '-context-' + context} className='flex items-center gap-1 text-sm'><Checkbox id={fieldId + '-context-' + context} checked={filterContexts.includes(context)} onCheckedChange={(value) => setFilterContexts((previous) => value === true ? [...previous, context] : previous.filter((item) => item !== context))} />{context}</label>)}</div>
              <Label htmlFor={fieldId + '-filter-policy'}>Filter policy</Label>
              <Select value={filterPolicy} onValueChange={(value) => setFilterPolicy(String(value))}><SelectTrigger id={fieldId + '-filter-policy'}><SelectValue /></SelectTrigger><SelectContent><SelectItem value='keep'>Default / keep current</SelectItem><SelectItem value='warn'>Warn</SelectItem><SelectItem value='hide'>Hide</SelectItem><SelectItem value='blur'>Blur (Mastodon4.4+)</SelectItem></SelectContent></Select>
              <label htmlFor={fieldId + '-whole-word'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-whole-word'} checked={wholeWord} onCheckedChange={(value) => setWholeWord(value === true)} />Match whole words for new keywords</label>
              <label htmlFor={fieldId + '-never-expire'} className='flex items-center gap-2 text-sm'><Checkbox id={fieldId + '-never-expire'} checked={filterNeverExpires} onCheckedChange={(value) => setFilterNeverExpires(value === true)} />Never expire (clear any current expiry)</label>
              <label htmlFor={fieldId + '-filter-expiry'} className='flex flex-col gap-1 text-sm'>Expiry in seconds (optional)<Input id={fieldId + '-filter-expiry'} type='number' min={60} max={31536000} disabled={filterNeverExpires} value={filterExpiry} onChange={(event) => setFilterExpiry(event.target.value)} /></label>
              <p className='text-muted-foreground text-xs'>Filters affect this account only. Blank fields keep existing settings when updating. A new filter needs a title and at least one context.</p>
            </>}
            <Button variant='outline' disabled={busy} onClick={() => void prepare()}>Review action</Button>
          </>
        )}
        {message && <p role='status' className='text-sm'>{message}</p>}
        {url && <a href={url} target='_blank' rel='noopener noreferrer' className='text-sm underline'>View on Mastodon</a>}
      </div>
    </details>
  );
}
