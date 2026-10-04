'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { failureOf, useFounderScope } from './kit/api';
import { recordLabel } from './kit/format';
import type { RecordRow } from './kit/types';

/** Existing per-founder Demo overlay only. The API supplies CSRF, stable retry keys and verified revisions. */
export function DemoWorkspaceActions({ workspace, revision }: { workspace: RecordRow; revision: number }) {
  const scope = useFounderScope();
  const client = useQueryClient();
  const currentName = recordLabel(workspace);
  const [name, setName] = useState(currentName);
  const [saved, setSaved] = useState('');
  useEffect(() => { setName(currentName); }, [workspace.id, currentName]);
  const mutation = useMutation({
    retry: false,
    mutationFn: async (action: 'rename_workspace' | 'reset') => {
      if (!scope.ready || scope.mode !== 'demo') throw new Error('Select Demo before changing sample data.');
      await scope.api.demoAction(action, action === 'reset' ? 'all' : workspace.id, action === 'reset' ? '' : name.trim(), revision);
      await client.invalidateQueries({ queryKey: scope.key() });
      return action;
    },
    onSuccess: (action) => setSaved(action === 'reset' ? 'Your Demo changes were reset.' : 'Sample workspace saved. Live accounts are unchanged.')
  });
  if (scope.mode !== 'demo') return null;
  return (
    <section aria-label='Demo workspace actions' className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3'>
      <h3 className='rafii-eyebrow'>Try a Demo action</h3>
      <p className='text-muted-foreground text-xs'>Changes stay in your private Demo. Reset restores all sample records.</p>
      <label htmlFor='demo-workspace-name' className='text-xs font-medium'>Sample workspace name</label>
      <Input id='demo-workspace-name' value={name} maxLength={80} disabled={mutation.isPending} onChange={(event) => { setName(event.target.value); setSaved(''); mutation.reset(); }} />
      <div className='flex flex-wrap gap-2'>
        <Button variant='action' disabled={!scope.ready || mutation.isPending || !name.trim() || name.trim() === recordLabel(workspace)} onClick={() => { setSaved(''); mutation.mutate('rename_workspace'); }}>{mutation.isPending ? 'Saving…' : 'Save sample workspace'}</Button>
        <Button variant='quiet' disabled={!scope.ready || mutation.isPending} onClick={() => { setSaved(''); mutation.mutate('reset'); }}>Reset my Demo</Button>
      </div>
      {saved && <p role='status' className='text-xs'>{saved}</p>}
      {mutation.error && <p role='alert' className='text-destructive text-xs'>{failureOf(mutation.error).message}</p>}
    </section>
  );
}
