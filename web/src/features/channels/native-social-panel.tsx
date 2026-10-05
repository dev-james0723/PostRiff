'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ChannelView, NativeSocialPreview, NativeSocialReading } from '@/lib/api/types';
import { nativeComments, nativeMetricRows, type NativeComment } from '@/lib/channels/native-readings';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const READS: Record<string, { comments?: string; analytics?: string }> = {
  LinkedIn: { comments: 'comments_read', analytics: 'analytics' },
  Threads: { comments: 'replies_read', analytics: 'insights' },
  Instagram: { comments: 'comments_read', analytics: 'insights' },
  Facebook: { comments: 'comments', analytics: 'insights' },
  X: { comments: 'conversation_read', analytics: 'analytics' },
  YouTube: { comments: 'comments_read', analytics: 'analytics' },
  Pinterest: { analytics: 'analytics' }
};

/** Explicit reads and exact, single-action approvals use the same workspace and access guard as Channels. */
export function NativeSocialPanel({ channel }: { channel: ChannelView }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const [target, setTarget] = useState('');
  const [metric, setMetric] = useState('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [reading, setReading] = useState<NativeSocialReading | null>(null);
  const [selected, setSelected] = useState<NativeComment | null>(null);
  const [text, setText] = useState('');
  const [preview, setPreview] = useState<NativeSocialPreview | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const reads = READS[channel.platform];
  if (!reads) return null;
  const comments = reading && reads.comments === reading.feature ? nativeComments(reading.data) : [];
  const metrics = reading && reads.analytics === reading.feature ? nativeMetricRows(reading.data) : [];
  const prefix = `native-${channel.id}`;

  async function run(operation: () => Promise<void>) {
    setBusy(true); setMessage('');
    try { await operation(); } catch (error) { setMessage(error instanceof Error ? error.message : 'The platform did not confirm this request.'); }
    finally { setBusy(false); }
  }
  function read(feature: string) {
    if (!workspaceId) return;
    void run(async () => {
      setSelected(null); setPreview(null); setReading(null);
      const options: Record<string, string> = {};
      if (metric) options[channel.platform === 'YouTube' ? 'metrics' : channel.platform === 'LinkedIn' ? 'queryType' : 'metric'] = metric;
      if (start) options.startDate = start;
      if (end) options.endDate = end;
      if (channel.platform === 'YouTube') options.filters = `video==${target}`;
      const result = await api.nativeSocialRead(workspaceId, channel.id, feature, target, options);
      setReading(result);
      if (result.availability !== 'available') setMessage(`Platform reading: ${result.availability.replaceAll('_', ' ')}. No missing metric is counted as zero.`);
    });
  }
  function reviewReply() {
    if (!workspaceId || !selected) return;
    void run(async () => {
      const payload: Record<string, unknown> = { text };
      if (channel.platform === 'LinkedIn') payload.rootPostUrn = selected.rootId ?? target;
      setPreview(await api.nativeSocialPreview(workspaceId, channel.id, 'reply', selected.id, payload));
    });
  }
  function approve() {
    if (!workspaceId || !preview) return;
    const approved = preview;
    setPreview(null); // An ambiguous submission never offers a second send.
    void run(async () => {
      const result = await api.nativeSocialApprove(workspaceId, channel.id, approved.id, approved.digest);
      setMessage(result.message ?? `Platform action: ${result.executionState ?? 'outcome unconfirmed'}. Submission is separate from verification.`);
      setSelected(null); setText('');
    });
  }
  return <details className='rafii-quiet rounded-xl p-3'>
    <summary className='rafii-focus cursor-pointer text-sm'>Read post metrics and conversations</summary>
    <p className='text-muted-foreground mt-2 text-xs'>Permissions are checked when you read or send. Readings keep the platform’s metric names. {channel.platform === 'X' && 'X requests require a separately approved API budget.'}</p>
    <div className='mt-3 flex flex-col gap-3'>
      <Label htmlFor={`${prefix}-target`}>Post identifier{channel.platform === 'LinkedIn' ? ' (post URN)' : ''}</Label>
      <Input id={`${prefix}-target`} value={target} onChange={(e) => { setTarget(e.target.value); setPreview(null); setReading(null); }} placeholder='Identifier from the publication receipt' />
      {reads.analytics && <>
        <Label htmlFor={`${prefix}-metric`}>Platform metrics</Label>
        <Input id={`${prefix}-metric`} value={metric} onChange={(e) => setMetric(e.target.value)} placeholder={channel.platform === 'LinkedIn' ? 'IMPRESSION' : channel.platform === 'YouTube' ? 'views,likes,comments' : channel.platform === 'Threads' ? 'views,likes,replies,reposts,quotes' : 'Documented metrics for this post type'} />
        <div className='grid grid-cols-2 gap-2'>
          <div><Label htmlFor={`${prefix}-start`}>From</Label><Input id={`${prefix}-start`} type='date' value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div><Label htmlFor={`${prefix}-end`}>Through</Label><Input id={`${prefix}-end`} type='date' value={end} onChange={(e) => setEnd(e.target.value)} /></div>
        </div>
      </>}
      <div className='flex flex-wrap gap-2'>
        {reads.comments && <Button variant='glass' disabled={busy || !target} onClick={() => read(reads.comments!)}>Read comments and replies</Button>}
        {reads.analytics && <Button variant='glass' disabled={busy || !target} onClick={() => read(reads.analytics!)}>Read metrics</Button>}
      </div>
      {reading?.availability === 'available' && <p className='text-muted-foreground text-xs'>Source: {reading.provider} · provider-native · {Object.entries(reading.provenance.reportingPeriod).map(([key, value]) => `${key}: ${value}`).join(' · ') || 'Provider response without a requested period'}</p>}
      {comments.length > 0 && <ul className='flex flex-col gap-3' aria-label='Provider comments'>{comments.map((comment) => <li key={comment.id} className='rounded-lg border p-3'>
        <p className='text-sm font-medium'>{comment.author || 'Author not returned'}</p><p className='whitespace-pre-wrap text-sm'>{comment.text}</p>
        {comment.parentId && <p className='text-muted-foreground text-xs'>Reply to {comment.parentId}</p>}
        {canEdit && channel.platform !== 'Threads' && <Button variant='glass' size='sm' onClick={() => { setSelected(comment); setPreview(null); setText(''); }}>Prepare reply</Button>}
        {channel.platform === 'Threads' && <p className='text-muted-foreground text-xs'>Prepare a Threads draft using reply identifier {comment.id}; approve it in the publishing composer.</p>}
      </li>)}</ul>}
      {metrics.length > 0 && <div className='overflow-x-auto'><table className='w-full text-left text-sm'><thead><tr><th>Platform field</th><th>Reported value</th></tr></thead><tbody>{metrics.map((row) => <tr key={row.name}><td className='break-all py-1 pr-3'>{row.name}</td><td>{row.value.toLocaleString()}</td></tr>)}</tbody></table></div>}
      {reading?.availability === 'available' && comments.length === 0 && metrics.length === 0 && <p className='text-muted-foreground text-xs'>No displayable comments or numeric metrics were returned. This is not a zero reading.</p>}
      {selected && <section className='flex flex-col gap-2 rounded-lg border p-3' aria-label='Review native reply'>
        <p className='text-sm'>Reply from {channel.account} to: {selected.text}</p>
        <Label htmlFor={`${prefix}-reply`}>Your exact reply</Label><Textarea id={`${prefix}-reply`} value={text} maxLength={4000} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
        {!preview && <Button variant='glass' disabled={busy || !text.trim()} onClick={reviewReply}>Review reply</Button>}
        {preview && <><p className='whitespace-pre-wrap text-sm'>{String(preview.manifest.payload.text)}</p><p className='text-muted-foreground text-xs'>Account: {preview.manifest.providerAccountId} · Reply to: {preview.manifest.target}</p><Button variant='glass' disabled={busy || !canApprove} onClick={approve}>Approve and send this reply</Button></>}
      </section>}
      {message && <p role='status' className='text-sm'>{message}</p>}
    </div>
  </details>;
}
