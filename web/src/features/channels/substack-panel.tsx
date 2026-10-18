'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { SegmentedControl } from '@/components/rafii/segmented-control';
import { StateMessage } from '@/components/rafii/state-message';
import { Surface } from '@/components/rafii/surface';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/client';
import { allows } from '@/lib/auth/permissions';
import { useWorkspace } from '@/lib/workspace/provider';
import {
  activeSubstackConnection,
  approvedSubstackDraft,
  fromSubstackLocalDateTime,
  safeSubstackHref,
  SUBSTACK_CAPABILITY_LABELS,
  SUBSTACK_STATUS_LABELS,
  substackAvailable,
  substackConnectionClaims,
  substackHandoffMarkdown,
  toSubstackLocalDateTime
} from '@/lib/substack/presentation';
import type {
  SubstackAudience,
  SubstackCapabilities,
  SubstackConnection,
  SubstackContentType,
  SubstackDraft,
  SubstackDraftInput,
  SubstackFeedResult,
  SubstackHandoff,
  SubstackWorkspace
} from '@/lib/substack/types';
import { cn } from '@/lib/utils';

type SubstackTab = 'publications' | 'drafts' | 'access';
type SubstackCommand =
  | { type: 'add_feed'; publicationUrl: string }
  | { type: 'remove_feed' | 'refresh_feed'; id: string }
  | { type: 'save_draft'; id?: string; input: Omit<SubstackDraftInput, 'expectedRevision'> }
  | { type: 'approve' | 'handoff' | 'cancel_draft' | 'delete_draft'; id: string; contentHash: string };
type MutationResult = SubstackWorkspace & { handoff?: SubstackHandoff; feed?: SubstackFeedResult['feed'] };
type RunCommand = (command: SubstackCommand) => Promise<MutationResult>;

const SUBSTACK_QUERY = (workspaceId: string) => ['substack', workspaceId] as const;
const SELECT_CLASS = 'rafii-field rafii-focus h-11 w-full rounded-[var(--rafii-radius-control)] px-3 text-sm disabled:opacity-50';
const DRAFT_STATUS: Record<string, string> = {
  draft: 'Draft',
  approved: 'Approved for manual handoff',
  handoff_ready: 'Manual action required',
  canceled: 'Canceled'
};

export function SubstackProviderTile({ onOpen }: { onOpen: () => void }) {
  return (
    <Surface material='quiet' radius='card' padding='md' className='flex h-full flex-col gap-3' data-testid='substack-entry'>
      <div className='flex items-center gap-2.5'>
        <ChannelIcon platform='Substack' name='Substack' size='md' />
        <span className='text-foreground font-medium'>Substack</span>
      </div>
      <p className='text-muted-foreground text-[13px] leading-relaxed'>
        Save a publication feed, prepare drafts and finish publishing in Substack. Account and analytics access are shown separately.
      </p>
      <div className='mt-auto pt-1'>
        <Button variant='glass' size='control' onClick={onOpen}>
          Open Substack
          <Icons.arrowRight className='size-4' aria-hidden />
        </Button>
      </div>
    </Surface>
  );
}

/** A workspace switch destroys unsaved editor/feed/receipt state; it never carries content into another workspace. */
export function SubstackPanel({ onClose, requestedDraftId }: { onClose: () => void; requestedDraftId?: string }) {
  const { workspaceId } = useWorkspace();
  if (!workspaceId) return null;
  return <SubstackWorkspacePanel key={`${workspaceId}:${requestedDraftId ?? ''}`} workspaceId={workspaceId} onClose={onClose} requestedDraftId={requestedDraftId} />;
}

