'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Checkbox } from '@/components/motion/checkbox';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { keys } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Snapshot, SnapshotSource } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';

const POLICY: Record<string, string> = {
  public_quote: 'May be quoted publicly',
  rewrite_approval: 'Rewrite; approve before publishing',
  internal_reference: 'Internal reference only',
  prohibited: 'Not for drafting'
};

/** Workspace sources the pocket can offer: active, not writing samples. */
export function pocketSources(sources: SnapshotSource[] | undefined) {
  return (sources ?? []).filter((s) => s.active && s.kind !== 'voice_sample');
}

export interface ContextPocketProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sources: SnapshotSource[];
  /** Ids staged for the next generation (applied on Done). */
  included: string[];
  onIncludedChange: (ids: string[]) => void;
  revision: number;
}

/**
 * Context Pocket (DNA §21.10, prompt §4): the usable workspace sources a draft may read, chosen
 * per request. Inclusion here never changes a source's policy: permission to quote publicly is
 * decided per source on the Ideas page and only shown here. A note added from the pocket becomes
 * a real workspace source (`source` action) and is included by default.
 */
export function ContextPocket({ open, onOpenChange, sources, included, onIncludedChange, revision }: ContextPocketProps) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [staged, setStaged] = useState<string[]>(included);
  const [note, setNote] = useState('');
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setStaged(included);
      setError(null);
    }
  }, [open, included]);
  const usable = useMemo(() => pocketSources(sources), [sources]);
  const set = new Set(staged);

  async function addNote() {
    const text = note.trim();
    if (!text) return;
    setAdding(true);
    setError(null);
    try {
      const current = client.getQueryData<Snapshot>(keys.snapshot(workspaceId));
      const title = text.split('\n')[0].slice(0, 60) || 'A new note';
      const after = await api.act(workspaceId, current?.revision ?? revision, 'source', { kind: 'text', text, title });
      client.setQueryData(keys.snapshot(workspaceId), after);
      const created = after.state.sources?.at(-1);
      if (created) setStaged((ids) => Array.from(new Set([...ids, created.id])));
      setNote('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The note could not be added.');
    } finally {
      setAdding(false);
    }
  }

  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm' aria-describedby={undefined}>
        <RafiiDialogHeader eyebrow='Context pocket' title='A little' accent='backstory.' intro='Pick what the next drafts may read.' />
        <RafiiDialogBody className='flex flex-col gap-4'>
          {usable.length === 0 ? (
            <StateMessage kind='empty' title='No sources yet' />
          ) : (
            <ul className='flex flex-col gap-2' aria-label='Usable sources'>
              {usable.map((source) => {
                const on = set.has(source.id);
                return (
                  <li key={source.id} className={cn('flex items-start gap-3 rounded-[var(--rafii-radius-control)] px-3 py-2.5', on ? 'rafii-glass-selected' : 'rafii-quiet')}>
                    <Checkbox
                      checked={on}
                      onCheckedChange={(checked) => setStaged((ids) => (checked ? Array.from(new Set([...ids, source.id])) : ids.filter((id) => id !== source.id)))}
                      label={source.title || 'Untitled source'}
                      className='min-w-0 flex-1 items-start gap-3 [&>button]:mt-0.5 [&>span]:text-sm'
                    />
                    <span className='text-muted-foreground shrink-0 pt-0.5 text-[11px] leading-relaxed' title={source.kind}>
                      {source.sourcePolicy ? POLICY[source.sourcePolicy] ?? source.sourcePolicy : 'Quoting not set'}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          <div className='flex flex-col gap-2'>
            <label htmlFor='rafii-pocket-note' className='text-foreground text-sm font-medium'>
              Add a note
            </label>
            <textarea
              id='rafii-pocket-note'
              aria-label='Add a note'
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={20000}
              rows={3}
              placeholder='The course launches on 3 March'
              className='rafii-field rafii-focus min-h-24 w-full resize-y rounded-[var(--rafii-radius-control)] px-3.5 py-3 text-base outline-none md:text-sm'
            />
            <div className='flex items-center justify-between gap-3'>
              <span className='text-muted-foreground text-xs'>Saved privately. Never quoted publicly unless you allow it.</span>
              <Button variant='glass' size='sm' disabled={!note.trim() || adding} onClick={() => void addNote()}>
                {adding ? <Icons.spinner className='animate-spin' /> : <Icons.add />}
                Add note
              </Button>
            </div>
            {error && (
              <p role='alert' className='text-foreground text-xs'>
                {error}
              </p>
            )}
          </div>
          <p className='text-muted-foreground text-xs'>
            <Link href='/app/ideas' className='text-foreground underline underline-offset-2'>
              Manage sources
            </Link>
          </p>
        </RafiiDialogBody>
        <RafiiDialogFooter>
          <Button variant='action' size='control' className='w-full' onClick={() => { onIncludedChange(staged.filter((id) => usable.some((s) => s.id === id))); onOpenChange(false); }}>
            Done · {staged.filter((id) => usable.some((s) => s.id === id)).length} included
            <Icons.check />
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
