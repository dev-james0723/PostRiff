'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { PreviewDeck } from '@/components/application/post-preview/preview-deck';
import { previewFromDraft } from '@/components/application/post-preview/draft-preview';
import { Button } from '@/components/ui/button';
import { StateMessage } from '@/components/rafii';
import { keys, useSnapshot } from '@/lib/api/hooks';
import type { Run } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { EditDraftDialog } from '@/features/pipeline/edit-draft-dialog';
import { languageLabel } from '@/lib/locales';
import { variantForRow } from './plan';

export function HomeResults({ run, loading, timeZone, canEdit }: { run: Run | null; loading: boolean; timeZone: string; canEdit: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const snapshot = useSnapshot();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [edit, setEdit] = useState<string | null>(null);
  const [openedAt] = useState(() => new Date());
  const state = snapshot.data?.state;
  const variants = run?.artifact?.variants ?? [];
  const items = variants.map((variant) => {
    const saved = run && state ? variantForRow(state, run, variant) : undefined;
    const channel = variant.channelId ? state?.phase2?.channels.find((c) => c.id === variant.channelId) : undefined;
    return { key: `${variant.channelId ?? variant.platform}:${variant.language}`, variant, saved,
      post: previewFromDraft({ platform: variant.platform, text: saved?.text ?? variant.text, account: variant.account ?? channel?.account ?? 'Draft preview', channelId: variant.channelId, timeZone, publishAt: openedAt }) };
  });
  const active = items.find((item) => item.key === selected) ?? items[0];
  async function save() {
    if (!run?.artifactHash || !canEdit) return;
    setSaving(true);
    try {
      const current = await api.snapshot(workspaceId);
      await api.applyRun(workspaceId, run.runId, current.revision, run.artifactHash);
      const next = await api.snapshot(workspaceId);
      client.setQueryData(keys.snapshot(workspaceId), next);
      toast.success('Saved to drafts.');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Drafts could not be saved.'); }
    finally { setSaving(false); }
  }
  if (!run) return <StateMessage kind={loading ? 'loading' : 'empty'} title={loading ? 'Preparing your drafts…' : 'Your idea, unfolded.'} description={loading ? 'Keep this page open, or return to the conversation.' : 'Your drafts will appear here.'} />;
  return (
    <section className='flex min-w-0 flex-col gap-3' aria-label='Draft previews'>
      <div className='flex flex-wrap items-center justify-between gap-2'><h2 className='font-serif text-2xl'>Your idea, unfolded.</h2><span role='status' className='text-muted-foreground text-xs'>{run.status === 'completed' ? 'Ready to review' : run.status}</span></div>
      {items.length > 0 && active ? <>
        <div className='flex flex-wrap gap-2' role='group' aria-label='Preview destinations'>
          {items.map((item) => <Button key={item.key} size='sm' variant='glass' aria-pressed={active.key === item.key} onClick={() => setSelected(item.key)}>{item.variant.account ?? item.variant.platform} · {languageLabel(item.variant.language)}</Button>)}
        </div>
        <PreviewDeck items={items} activeKey={active.key} onChange={setSelected} label='Generated draft previews' tools={false} scale={0.64} />
        <p className='text-muted-foreground text-xs'>Layout preview · not published</p>
        {(active.variant.unknowns.length > 0 || (active.variant.warnings?.length ?? 0) > 0) && <details><summary className='rafii-focus min-h-11 cursor-pointer py-3 text-sm'>Review notes</summary><p className='text-muted-foreground text-sm'>{[...active.variant.unknowns, ...(active.variant.warnings ?? [])].join(' ')}</p></details>}
        {canEdit && <div className='flex flex-wrap gap-2'>
          {active.saved ? <Button variant='action' onClick={() => setEdit(active.saved!.id)}>Edit draft</Button> : <Button variant='action' disabled={saving || run.status !== 'completed'} onClick={() => void save()}>{saving ? 'Saving…' : 'Save drafts'}</Button>}
          <Link href='/app/pipeline' className='rafii-focus inline-flex min-h-11 items-center rounded-lg px-3 text-sm'>Open drafts</Link>
        </div>}
      </> : <StateMessage kind={run.status === 'failed' ? 'error' : 'loading'} title={run.status === 'failed' ? 'Draft preparation failed' : run.status === 'cancelled' ? 'Preparation cancelled' : 'Waiting for results…'} />}
      <Link href={`/app/agent/${encodeURIComponent(run.conversationId)}`} className='rafii-focus inline-flex min-h-11 items-center self-start rounded-lg text-sm underline'>Open conversation{run.artifact?.plan ? ' & review schedule' : ''}</Link>
      {canEdit && ['running', 'queued'].includes(run.status) && <Button variant='glass' onClick={() => { void api.cancelRun(workspaceId, run.runId).catch((error) => toast.error(error instanceof Error ? error.message : 'Cancellation could not be confirmed.')); }}>Cancel preparation</Button>}
      {edit && <EditDraftDialog key={edit} variantId={edit} open onOpenChange={(open) => { if (!open) setEdit(null); }} />}
    </section>
  );
}