function SubstackWorkspacePanel({ workspaceId, onClose, requestedDraftId }: { workspaceId: string; onClose: () => void; requestedDraftId?: string }) {
  const { api } = useWorkspace();
  const client = useQueryClient();
  const [tab, setTab] = useState<SubstackTab>(requestedDraftId ? 'drafts' : 'publications');
  const [notice, setNotice] = useState<string | null>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [closeRequested, setCloseRequested] = useState(false);
  const [draftTarget, setDraftTarget] = useState<{ connectionId: string; sequence: number } | null>(null);
  const [pendingDraftTarget, setPendingDraftTarget] = useState<string | null>(null);
  const [feed, setFeed] = useState<{ connectionId: string; data: SubstackFeedResult['feed'] } | null>(null);
  const query = useQuery({
    queryKey: SUBSTACK_QUERY(workspaceId),
    queryFn: () => api.substackWorkspace(workspaceId),
    retry: false
  });
  const data = query.data;
  const mutation = useMutation({
    mutationFn: async (command: SubstackCommand): Promise<MutationResult> => {
      if (!data?.enabled) throw new Error('Substack is not available in this workspace.');
      const expectedRevision = data.revision;
      switch (command.type) {
        case 'add_feed':
          return api.substackAddFeed(workspaceId, { expectedRevision, publicationUrl: command.publicationUrl, mode: 'public_feed', confirmed: true });
        case 'remove_feed':
          return api.substackDisconnect(workspaceId, command.id, { expectedRevision });
        case 'refresh_feed':
          return api.substackRefreshFeed(workspaceId, command.id, { expectedRevision });
        case 'save_draft':
          return command.id
            ? api.substackUpdateDraft(workspaceId, command.id, { ...command.input, expectedRevision })
            : api.substackCreateDraft(workspaceId, { ...command.input, expectedRevision });
        case 'approve':
          return api.substackApproveDraft(workspaceId, command.id, { expectedRevision, contentHash: command.contentHash, confirmed: true });
        case 'handoff':
          return api.substackHandoff(workspaceId, command.id, { expectedRevision, contentHash: command.contentHash });
        case 'cancel_draft':
          return api.substackCancelDraft(workspaceId, command.id, { expectedRevision, contentHash: command.contentHash });
        case 'delete_draft':
          return api.substackDeleteDraft(workspaceId, command.id, { expectedRevision, contentHash: command.contentHash });
      }
    },
    onMutate: () => setNotice(null),
    onSuccess: (result, command) => {
      // A receipt changes the workspace cache only after the hosted API accepts it. No optimistic approval or connection.
      client.setQueryData(SUBSTACK_QUERY(workspaceId), result);
      void client.invalidateQueries({ queryKey: ['snapshot', workspaceId] });
      void client.invalidateQueries({ queryKey: ['audit', workspaceId] });
      if (command.type === 'refresh_feed' && result.feed) {
        setFeed({ connectionId: command.id, data: result.feed });
        setNotice('Public feed refreshed. This does not authenticate the publication account.');
      } else if (command.type === 'remove_feed') {
        if (feed?.connectionId === command.id) setFeed(null);
        setNotice('Saved feed removed. Drafts for that publication cannot be handed off while it is disconnected.');
      } else if (command.type === 'add_feed') {
        setNotice('Public feed added. Ownership, account authorization and analytics have not been verified.');
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        void client.invalidateQueries({ queryKey: SUBSTACK_QUERY(workspaceId) });
      }
    }
  });

  const error = mutation.error ?? query.error;
  const errorMessage = error instanceof ApiError && error.status === 409
    ? 'This workspace changed while you were reviewing it. Check the latest saved version before trying again.'
    : error instanceof Error ? error.message : 'Substack data could not be loaded.';

  const updateDraftDirty = useCallback((value: boolean) => {
    setDraftDirty(value);
    if (!value) setCloseRequested(false);
  }, []);

  function startDraft(connectionId: string) {
    setDraftTarget((previous) => ({ connectionId, sequence: (previous?.sequence ?? 0) + 1 }));
    setPendingDraftTarget(null);
    updateDraftDirty(false);
  }

  function openDrafts(connectionId?: string) {
    setTab('drafts');
    if (!connectionId) return;
    if (draftDirty) setPendingDraftTarget(connectionId);
    else startDraft(connectionId);
  }

  return (
    <Surface as='section' id='substack-workspace-panel' material='glass' radius='card' padding='lg' className='scroll-mt-8 flex flex-col gap-5' aria-labelledby='substack-panel-title'>
      <div className='flex items-start justify-between gap-3'>
        <div className='flex min-w-0 items-center gap-3'>
          <ChannelIcon platform='Substack' name='Substack' size='md' />
          <div>
            <h2 id='substack-panel-title' className='text-foreground text-lg font-medium tracking-tight'>Substack</h2>
            <p className='text-muted-foreground text-sm'>Publications, drafts and access for this workspace</p>
          </div>
        </div>
        <Button variant='quiet' size='icon-control' onClick={() => draftDirty ? setCloseRequested(true) : onClose()} aria-label='Close Substack'>
          <Icons.close className='size-4' aria-hidden />
        </Button>
      </div>
      {closeRequested && <StateMessage kind='stale' layout='inline' title='This draft has unsaved changes' description='Keep editing to save your changes, or close and discard the unsaved text.' action={<><Button variant='glass' size='control' onClick={() => setCloseRequested(false)}>Keep editing</Button><Button variant='quiet' size='control' onClick={onClose}>Discard changes & close</Button></>} />}
      {query.isPending ? (
        <StateMessage kind='loading' title='Loading Substack workspace…' />
      ) : !data ? (
        <StateMessage kind='error' title="Couldn't load Substack" description={errorMessage} action={<Button variant='glass' size='control' onClick={() => void query.refetch()}>Try again</Button>} />
      ) : !data.enabled ? (
        <StateMessage kind='partial' title='Substack is not enabled in this workspace' description='Existing publication and draft access will appear here when this workspace is enabled.' />
      ) : (
        <>
          <SegmentedControl<SubstackTab>
            options={[{ value: 'publications', label: 'Publications' }, { value: 'drafts', label: 'Drafts & handoff' }, { value: 'access', label: 'Access & capabilities' }]}
            value={tab} onChange={setTab} label='Substack workspace view' widths='content'
          />
          {error && <StateMessage kind='error' layout='inline' title='Action not completed' description={errorMessage} action={<Button variant='quiet' size='control' onClick={() => { mutation.reset(); void query.refetch(); }}>Reload latest state</Button>} />}
          {notice && <StateMessage kind='success' layout='inline' title={notice} />}
          {pendingDraftTarget && <StateMessage kind='stale' layout='inline' title='Save your changes before starting another draft' description={`The requested destination is ${data.connections.find((item) => item.id === pendingDraftTarget)?.publicationUrl ?? 'another publication'}. Your current text is still in the editor.`} action={<><Button variant='glass' size='control' onClick={() => setPendingDraftTarget(null)}>Keep editing this draft</Button><Button variant='quiet' size='control' onClick={() => startDraft(pendingDraftTarget)}>Discard changes & start draft</Button></>} />}
          <div hidden={tab !== 'publications'}><SubstackPublications data={data} feed={feed} run={mutation.mutateAsync} pending={mutation.isPending} onDrafts={openDrafts} onAccess={() => setTab('access')} /></div>
          <div hidden={tab !== 'drafts'}><SubstackDrafts key={draftTarget?.sequence ?? 0} initialConnectionId={draftTarget?.connectionId} initialDraftId={draftTarget ? undefined : requestedDraftId} data={data} run={mutation.mutateAsync} pending={mutation.isPending} onPublications={() => setTab('publications')} onDirtyChange={updateDraftDirty} /></div>
          <div hidden={tab !== 'access'}><SubstackAccess capabilities={data.capabilities} onDrafts={() => setTab('drafts')} /></div>
        </>
      )}
    </Surface>
  );
}

