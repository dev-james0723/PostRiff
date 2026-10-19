'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { keys } from '@/lib/api/hooks';
import type { Job, NativeSocialPreview } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspace } from '@/lib/workspace/provider';

/** Commentary edits use a separate exact approval; the original create stays immutable. */
export function LinkedInPostEdit({ job }: { job: Job }) {
  const { api, workspaceId } = useWorkspace();
  const access = useWorkspaceAccess();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [preview, setPreview] = useState<NativeSocialPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [frozen, setFrozen] = useState(false);
  const [message, setMessage] = useState('');
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const connectionId = job.manifest.channelId;
  if (job.manifest.platform !== 'LinkedIn' || job.manifest.workspaceId !== workspaceId
    || !connectionId
    || !['provider_accepted', 'verified'].includes(job.state)
    || !/^urn:li:(share|ugcPost):\d+$/.test(job.providerReference ?? '')) return null;

  const currentText = job.publishedEdit?.text ?? job.manifest.payload.text;
  async function review() {
    if (!workspaceId || !job.providerReference || !connectionId) return;
    setBusy(true); setMessage('');
    try {
      setPreview(await api.nativeSocialPreview(workspaceId, connectionId, 'edit', job.providerReference, { text }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Couldn’t prepare this edit.');
    } finally { setBusy(false); }
  }
  async function approve() {
    if (!workspaceId || !preview || !connectionId) return;
    const approved = preview;
    setPreview(null); setFrozen(true); setBusy(true); setMessage('');
    try {
      const result = await api.nativeSocialApprove(workspaceId, connectionId, approved.id, approved.digest);
      setMessage(result.message ?? 'Check the edit receipt before continuing.');
      if (result.executionState === 'submitted') { setEditing(false); setFrozen(false); }
      else if (result.executionState === 'held') setFrozen(false);
    } catch {
      setMessage('The edit outcome is unconfirmed. Open the LinkedIn post and reconcile its receipt before another edit.');
    } finally {
      setBusy(false);
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    }
  }

  return (
    <section className='flex flex-col gap-3' aria-label='Edit this LinkedIn post'>
      <h3 className='rafii-eyebrow'>LinkedIn post text</h3>
      {job.publishedEdit && <p className='whitespace-pre-wrap text-sm'>{currentText}</p>}
      {job.publishedEdit && <p className='text-muted-foreground text-xs'>LinkedIn accepted this commentary edit. Open the post to confirm its display.</p>}
      {!editing && canEdit && <Button variant='glass' size='control' disabled={busy || frozen} onClick={() => {
        setText(currentText); setPreview(null); setMessage(''); setEditing(true);
      }}>Edit published text</Button>}
      {editing && <>
        <Label htmlFor={`linkedin-edit-${job.id}`}>Updated post text</Label>
        <Textarea id={`linkedin-edit-${job.id}`} value={text} maxLength={3000} disabled={busy || frozen || !canEdit}
          onChange={(event) => { setText(event.target.value); setPreview(null); }} />
        <p className='text-muted-foreground text-xs'>Account: {job.manifest.account}. This changes the existing post’s commentary. Its media and original publishing approval stay unchanged.</p>
        {preview && <section className='flex flex-col gap-2 rounded-lg border p-3' aria-label='Review LinkedIn text edit'>
          <p className='whitespace-pre-wrap text-sm'>{String(preview.manifest.payload.text)}</p>
          <p className='text-muted-foreground text-xs'>Post: {preview.manifest.target}</p>
          <Button variant='action' size='control' disabled={busy || frozen || !canApprove} onClick={() => void approve()}>
            Approve this text edit
          </Button>
        </section>}
        {!preview && <Button variant='glass' size='control' disabled={busy || frozen || !canEdit || !text.trim() || text === currentText}
          onClick={() => void review()}>{busy ? 'Preparing edit…' : 'Review text edit'}</Button>}
        <Button variant='quiet' size='control' disabled={busy} onClick={() => { setEditing(false); setPreview(null); }}>Close edit</Button>
      </>}
      {message && <p role='status' className='text-sm'>{message}</p>}
    </section>
  );
}
