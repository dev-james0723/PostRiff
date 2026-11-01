'use client';

import { useId, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Textarea } from '@/components/ui/textarea';
import { StateMessage } from '@/components/rafii';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { ChannelView } from '@/lib/api/types';
import type { DiscordEngagementMessage, DiscordEngagementPermissions, DiscordEngagementRead, DiscordEngagementStatus, DiscordReplyReview } from '@/lib/channels/discord-engagement';
import { formatDateTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { CONTROL_44, DIALOG_ELEVATED, SHEET_ELEVATED } from './rafii-materials';
import { cn } from '@/lib/utils';

const NONE: DiscordEngagementPermissions = { analytics: false, inbox: false, reply: false };
const LABELS = { analytics: 'Read server snapshots and Rafii-managed message metrics', inbox: 'Read the partial Discord inbox', reply: 'Prepare replies for my individual approval' };

/** Personal consent and manual reads; no background ingestion or automatic reply path. */
export function DiscordEngagementPanel({ channel, mode = 'all' }: { channel: ChannelView; mode?: 'all' | 'analytics' | 'inbox' }) {
  const { api, workspaceId } = useWorkspaceApi();
  const controlId = useId();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<DiscordEngagementStatus | null>(null);
  const [selected, setSelected] = useState('');
  const [permissions, setPermissions] = useState<DiscordEngagementPermissions>(NONE);
  const [extended, setExtended] = useState(false);
  const [data, setData] = useState<DiscordEngagementRead | null>(null);
  const [parent, setParent] = useState<DiscordEngagementMessage | null>(null);
  const [text, setText] = useState('');
  const [localTime, setLocalTime] = useState('');
  const [review, setReview] = useState<DiscordReplyReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const destination = status?.destinations.find((item) => item.target.id === selected);
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try { await action(); }
    catch (cause) {
      setError(cause instanceof ApiError || cause instanceof Error ? cause.message : 'The request did not complete. Reload its state before trying again.');
      // Previously delivered provider data is never presented as a fresh read.
      setData(null);
      setReview(null);
    } finally { setBusy(false); }
  }

  function choose(next: string, current: DiscordEngagementStatus | null = status) {
    setSelected(next);
    setExtended(current?.destinations.find((item) => item.target.id === next)?.contentAccess === 'approved_content');
    setPermissions(current?.destinations.find((item) => item.target.id === next)?.permissions ?? NONE);
    setData(null); setParent(null); setReview(null); setText('');
  }

  async function reload() {
    const next = await api.discordEngagement(workspaceId, channel.id);
    setStatus(next);
    return next;
  }

  function show() {
    setOpen(true); setData(null); setReview(null); setParent(null);
    void run(async () => {
      const next = await reload();
      choose(next.destinations[0]?.target.id ?? '', next);
    });
  }

  function consent(revoke: boolean) {
    if (!destination) return;
    void run(async () => {
      const next = await api.discordEngagementConsent(workspaceId, channel.id, {
        destinationId: destination.target.id, targetDigest: destination.targetDigest,
        permissions: revoke ? NONE : permissions, confirmed: true, contentAccess: extended && !revoke ? 'approved_content' : 'mentions_only'
      });
      setStatus(next); choose(selected, next);
      void client.invalidateQueries({ queryKey: keys.channels(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    });
  }

  function read(kind: 'analytics' | 'inbox') {
    if (!destination) return;
    setData(null); setParent(null); setReview(null);
    void run(async () => { setData(await api.discordEngagementRead(workspaceId, channel.id, { destinationId: destination.target.id, kind })); });
  }

  function prepare() {
    if (!destination || !parent) return;
    void run(async () => {
      setReview(await api.discordReplyPreview(workspaceId, channel.id, {
        destinationId: destination.target.id, parentMessageId: parent.id, text,
        ...(localTime ? { localTime, timeZone } : {})
      }));
    });
  }

  function approve() {
    if (!review) return;
    const frozen = review;
    void run(async () => {
      await api.discordReplyApprove(workspaceId, channel.id, { reviewId: frozen.reviewId, digest: frozen.digest, confirmed: true });
      setReview(null); setParent(null); setText('');
      await reload();
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    });
  }

  const label = mode === 'analytics' ? `Discord analytics · ${channel.account}` : mode === 'inbox' ? `Discord conversations · ${channel.account}` : 'Discord analytics & conversations';
  return (
    <>
      <Button variant='glass' className={CONTROL_44} onClick={show}>{label}</Button>
      <Sheet open={open} onOpenChange={(value) => { if (!busy) { setOpen(value); if (!value) { setData(null); setParent(null); setReview(null); setText(''); } } }}>
        <SheetContent side='right' className={cn(SHEET_ELEVATED, 'w-full sm:max-w-xl')}>
          <SheetHeader className='px-5 pt-5 pr-14 pb-3'>
            <SheetTitle>Discord analytics & conversations</SheetTitle>
            <SheetDescription>{channel.account}. Choose the exact channel and approve your own access. Every reply needs a separate review and approval.</SheetDescription>
          </SheetHeader>
          <div className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-6 text-sm'>
            {error && <p role='alert' className='text-destructive'>{error}</p>}
            {!status ? <StateMessage kind='loading' layout='inline' title='Loading Discord access…' /> : <>
              {!status.enabled && <StateMessage kind='permission' layout='inline' title='Engagement rollout is paused' description='Scoped support is implemented. The operator must complete the separately approved rollout checks before reads or reply approvals can run.' />}
              <p>{status.limits.analytics}</p>
              <p>{status.limits.inbox}</p>
              <p className='text-muted-foreground'>{status.limits.retention}</p>
              <label htmlFor={`${controlId}-destination`} className='flex flex-col gap-1'>Exact Discord destination
                <select id={`${controlId}-destination`} aria-label='Engagement destination' className='rafii-field min-h-11 rounded-md p-2' value={selected} disabled={busy} onChange={(event) => choose(event.target.value)}>
                  <option value='' disabled>Choose an authorized channel</option>
                  {status.destinations.map(({ target }) => <option key={target.id} value={target.id}>{target.guildName} · {target.channelName} ({target.channelId})</option>)}
                </select>
              </label>
              {!status.destinations.length && <p>Authorize a text or announcement channel in Channels first.</p>}
              {destination && <>
                <p className='text-muted-foreground break-all'>Server {destination.target.guildId} · channel {destination.target.channelId}</p>
                <fieldset className='flex flex-col gap-2' disabled={busy || !status.enabled}>
                  <legend className='mb-2 font-medium'>Allow for my account for 30 days</legend>
                  {(Object.keys(LABELS) as (keyof DiscordEngagementPermissions)[]).map((kind) => <label key={kind} htmlFor={`${controlId}-${kind}`} className='flex min-h-11 items-center gap-2'>
                    <input id={`${controlId}-${kind}`} aria-label={LABELS[kind]} type='checkbox' checked={permissions[kind]} disabled={kind === 'reply' && !status.canReply} onChange={(event) => setPermissions((prior) => ({ ...prior, [kind]: event.target.checked, ...(kind === 'inbox' && !event.target.checked ? { reply: false } : {}), ...(kind === 'reply' && event.target.checked ? { inbox: true } : {}) }))} />
                    {LABELS[kind]}
                  </label>)}
                  <label htmlFor={`${controlId}-general-content`} className='flex min-h-11 items-center gap-2'>
                    <input id={`${controlId}-general-content`} aria-label='Read general channel text with separately approved Discord access' type='checkbox' checked={extended} disabled={!destination.broaderContentEligible} onChange={(event) => setExtended(event.target.checked)} />
                    Read general channel text with separately approved Discord access
                  </label>
                  {!destination.broaderContentEligible && <p className='text-muted-foreground'>General channel text awaits the app’s separate Discord approval and enablement. Limited access remains available.</p>}
                </fieldset>
                <div className='flex flex-wrap gap-2'>
                  <Button variant='action' disabled={busy || !status.enabled || !Object.values(permissions).some(Boolean)} onClick={() => consent(false)}>Approve selected access</Button>
                  <Button variant='glass' disabled={busy || !Object.values(destination.permissions).some(Boolean)} onClick={() => consent(true)}>Revoke my channel access</Button>
                </div>
                {destination.expiresAt && <p className='text-muted-foreground'>Access expires {formatDateTime(destination.expiresAt)}. Changing access fences pending replies.</p>}
                <div className='flex flex-wrap gap-2'>
                  {mode !== 'inbox' && <Button variant='glass' disabled={busy || !status.enabled || !destination.permissions.analytics} onClick={() => read('analytics')}>Read Discord metrics</Button>}
                  {mode !== 'analytics' && <Button variant='glass' disabled={busy || !status.enabled || !destination.permissions.inbox} onClick={() => read('inbox')}>Read partial inbox</Button>}
                </div>
              </>}
              {data?.kind === 'analytics' && <section aria-label='Discord metric readings' className='flex flex-col gap-2'>
                <p className='font-medium'>Native approximate server snapshot</p>
                <p>Members: {data.server?.approximateMembers.value ?? 'Unavailable'} · online: {data.server?.approximateOnline.value ?? 'Unavailable'}</p>
                <p className='font-medium'>Rafii-managed messages only</p>
                <div className='overflow-x-auto'><table className='w-full text-left'><thead><tr><th>Message</th><th>Reactions</th><th>Replies observed</th></tr></thead><tbody>
                  {data.managedMessages?.map((item) => <tr key={item.messageId}><td className='break-all py-2'>{item.messageId}</td><td>{item.reactions.value ?? 'Unavailable'}</td><td>{item.repliesObserved.value ?? 'Unavailable'} (lower bound)</td></tr>)}
                </tbody></table></div>
                {!data.managedMessages?.length && <p>No verified Rafii-managed messages in this channel.</p>}
                <p className='text-muted-foreground'>Impressions, reach and all-time reply totals: unavailable. Read {formatDateTime(data.observedAt)}.</p>
              </section>}
              {data?.kind === 'inbox' && <section aria-label='Partial Discord inbox' className='flex flex-col gap-3'>
                <p>Latest {data.pageLimit} messages scanned. Older messages and threads are outside this reading. {data.contentAccess === 'approved_content' ? 'General channel text is covered by your separate consent and the current Discord access check.' : 'Limited mode: bot mentions and replies to Rafii-managed messages.'}</p>
                {!data.messages?.length && <p>No relevant replies or bot mentions in this page.</p>}
                {data.messages?.map((message) => <article key={message.id} className='rafii-quiet flex flex-col gap-2 rounded-md p-3'>
                  <p className='font-medium'>{message.author ?? 'Content restricted by Discord'}</p>
                  <p className='whitespace-pre-wrap break-words'>{message.content ?? 'Discord withheld this message’s text. Open the message in Discord to read or reply.'}</p>
                  <p className='text-muted-foreground break-all'>Message {message.id}{message.parentMessageId ? ` · reply to ${message.parentMessageId}` : data.contentAccess === 'approved_content' ? ' · channel message' : ' · bot mention'}</p>
                  <div className='flex flex-wrap gap-2'><a href={message.url} target='_blank' rel='noreferrer' className='underline'>Open in Discord</a>
                    <Button variant='glass' disabled={busy || !message.replyable || !status.canReply || !destination?.permissions.reply} onClick={() => { setParent(message); setText(''); }}>Write a reply</Button>
                  </div>
                </article>)}
              </section>}
              {parent && <section aria-label='Write an individually approved Discord reply' className='flex flex-col gap-2'>
                <p>Reply to message {parent.id}</p>
                <label htmlFor={`${controlId}-reply`}>Your exact reply<Textarea id={`${controlId}-reply`} aria-label='Exact Discord reply' value={text} disabled={busy} maxLength={2000} onChange={(event) => setText(event.target.value)} /></label>
                <label htmlFor={`${controlId}-time`} className='flex flex-col gap-1'>Schedule in {timeZone} (optional)
                  <input id={`${controlId}-time`} type='datetime-local' aria-label='Discord reply time' className='rafii-field min-h-11 rounded-md p-2' value={localTime} disabled={busy} onChange={(event) => setLocalTime(event.target.value)} />
                </label>
                <p className='text-muted-foreground'>Leave the time empty to review the next minute. Mentions and reply notifications are suppressed.</p>
                <Button variant='action' disabled={busy || !text.trim()} onClick={prepare}>Review exact reply</Button>
              </section>}
              {!!status.jobs.length && <section aria-label='My approved Discord replies' className='flex flex-col gap-3'><p className='font-medium'>My approved replies</p>
                {status.jobs.map((job) => <article key={job.id} className='rafii-quiet rounded-md p-3'>
                  <p className='whitespace-pre-wrap break-words'>{job.text}</p><p>{job.state}{job.cancelRequested ? ' · cancellation requested' : ''} · {formatDateTime(job.timing.timestamp)}</p>
                  <p className='text-muted-foreground'>Parent {job.parentMessageId}</p>
                  {job.state === 'uncertain' && <p>Outcome unknown. Keep the original receipt for reconciliation; do not approve another copy.</p>}
                  {job.previewDispatchPending && job.state === 'held' && !job.cancelRequested && <Button variant='glass' disabled={busy} onClick={() => void run(async () => { await api.executeJob(workspaceId, job.id, job.approvalDigest); await reload(); })}>Dispatch approved reply</Button>}
                  {!['verified', 'canceled', 'failed'].includes(job.state) && !job.cancelRequested && <Button variant='quiet' disabled={busy} onClick={() => void run(async () => { await api.discordReplyCancel(workspaceId, channel.id, job.id); await reload(); })}>Cancel further sending</Button>}
                </article>)}
              </section>}
              <details><summary>Content access limits</summary><p>{status.limits.broaderAccess}</p><a href='https://docs.discord.com/developers/events/gateway#message-content-intent' target='_blank' rel='noreferrer' className='underline'>Discord’s official message-content rules</a></details>
            </>}
            {busy && <p role='status'>Working…</p>}
          </div>
        </SheetContent>
      </Sheet>
      <Dialog open={Boolean(review)} onOpenChange={(value) => { if (!value && !busy) setReview(null); }}>
        <DialogContent className={DIALOG_ELEVATED}>
          <DialogHeader><DialogTitle>Approve this exact Discord reply</DialogTitle><DialogDescription>Your approval covers only this text, parent message, destination and time. A changed parent or revoked access stops dispatch.</DialogDescription></DialogHeader>
          {review && <div className='flex flex-col gap-3 text-sm'>
            <p className='break-all'>{review.manifest.discord.target.guildName} · {review.manifest.discord.target.channelName}<br />Server {review.manifest.discord.target.guildId} · channel {review.manifest.discord.target.channelId}</p>
            <p>Parent message {review.manifest.engagementReply.parentMessageId}</p>
            <blockquote className='rafii-quiet whitespace-pre-wrap break-words rounded-md p-3'>{review.parent.content}</blockquote>
            <p className='font-medium'>Frozen reply</p><p className='rafii-quiet whitespace-pre-wrap break-words rounded-md p-3'>{review.manifest.payload.text}</p>
            <p>{formatDateTime(review.manifest.timing.timestamp)} · {review.manifest.timing.timeZone}</p>
            <p className='text-muted-foreground'>No mentions or reply notifications. Review expires {formatDateTime(review.expiresAt)}.</p>
          </div>}
          <DialogFooter><Button variant='glass' disabled={busy} onClick={() => setReview(null)}>Back to editing</Button><Button variant='action' disabled={busy || !review} onClick={approve}>Approve this exact reply</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