function SubstackPublications({ data, feed, run, pending, onDrafts, onAccess }: {
  data: SubstackWorkspace;
  feed: { connectionId: string; data: SubstackFeedResult['feed'] } | null;
  run: RunCommand;
  pending: boolean;
  onDrafts: (connectionId?: string) => void;
  onAccess: () => void;
}) {
  const [url, setUrl] = useState('');
  const [consent, setConsent] = useState(false);
  const canManage = allows(data.membership, 'manage_connections');
  const available = data.connections.filter(activeSubstackConnection);

  async function addFeed(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!consent || pending || !canManage) return;
    try {
      await run({ type: 'add_feed', publicationUrl: url.trim() });
      setUrl('');
      setConsent(false);
    } catch { /* The workspace action state displays the server error; retain the input. */ }
  }

  return (
    <div className='flex flex-col gap-5'>
      <div className='grid gap-4 lg:grid-cols-2'>
        <div className='flex flex-col gap-3'>
          <h3 className='text-foreground font-medium'>Add a public publication</h3>
          <p className='text-muted-foreground text-sm leading-relaxed'>Save a public feed as a reference and a destination for drafts. A publication URL does not prove ownership or authorize publishing.</p>
          {canManage && substackAvailable(data.capabilities, 'public_feed_read') ? (
            <form onSubmit={addFeed} className='flex flex-col gap-3'>
              <label htmlFor='substack-publication-url' className='text-sm font-medium'>Publication URL</label>
              <Input id='substack-publication-url' type='url' required maxLength={2048} placeholder='https://yourpublication.substack.com' value={url} onChange={(event) => setUrl(event.target.value)} disabled={pending} className='h-11' autoComplete='off' aria-describedby='substack-feed-scope' />
              <p id='substack-feed-scope' className='text-muted-foreground text-xs'>Use the publication’s public Substack address. Paid feeds, sign-in links and session credentials are not accepted.</p>
              <label htmlFor='substack-feed-consent' className='flex min-h-11 cursor-pointer items-start gap-2 text-sm leading-relaxed'>
                <input id='substack-feed-consent' type='checkbox' aria-label='I have permission to use this public feed in this workspace' checked={consent} onChange={(event) => setConsent(event.target.checked)} disabled={pending} className='mt-1 size-4 shrink-0' />
                I have permission to use this public feed in this workspace.
              </label>
              <Button type='submit' variant='action' size='control' disabled={pending || !consent || !url.trim()} className='self-start'>
                <Icons.add className='size-4' aria-hidden />
                Add public feed
              </Button>
            </form>
          ) : <p className='text-muted-foreground text-sm'>{canManage ? data.capabilities.public_feed_read?.reason ?? 'Public feed access is unavailable.' : 'A workspace owner or member with connection permissions can add a publication.'}</p>}
        </div>
        <Surface material='quiet' radius='card' padding='md' className='flex flex-col items-start gap-3'>
          <h3 className='text-foreground font-medium'>Account authorization</h3>
          <p className='text-muted-foreground text-sm leading-relaxed'>Official account, analytics and publishing permissions are separate from a saved feed. Check the available connection methods and publication requirements.</p>
          <Button variant='glass' size='control' onClick={onAccess}>View access options <Icons.arrowRight className='size-4' aria-hidden /></Button>
        </Surface>
      </div>
      {available.length === 0 ? <StateMessage kind='empty' title='No publications saved' description='Add a public publication to start drafting for it. This will not connect its private account.' /> : (
        <div className='flex flex-col gap-4'>
          {available.map((connection) => {
            const href = safeSubstackHref(connection.publicationUrl);
            const currentFeed = feed?.connectionId === connection.id ? feed.data : null;
            return (
              <Surface key={connection.id} material='quiet' radius='card' padding='md' className='flex flex-col gap-3'>
                <div className='flex flex-wrap items-start justify-between gap-3'>
                  <div className='min-w-0'>
                    <h3 className='text-foreground text-sm font-medium break-all'>{connection.publicationUrl}</h3>
                    {href && <a href={href} target='_blank' rel='noopener noreferrer' className='rafii-focus text-muted-foreground inline-flex min-h-11 items-center gap-1 rounded-sm text-sm underline underline-offset-2'>Open publication <Icons.externalLink className='size-3.5' aria-hidden /></a>}
                  </div>
                  <Button variant='glass' size='control' disabled={pending} onClick={() => onDrafts(allows(data.membership, 'edit') && substackAvailable(data.capabilities, 'draft_create') ? connection.id : undefined)}>{allows(data.membership, 'edit') && substackAvailable(data.capabilities, 'draft_create') ? 'Prepare a draft' : 'View drafts'}</Button>
                </div>
                <ul className='grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-3' aria-label='Publication verification and permissions'>
                  {substackConnectionClaims(connection).map((claim) => (
                    <li key={claim.label} className='text-muted-foreground flex items-center gap-1.5'>
                      {claim.verified ? <Icons.check className='size-3.5 shrink-0' aria-hidden /> : <Icons.minus className='size-3.5 shrink-0' aria-hidden />}
                      <span>{claim.label}: {claim.verified ? 'Yes' : 'No'}</span>
                    </li>
                  ))}
                </ul>
                <div className='flex flex-wrap gap-2'>
                  {allows(data.membership, 'read') && substackAvailable(data.capabilities, 'public_feed_read') && <Button variant='glass' size='control' disabled={pending} onClick={() => void run({ type: 'refresh_feed', id: connection.id }).catch(() => {})}><Icons.refresh className='size-4' aria-hidden />Read public feed</Button>}
                  {canManage && substackAvailable(data.capabilities, 'public_feed_remove') && <Button variant='quiet' size='control' disabled={pending} onClick={() => void run({ type: 'remove_feed', id: connection.id }).catch(() => {})}>Remove saved feed</Button>}
                </div>
                {currentFeed && <PublicFeedPreview feed={currentFeed} connection={connection} />}
              </Surface>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PublicFeedPreview({ feed, connection }: { feed: SubstackFeedResult['feed']; connection: SubstackConnection }) {
  return (
    <div className='border-border flex flex-col gap-2 border-t pt-3'>
      <p className='text-muted-foreground text-xs'>Source: public feed · private subscriber and paid content access are not connected</p>
      {feed.items.length === 0 ? <p className='text-muted-foreground text-sm'>The feed returned no public items.</p> : (
        <ul className='flex flex-col gap-3'>
          {feed.items.slice(0, 10).map((item, index) => {
            const href = safeSubstackHref(item.url ?? item.link, connection.publicationUrl);
            return <li key={item.id ?? `${item.url ?? 'item'}-${index}`} className='flex flex-col gap-1'>
              {href ? <a href={href} target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground rounded-sm text-sm font-medium underline underline-offset-2'>{item.title}</a> : <p className='text-foreground text-sm font-medium'>{item.title}</p>}
              {item.summary && <p className='text-muted-foreground line-clamp-3 text-sm leading-relaxed'>{item.summary}</p>}
            </li>;
          })}
        </ul>
      )}
    </div>
  );
}

function SubstackDrafts({ initialConnectionId, initialDraftId, data, run, pending, onPublications, onDirtyChange }: { initialConnectionId?: string; initialDraftId?: string; data: SubstackWorkspace; run: RunCommand; pending: boolean; onPublications: () => void; onDirtyChange: (value: boolean) => void }) {
  const [selectedId, setSelectedId] = useState<string | null>(() => initialConnectionId ? null : initialDraftId ?? data.drafts[0]?.id ?? null);
  const [dirty, setDirty] = useState(false);
  const [nextSelection, setNextSelection] = useState<{ id: string | null } | null>(null);
  const updateDirty = useCallback((value: boolean) => { setDirty(value); onDirtyChange(value); }, [onDirtyChange]);
  const draft = data.drafts.find((item) => item.id === selectedId);
  const canEdit = allows(data.membership, 'edit');
  const hasPublication = data.connections.some(activeSubstackConnection);
  const needsPublication = <StateMessage kind='partial' title='Choose a publication first' description='A saved publication gives each draft a clear destination. It does not grant account or publishing access.' action={<Button variant='glass' size='control' onClick={onPublications}>Go to publications</Button>} />;
  function selectDraft(id: string | null) {
    if (id === selectedId) return;
    if (dirty) setNextSelection({ id });
    else setSelectedId(id);
  }
  function saved(id: string | null) {
    updateDirty(false);
    setNextSelection(null);
    setSelectedId(id);
  }
  if (!hasPublication && data.drafts.length === 0) return selectedId ? <StateMessage kind='partial' title='This draft is not available in this workspace' /> : needsPublication;
  return (
    <div className='grid gap-5 lg:grid-cols-[minmax(12rem,0.7fr)_minmax(0,2fr)]'>
      {nextSelection && <div className='lg:col-span-2'><StateMessage kind='stale' layout='inline' title='Save your changes before switching drafts' description='Your current text is still in the editor.' action={<><Button variant='glass' size='control' onClick={() => setNextSelection(null)}>Keep editing this draft</Button><Button variant='quiet' size='control' onClick={() => saved(nextSelection.id)}>Discard changes & switch</Button></>} /></div>}
      <div className='flex flex-col gap-3'>
        <div className='flex items-center justify-between gap-2'>
          <h3 className='font-medium'>Saved drafts</h3>
          {canEdit && substackAvailable(data.capabilities, 'draft_create') && <Button variant='glass' size='control' onClick={() => selectDraft(null)} disabled={pending || !hasPublication}>New draft</Button>}
        </div>
        {data.drafts.length === 0 ? <p className='text-muted-foreground text-sm'>Your saved drafts will appear here.</p> : (
          <ul className='flex flex-col gap-2' aria-label='Substack drafts'>
            {data.drafts.map((item) => (
              <li key={item.id}>
                <button type='button' onClick={() => selectDraft(item.id)} disabled={pending} aria-pressed={selectedId === item.id} className={cn('rafii-focus flex w-full flex-col gap-1 rounded-[var(--rafii-radius-control)] p-3 text-left', selectedId === item.id ? 'rafii-glass-selected' : 'rafii-quiet')}>
                  <span className='text-foreground line-clamp-2 text-sm font-medium'>{item.title || (item.contentType === 'note' ? 'Untitled Note' : 'Untitled draft')}</span>
                  <span className='text-muted-foreground text-xs'>{DRAFT_STATUS[item.status] ?? 'Status unavailable'}</span>
                  {item.scheduledFor && <span className='text-muted-foreground text-xs'>Target: {new Date(item.scheduledFor).toLocaleString()}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {selectedId && !draft ? <StateMessage kind='partial' title='This draft is no longer available' /> : !draft && !hasPublication ? needsPublication : <SubstackDraftEditor key={selectedId ?? 'new'} initialConnectionId={initialConnectionId} draft={draft} data={data} run={run} pending={pending} onSaved={saved} onDeleted={() => saved(null)} onDirtyChange={updateDirty} />}
    </div>
  );
}

function SubstackDraftEditor({ initialConnectionId, draft, data, run, pending, onSaved, onDeleted, onDirtyChange }: { initialConnectionId?: string; draft: SubstackDraft | undefined; data: SubstackWorkspace; run: RunCommand; pending: boolean; onSaved: (id: string) => void; onDeleted: () => void; onDirtyChange: (value: boolean) => void }) {
  const [connectionId, setConnectionId] = useState(draft?.connectionId ?? initialConnectionId ?? data.connections.find(activeSubstackConnection)?.id ?? '');
  const [title, setTitle] = useState(draft?.title ?? '');
  const [body, setBody] = useState(draft?.body ?? '');
  const [scheduledFor, setScheduledFor] = useState(toSubstackLocalDateTime(draft?.scheduledFor));
  const [contentType, setContentType] = useState<SubstackContentType>(draft?.contentType ?? 'article');
  const [audience, setAudience] = useState<SubstackAudience>(draft?.audience ?? 'everyone');
  const [loadedHash, setLoadedHash] = useState(draft?.contentHash ?? null);
  const [reviewed, setReviewed] = useState(false);
  const [preview, setPreview] = useState(false);
  const [handoff, setHandoff] = useState<SubstackHandoff | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const canEdit = allows(data.membership, 'edit');
  const canApprove = allows(data.membership, 'approve');
  const connection = data.connections.find((item) => item.id === connectionId);
  const connectionActive = Boolean(connection && activeSubstackConnection(connection));
  const serverChanged = Boolean(draft && loadedHash && draft.contentHash !== loadedHash);
  const dirty = !draft || title !== draft.title || body !== draft.body || connectionId !== draft.connectionId || scheduledFor !== toSubstackLocalDateTime(draft.scheduledFor) || contentType !== (draft.contentType ?? 'article') || audience !== (draft.audience ?? 'everyone');
  const editable = canEdit && !pending && !serverChanged;
  const approved = Boolean(draft && approvedSubstackDraft(draft, connection));
  const canSave = editable && connectionActive && (contentType === 'note' || title.trim().length > 0) && body.trim().length > 0 && substackAvailable(data.capabilities, draft ? 'draft_edit' : 'draft_create');
  const currentHandoff = handoff && draft && !dirty && !serverChanged && approved && handoff.contentHash === draft.contentHash ? handoff : null;
  const hasUnsavedText = dirty && Boolean(draft || title || body);
  useEffect(() => { onDirtyChange(hasUnsavedText); }, [hasUnsavedText, onDirtyChange]);

  function changed() {
    setReviewed(false);
    setHandoff(null);
    setMessage(null);
    setLocalError(null);
    setDeleteConfirm(false);
  }

  function reloadDraft() {
    if (!draft) return;
    setConnectionId(draft.connectionId);
    setTitle(draft.title);
    setBody(draft.body);
    setScheduledFor(toSubstackLocalDateTime(draft.scheduledFor));
    setContentType(draft.contentType ?? 'article');
    setAudience(draft.audience ?? 'everyone');
    setLoadedHash(draft.contentHash);
    changed();
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) return;
    setLocalError(null);
    try {
      const result = await run({ type: 'save_draft', id: draft?.id, input: { connectionId, title, body, contentType, audience, scheduledFor: fromSubstackLocalDateTime(scheduledFor) } });
      const saved = draft ? result.drafts.find((item) => item.id === draft.id) : result.drafts.find((item) => !data.drafts.some((old) => old.id === item.id));
      if (!saved) throw new Error('The workspace did not return a saved draft. Reload the latest state before trying again.');
      setTitle(saved.title);
      setBody(saved.body);
      setLoadedHash(saved.contentHash);
      setScheduledFor(toSubstackLocalDateTime(saved.scheduledFor));
      setContentType(saved.contentType ?? 'article');
      setAudience(saved.audience ?? 'everyone');
      setReviewed(false);
      setHandoff(null);
      setMessage('Draft saved in Rafii. Any previous approval must be reviewed again.');
      onSaved(saved.id);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'The draft could not be saved.');
    }
  }

  async function approve() {
    if (!draft || !reviewed || dirty || serverChanged || !connectionActive || !canApprove || pending) return;
    setLocalError(null);
    try {
      await run({ type: 'approve', id: draft.id, contentHash: draft.contentHash });
      setReviewed(false);
      setMessage('This saved version is approved for manual handoff. Nothing has been published.');
    } catch { /* The server error appears above the editor. */ }
  }

  async function prepareHandoff() {
    if (!draft || !approved || dirty || serverChanged || !canApprove || pending) return;
    setLocalError(null);
    try {
      const result = await run({ type: 'handoff', id: draft.id, contentHash: draft.contentHash });
      if (!result.handoff) throw new Error('The server did not return a handoff receipt.');
      substackHandoffMarkdown(result.handoff, draft.contentHash);
      setHandoff(result.handoff);
      setMessage(null);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'The manual handoff could not be prepared.');
    }
  }

  async function cancelDraft() {
    if (!draft || dirty || serverChanged || !canApprove || pending) return;
    try {
      await run({ type: 'cancel_draft', id: draft.id, contentHash: draft.contentHash });
      changed();
      setMessage('Approval and manual queue entry canceled. No Substack publication was changed.');
    } catch { /* The server error appears above the editor. */ }
  }

  async function deleteDraft() {
    if (!draft || !deleteConfirm || dirty || serverChanged || !canEdit || pending || !['draft', 'canceled'].includes(draft.status)) return;
    try {
      await run({ type: 'delete_draft', id: draft.id, contentHash: draft.contentHash });
      onDeleted();
    } catch { /* Keep the saved draft visible until the server confirms deletion. */ }
  }

  function downloadHandoff() {
    if (!currentHandoff || !draft) return;
    try {
      const markdown = substackHandoffMarkdown(currentHandoff, draft.contentHash);
      const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `substack-draft-${draft.id.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64)}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'The draft could not be exported.');
    }
  }

  return (
    <div className='flex min-w-0 flex-col gap-4'>
      <div>
        <h3 className='text-foreground font-medium'>{draft ? 'Review this draft' : 'Prepare a draft'}</h3>
        <p className='text-muted-foreground mt-1 text-sm leading-relaxed'>Save and review the text here, then finish in Substack. A target time organizes your work; it does not schedule automatic publishing or send email.</p>
      </div>
      {!canEdit && <p className='text-muted-foreground text-sm'>{canApprove ? 'You can review and approve saved drafts. An editor can make changes.' : 'You have read-only access to these drafts.'}</p>}
      {serverChanged && <StateMessage kind='stale' layout='inline' title='A newer saved version is available' description='Your text is still visible. Loading the saved version replaces this editor’s unsaved text.' action={<Button variant='glass' size='control' onClick={reloadDraft}>Load saved version</Button>} />}
      {localError && <StateMessage kind='error' layout='inline' title='Draft action not completed' description={localError} />}
      {message && <StateMessage kind='success' layout='inline' title={message} />}
      <form onSubmit={save} className='flex flex-col gap-4'>
        <fieldset disabled={!editable} className='flex min-w-0 flex-col gap-4'>
          <div className='flex flex-col gap-2'>
            <label htmlFor='substack-draft-publication' className='text-sm font-medium'>Destination publication</label>
            <select id='substack-draft-publication' className={SELECT_CLASS} value={connectionId} onChange={(event) => { changed(); setConnectionId(event.target.value); }} required>
              {!connectionActive && <option value={connectionId} disabled>Publication unavailable — choose another</option>}
              {data.connections.filter(activeSubstackConnection).map((item) => <option key={item.id} value={item.id}>{item.publicationUrl}</option>)}
            </select>
          </div>
          <div className='grid gap-3 sm:grid-cols-2'>
            <div className='flex flex-col gap-2'>
              <label htmlFor='substack-draft-kind' className='text-sm font-medium'>Content to prepare</label>
              <select id='substack-draft-kind' className={SELECT_CLASS} value={contentType} onChange={(event) => { changed(); const value = event.target.value as SubstackContentType; setContentType(value); if (value === 'note') setAudience('everyone'); }}>
                <option value='article'>Article / newsletter draft</option><option value='note'>Note draft</option><option value='podcast'>Podcast outline</option><option value='video'>Video post draft</option>
              </select>
            </div>
            <div className='flex flex-col gap-2'>
              <label htmlFor='substack-draft-audience' className='text-sm font-medium'>Audience to choose in Substack</label>
              <select id='substack-draft-audience' className={SELECT_CLASS} value={audience} disabled={contentType === 'note'} onChange={(event) => { changed(); setAudience(event.target.value as SubstackAudience); }}>
                <option value='everyone'>Everyone</option><option value='free'>Free subscribers</option><option value='paid'>Paid subscribers</option>
              </select>
            </div>
          </div>
          <div className='flex flex-col gap-2'>
            <label htmlFor='substack-draft-title' className='text-sm font-medium'>Title</label>
            <Input id='substack-draft-title' value={title} onChange={(event) => { changed(); setTitle(event.target.value); }} required={contentType !== 'note'} maxLength={300} className='h-11' aria-describedby={contentType === 'note' ? 'substack-note-title-help' : undefined} />
            {contentType === 'note' && <p id='substack-note-title-help' className='text-muted-foreground text-xs'>Optional for a Note. Leave the title empty to export only the Note text.</p>}
          </div>
          <div className='flex flex-col gap-2'>
            <label htmlFor='substack-draft-body' className='text-sm font-medium'>Draft text (Markdown)</label>
            <Textarea id='substack-draft-body' value={body} onChange={(event) => { changed(); setBody(event.target.value); }} required maxLength={100_000} className='min-h-64 font-mono text-sm' aria-describedby='substack-draft-media' />
            <p id='substack-draft-media' className='text-muted-foreground text-xs'>The export contains text and links. Add and verify images, audio, video and audience settings in Substack before publishing.</p>
          </div>
          {substackAvailable(data.capabilities, 'editorial_schedule') && <div className='flex max-w-sm flex-col gap-2'>
            <label htmlFor='substack-draft-target' className='text-sm font-medium'>Target handoff time (your local time)</label>
            <Input id='substack-draft-target' type='datetime-local' value={scheduledFor} onChange={(event) => { changed(); setScheduledFor(event.target.value); }} className='h-11' />
            <p className='text-muted-foreground text-xs'>Device time zone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Clear this field and save to remove the target time.</p>
          </div>}
        </fieldset>
        <div className='flex flex-wrap gap-2'>
          {canEdit && <Button type='submit' variant='action' size='control' disabled={!canSave || (!dirty && draft?.status !== 'canceled')}>{pending ? 'Saving…' : draft?.status === 'canceled' ? 'Save to reopen draft' : 'Save draft'}</Button>}
          <Button type='button' variant='glass' size='control' onClick={() => setPreview(!preview)} aria-expanded={preview} aria-controls='substack-draft-preview'>{preview ? 'Hide text preview' : 'Preview text'}</Button>
        </div>
      </form>
      {preview && <Surface id='substack-draft-preview' material='paper' radius='card' padding='md' className='flex flex-col gap-3'>
        <h4 className='text-foreground text-lg font-medium break-words'>{title || 'Untitled draft'}</h4>
        <p className='text-muted-foreground text-xs'>Text preview. Markdown and embedded HTML are shown as text.</p>
        <pre className='text-foreground font-sans text-sm leading-relaxed whitespace-pre-wrap break-words'>{body || 'Your draft text will appear here.'}</pre>
      </Surface>}
      {draft && (
        <div className='border-border flex flex-col gap-3 border-t pt-4'>
          <p className='text-muted-foreground text-sm'>{DRAFT_STATUS[draft.status] ?? 'Status unavailable'}{dirty ? ' · Save your changes before review' : ''}</p>
          {!connectionActive && <p className='text-muted-foreground text-sm'>This publication is disconnected. Choose an active publication and save again before review.</p>}
          {canApprove && substackAvailable(data.capabilities, 'draft_approval') && !approved && draft.status !== 'canceled' && <>
            <label htmlFor='substack-draft-reviewed' className='flex min-h-11 cursor-pointer items-start gap-2 text-sm leading-relaxed'>
              <input id='substack-draft-reviewed' type='checkbox' aria-label='I reviewed this saved version for manual handoff' checked={reviewed && !dirty && !serverChanged} onChange={(event) => setReviewed(event.target.checked)} disabled={pending || dirty || serverChanged || !connectionActive} className='mt-1 size-4 shrink-0' />
              I reviewed this saved version, its publication, audience and target time for manual handoff.
            </label>
            <Button variant='glass' size='control' disabled={pending || !reviewed || dirty || serverChanged || !connectionActive} onClick={() => void approve()} className='self-start'>Approve this draft</Button>
          </>}
          {canApprove && substackAvailable(data.capabilities, 'manual_handoff') && <Button variant='glass' size='control' disabled={pending || !approved || dirty || serverChanged} onClick={() => void prepareHandoff()} className='self-start'>Prepare manual handoff</Button>}
          {canApprove && ['approved', 'handoff_ready'].includes(draft.status) && <Button variant='quiet' size='control' disabled={pending || dirty || serverChanged} onClick={() => void cancelDraft()} className='self-start'>Cancel approval & handoff</Button>}
          {!approved && <p className='text-muted-foreground text-xs'>Manual handoff requires approval of the exact saved version.</p>}
          {canEdit && ['draft', 'canceled'].includes(draft.status) && <div className='flex flex-col items-start gap-2'>
            {deleteConfirm ? <>
              <p className='text-muted-foreground text-sm'>Delete this saved Rafii draft and its manual queue entry? The text cannot be restored from this workspace.</p>
              <div className='flex gap-2'><Button variant='destructive' size='control' disabled={pending || dirty || serverChanged} onClick={() => void deleteDraft()}>Delete saved draft</Button><Button variant='quiet' size='control' onClick={() => setDeleteConfirm(false)}>Keep draft</Button></div>
            </> : <Button variant='quiet' size='control' disabled={pending || dirty || serverChanged} onClick={() => setDeleteConfirm(true)}>Delete draft…</Button>}
          </div>}
        </div>
      )}
      {currentHandoff && <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-3' data-testid='substack-handoff-receipt'>
        <h4 className='text-foreground font-medium'>Ready to finish in Substack</h4>
        <p className='text-muted-foreground text-sm'>Rafii has prepared the approved text. You still need to paste it into the right publication, review its formatting and audience, then publish or schedule it in Substack.</p>
        <p className='text-foreground text-sm font-medium'>Manual action required · Not published · No email sent</p>
        {currentHandoff.scheduledFor && <p className='text-muted-foreground text-sm'>Target handoff time: {new Date(currentHandoff.scheduledFor).toLocaleString()}</p>}
        <div className='flex flex-wrap gap-2'>
          <Button variant='action' size='control' onClick={downloadHandoff}><Icons.download className='size-4' aria-hidden />Download approved Markdown</Button>
          <a href={safeSubstackHref(currentHandoff.publicationUrl) ?? undefined} target='_blank' rel='noopener noreferrer' className={buttonVariants({ variant: 'glass', size: 'control' })}>Open publication <Icons.externalLink className='size-4' aria-hidden /></a>
        </div>
      </Surface>}
    </div>
  );
}

function SubstackAccess({ capabilities, onDrafts }: { capabilities: SubstackCapabilities; onDrafts: () => void }) {
  return (
    <div className='flex flex-col gap-5'>
      <div className='grid gap-4 lg:grid-cols-2'>
        <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-3'>
          <h3 className='text-foreground font-medium'>Official analytics connection</h3>
          <p className='text-muted-foreground text-sm leading-relaxed'>Substack’s official MCP requires an Admin of an eligible Bestseller publication. It provides read-only publication data. It cannot publish articles or Notes.</p>
          <p className='text-muted-foreground text-sm'>{capabilities.publication_analytics?.reason ?? 'Rafii’s official analytics authorization is not available for this workspace.'}</p>
          <a href='https://support.substack.com/hc/en-us/articles/50834026608916-How-to-connect-Substack-to-your-AI-Assistant' target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground inline-flex min-h-11 items-center gap-1 self-start rounded-sm text-sm underline underline-offset-2'>Check Substack eligibility <Icons.externalLink className='size-3.5' aria-hidden /></a>
        </Surface>
        <Surface material='quiet' radius='card' padding='md' className='flex flex-col gap-3'>
          <h3 className='text-foreground font-medium'>Official publishing access</h3>
          <p className='text-muted-foreground text-sm leading-relaxed'>Rafii needs its own approved Substack access before it can publish or schedule for customers. A partner’s permission does not authorize Rafii, and a public feed does not grant publishing access.</p>
          <p className='text-muted-foreground text-sm'>{capabilities.post_publish?.reason ?? 'Publishing access is not authorized for this workspace.'}</p>
          <Button variant='glass' size='control' onClick={onDrafts} className='self-start'>Prepare a draft now <Icons.arrowRight className='size-4' aria-hidden /></Button>
        </Surface>
      </div>
      <div className='flex flex-col gap-3'>
        <h3 className='text-foreground font-medium'>What is available</h3>
        <p className='text-muted-foreground text-sm'>Availability is reported by Rafii’s server for this workspace. Unavailable metrics stay unavailable; they are not shown as zero.</p>
        <dl className='divide-border flex flex-col divide-y sm:hidden'>
          {Object.entries(capabilities).map(([key, capability]) => <div key={key} className='flex flex-col gap-1 py-3'>
            <dt className='text-foreground text-sm font-medium'>{SUBSTACK_CAPABILITY_LABELS[key] ?? key.replaceAll('_', ' ')}</dt>
            <dd className='text-foreground text-sm'>{SUBSTACK_STATUS_LABELS[capability.status] ?? 'Status unavailable'}</dd>
            <dd className='text-muted-foreground text-sm leading-relaxed'>{capability.reason}</dd>
          </div>)}
        </dl>
        <div className='hidden overflow-x-auto sm:block'>
          <table className='w-full min-w-[34rem] text-left text-sm'>
            <caption className='sr-only'>Substack capabilities and official access requirements</caption>
            <thead><tr className='border-border border-b'><th scope='col' className='py-3 pr-4 font-medium'>Capability</th><th scope='col' className='py-3 pr-4 font-medium'>Status</th><th scope='col' className='py-3 font-medium'>Details</th></tr></thead>
            <tbody>{Object.entries(capabilities).map(([key, capability]) => <tr key={key} className='border-border border-b align-top'>
              <th scope='row' className='py-3 pr-4 font-normal'>{SUBSTACK_CAPABILITY_LABELS[key] ?? key.replaceAll('_', ' ')}</th>
              <td className='py-3 pr-4'>{SUBSTACK_STATUS_LABELS[capability.status] ?? 'Status unavailable'}</td>
              <td className='text-muted-foreground py-3 leading-relaxed'>{capability.reason}</td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
