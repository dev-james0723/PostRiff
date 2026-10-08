'use client';

import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { LibrarySuggestion } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey } from '@/lib/library/batch';
import { SUGGESTION_CATEGORY_LABEL, affectedLabel, capLine, clampSnoozeDays, suggestionEnvelope, type SuggestionStateAction } from '@/lib/library/proactive';
import { relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function SuggestionItem({
  item,
  snoozeDefault,
  canDisable,
  canEdit,
  onOpen,
  onChange
}: {
  item: LibrarySuggestion;
  snoozeDefault: number;
  canDisable: boolean;
  canEdit: boolean;
  onOpen: (assetId: string) => void;
  onChange: (item: LibrarySuggestion, action: SuggestionStateAction, snoozeDays?: number) => Promise<string | null>;
}) {
  const [days, setDays] = useState(snoozeDefault);
  const [busy, setBusy] = useState<SuggestionStateAction | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const first = item.candidateRefs[0];

  async function run(action: SuggestionStateAction) {
    setBusy(action);
    setMessage(await onChange(item, action, action === 'snooze' ? days : undefined));
    setBusy(null);
  }

  return (
    <li className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3'>
      <p className='flex flex-wrap items-center gap-2 text-sm font-medium'>
        {item.critical ? <Icons.warning className='size-4' aria-hidden /> : <Icons.info className='size-4' aria-hidden />}
        {SUGGESTION_CATEGORY_LABEL[item.category] ?? item.category}
        {item.critical ? <span className='text-muted-foreground text-xs font-normal'>· Warning</span> : null}
      </p>
      <p className='text-sm'>{item.reason}</p>
      {item.affected.length ? (
        <p className='text-muted-foreground text-xs'>
          Affects: {item.affected.slice(0, 5).map(affectedLabel).join(', ')}
          {item.affected.length > 5 ? ` and ${item.affected.length - 5} more` : ''}
        </p>
      ) : null}
      {item.createdAt ? <p className='text-muted-foreground text-xs'>Found {relativeTime(item.createdAt)}</p> : null}
      <div className='flex flex-wrap items-center gap-2'>
        {item.actions.includes('open') && first ? (
          <Button variant='glass' size='control' className='h-11' onClick={() => onOpen(first.assetId)}>
            {item.category === 'outdated_source' ? 'Review' : 'Open'}
          </Button>
        ) : null}
        {item.actions.includes('apply') && canEdit ? (
          <Button variant='glass' size='control' className='h-11' disabled={busy !== null} onClick={() => void run('apply')}>
            Create this collection
          </Button>
        ) : null}
        {item.actions.includes('dismiss') ? (
          <Button variant='quiet' size='control' className='h-11' disabled={busy !== null} onClick={() => void run('dismiss')}>
            Dismiss
          </Button>
        ) : null}
        {item.actions.includes('snooze') ? (
          <span className='flex items-center gap-1.5'>
            <Button variant='quiet' size='control' className='h-11' disabled={busy !== null} onClick={() => void run('snooze')}>
              Snooze for
            </Button>
            <Input
              type='number'
              min={1}
              max={90}
              aria-label='Snooze for how many days'
              value={days}
              onChange={(event) => setDays(clampSnoozeDays(event.target.value))}
              className='h-11 w-16'
            />
            <span className='text-muted-foreground text-xs'>days</span>
          </span>
        ) : null}
        {item.actions.includes('disable_category') && canDisable && !item.critical ? (
          <Button variant='quiet' size='control' className='h-11' disabled={busy !== null} onClick={() => void run('disable_category')}>
            Don’t suggest this kind
          </Button>
        ) : null}
      </div>
      {item.critical ? <p className='text-muted-foreground text-xs'>Warnings about permissions and sources can’t be turned off.</p> : null}
      {message ? <p className='text-muted-foreground text-xs'>{message}</p> : null}
    </li>
  );
}

/**
 * "Suggested for you" (PRD R14): a quiet list inside the Library, with no counters or urgency colours and no pop-ups. It states
 * its daily cap and that it stays in Rafii, and every item can be dismissed or snoozed.
 */
export function SuggestionsPanel({ enabled, canEdit, onOpen, onAnnounce }: { enabled: boolean; canEdit: boolean; onOpen: (assetId: string) => void; onAnnounce: (message: string) => void }) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const inbox = useQuery({ queryKey: ['library-suggestions', workspaceId], queryFn: () => api.librarySuggestions(workspaceId), enabled: Boolean(workspaceId && enabled), retry: false, staleTime: 60_000, refetchOnWindowFocus: false });
  const keys = useRef<Record<string, string>>({});
  if (!enabled || !inbox.data) return null;
  const data = inbox.data;
  const open = data.suggestions.filter((item) => item.state === 'new' || item.state === 'seen');
  if (!open.length) return null;

  async function change(item: LibrarySuggestion, action: SuggestionStateAction, snoozeDays?: number): Promise<string | null> {
    const envelope = suggestionEnvelope(item, action, { snoozeDays, actionId: `suggestion-${Date.now()}` });
    if (!envelope) return 'This suggestion doesn’t allow that.';
    const slot = `${item.id}:${action}:${snoozeDays ?? ''}`;
    keys.current[slot] ??= newIdempotencyKey('lib-suggestion', randomKey);
    try {
      const result = await api.libraryAction(workspaceId, { ...envelope, idempotencyKey: keys.current[slot] });
      if (result.status !== 'applied') return result.warnings?.[0] || 'That didn’t change anything.';
      await client.invalidateQueries({ queryKey: ['library-suggestions', workspaceId] });
      if (action === 'apply') await client.invalidateQueries({ queryKey: ['library-collections', workspaceId] });
      const done = action === 'dismiss' ? 'Dismissed.' : action === 'snooze' ? `Snoozed for ${clampSnoozeDays(snoozeDays)} days.` : action === 'apply' ? 'Collection created. You can undo it from the collection.' : 'Suggestions of this kind are off.';
      onAnnounce(done);
      return done;
    } catch (failure) {
      return failure instanceof Error ? failure.message : 'That didn’t change anything.';
    }
  }

  return (
    <details className='group/suggestions rafii-quiet rounded-[var(--rafii-radius-card)] px-3'>
      <summary className='rafii-focus flex min-h-11 cursor-pointer items-center justify-between gap-2 text-sm'>
        <span>
          Suggested for you <span className='text-muted-foreground'>({open.length})</span>
        </span>
        <Icons.chevronDown className='size-4 transition-transform group-open/suggestions:rotate-180 motion-reduce:transition-none' aria-hidden />
      </summary>
      <div className='flex flex-col gap-2 pb-3'>
        <ul className='flex flex-col gap-2' aria-label='Suggestions'>
          {open.map((item) => (
            <SuggestionItem
              key={item.id}
              item={item}
              snoozeDefault={data.preferences[item.category]?.snoozeDays ?? 7}
              canDisable={data.preferences[item.category]?.canDisable ?? !item.critical}
              canEdit={canEdit}
              onOpen={onOpen}
              onChange={change}
            />
          ))}
        </ul>
        <p className='text-muted-foreground text-xs'>{capLine(data)}</p>
        <p className='text-muted-foreground text-xs'>{data.delivery.note}</p>
        {!data.proactiveEnabled ? <p className='text-muted-foreground text-xs'>Proactive suggestions are off here; version and permission warnings still appear.</p> : null}
      </div>
    </details>
  );
}
