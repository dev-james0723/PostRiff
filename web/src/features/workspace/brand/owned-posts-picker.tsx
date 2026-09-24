'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { appendOwnedPage, coverageSummary, loadedPosts, MAX_PREVIEW_PAGES, MAX_SELECTED_POSTS, selectedReceipts } from '@/lib/channels/owned-posts';
import Link from 'next/link';
import Image from 'next/image';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Band, FIELD_CLASS, SelectField } from '@/features/workspace/rafii-parts';
import { ApiError } from '@/lib/api/client';
import { keys, useChannels } from '@/lib/api/hooks';
import type { OwnedPostPage } from '@/lib/api/types';
import { historyBlocker } from '@/lib/channels/onboarding';
import { useWorkspaceApi } from '@/lib/workspace/provider';

export function OwnedPostsPicker({ revision, isOwner, preferredPlatform, autoPropose = false }: { revision: number; isOwner: boolean; preferredPlatform?: string; autoPropose?: boolean }) {
  const { workspaceId } = useWorkspaceApi();
  if (!isOwner || !workspaceId) return <p className='text-muted-foreground text-xs'>An owner can import posts from a connected account.</p>;
  // A workspace switch destroys previews and selection receipts, not just the account dropdown.
  return <PickerSession key={workspaceId} workspaceId={workspaceId} revision={revision} preferredPlatform={preferredPlatform} autoPropose={autoPropose} />;
}

function PickerSession({ workspaceId, revision, preferredPlatform, autoPropose }: { workspaceId: string; revision: number; preferredPlatform?: string; autoPropose: boolean }) {
  const { api } = useWorkspaceApi();
  const channels = useChannels();
  const cache = useQueryClient();
  const [chosenConnectionId, setConnectionId] = useState('');
  const [pages, setPages] = useState<OwnedPostPage[]>([]);
  const page = pages.at(-1);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [mediaType, setMediaType] = useState('');
  const autoStarted = useRef(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<'loading' | 'importing' | null>(null);
  const [error, setError] = useState('');
  const request = useRef(0);
  useEffect(
    () => () => {
      request.current += 1;
    },
    []
  );
  const accounts = channels.data?.channels.filter((item) => ['Instagram', 'LinkedIn'].includes(item.platform) && (!preferredPlatform || item.platform === preferredPlatform)) ?? [];
  const connectionId = chosenConnectionId || (autoPropose && accounts.length === 1 ? accounts[0].id : '');
  const account = accounts.find((item) => item.id === connectionId);
  const provider = channels.data?.providers.find((item) => item.platform === account?.platform);
  const blocker = historyBlocker(account, provider);
  const posts = loadedPosts(pages);
  const visible = posts.filter((post) => post.text.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()) && (!mediaType || post.mediaType === mediaType));

  const load = useCallback(
    async (cursor?: string) => {
      if (!connectionId || blocker || busy) return;
      const current = ++request.current;
      setBusy('loading');
      setError('');
      try {
        const next = await api.ownedPosts(workspaceId, connectionId, cursor);
        if (request.current !== current) return;
        const combined = appendOwnedPage(pages, next, cursor);
        setPages(combined);
        if (!cursor) {
          setSelected(
            autoPropose
              ? loadedPosts(combined)
                  .filter((post) => Number.isFinite(Date.parse(post.publishedAt)))
                  .toSorted((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt))
                  .slice(0, 10)
                  .map((post) => post.id)
              : []
          );
          setLabels({});
          setQuery('');
          setMediaType('');
        }
        setConfirmed(false);
      } catch (err) {
        if (request.current === current) setError(err instanceof Error ? err.message : 'Posts could not be loaded. No samples were imported.');
      } finally {
        if (request.current === current) setBusy(null);
      }
    },
    [api, workspaceId, connectionId, blocker, busy, pages, autoPropose]
  );

  useEffect(() => {
    if (!autoPropose || autoStarted.current || !connectionId || blocker) return;
    autoStarted.current = true;
    void load();
  }, [autoPropose, connectionId, blocker, load]);

  async function retain() {
    if (!page || !selected.length || !confirmed || busy || blocker) return;
    const current = ++request.current;
    setBusy('importing');
    setError('');
    try {
      const selections = selectedReceipts(pages, selected);
      const selectedLabels = Object.fromEntries(selected.filter((id) => labels[id]).map((id) => [id, labels[id]]));
      const snapshot = await api.importOwnedPostSelection(workspaceId, connectionId, selections, selectedLabels, revision);
      if (request.current !== current) return;
      cache.setQueryData(keys.snapshot(workspaceId), snapshot);
      void cache.invalidateQueries({ queryKey: keys.audit(workspaceId) });
      setSelected([]);
      setConfirmed(false);
      toast.success('Selected posts retained. Select the samples below and grant their analysis use separately.');
    } catch (err) {
      if (request.current === current) {
        setError(err instanceof Error ? err.message : 'Selected posts could not be retained.');
        if (err instanceof ApiError && err.status === 409) void cache.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      }
    } finally {
      if (request.current === current) setBusy(null);
    }
  }

  return (
    <Band as='section' data-tour='owned-posts-picker' aria-label='Import my social posts'>
      <h3 className='text-foreground text-sm font-medium'>{autoPropose ? 'Review Rafii’s proposed sample set' : 'Choose from my social posts'}</h3>
      {autoPropose && <p className='text-muted-foreground text-xs'>Your request authorizes read-only retrieval. Up to 10 dated posts from the loaded results are proposed, not retained or analyzed. Change this selection, confirm authorship, then separately allow an analysis route.</p>}
      <p className='text-muted-foreground text-xs'>Read your connected account, choose your own writing, then decide how it may be analysed. This never publishes or starts AI analysis.</p>
      {channels.isError && (
        <StateMessage
          kind='error'
          layout='inline'
          title='Accounts could not be loaded.'
          action={
            <Button variant='glass' size='sm' onClick={() => void channels.refetch()}>
              <Icons.refresh /> Retry
            </Button>
          }
        />
      )}
      <SelectField
        label='Account'
        aria-label='Account to read posts from'
        value={connectionId}
        disabled={Boolean(busy) || channels.isPending}
        onChange={(event) => {
          request.current += 1;
          setConnectionId(event.target.value);
          setPages([]);
          setSelected([]);
          setLabels({});
          setConfirmed(false);
          setError('');
        }}
      >
        <option value=''>Choose an Instagram or LinkedIn account</option>
        {accounts.map((item) => (
          <option key={item.id} value={item.id}>
            {item.platform} · {item.account}
          </option>
        ))}
      </SelectField>
      {blocker && (
        <p role='status' className='text-muted-foreground text-xs'>
          {blocker}{' '}
          <a href='#manual-writing-samples' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
            Import writing samples manually
          </a>
        </p>
      )}
      <div className='flex flex-wrap items-center gap-3'>
        <Button size='default' variant='glass' disabled={Boolean(busy) || Boolean(blocker)} onClick={() => void load()}>
          {busy === 'loading' ? (
            <>
              <Icons.spinner className='motion-safe:animate-spin' /> Reading posts…
            </>
          ) : (
            'Load my posts (read-only)'
          )}
        </Button>
        <Link className='rafii-focus text-foreground rounded-sm text-sm underline underline-offset-4' href='/app/channels'>
          Connect or manage accounts
        </Link>
      </div>
      {error && <StateMessage kind='error' layout='inline' title={error} />}
      {page && (
        <div className='flex flex-col gap-3'>
          <p role='status' className='text-muted-foreground text-xs'>
            {coverageSummary(pages)} {pages.length} pages · {pages.reduce((sum, item) => sum + item.scannedCount, 0)} records read · {pages.reduce((sum, item) => sum + item.skippedCount, 0)} excluded by the adapter.
          </p>
          <div className='grid gap-3 sm:grid-cols-[minmax(0,1fr)_14rem]'>
            <Input aria-label='Search retrieved posts' placeholder='Search only the posts loaded here…' value={query} onChange={(event) => setQuery(event.target.value)} className={FIELD_CLASS} />
            <SelectField label='Media type' hideLabel aria-label='Filter retrieved posts by media type' value={mediaType} onChange={(event) => setMediaType(event.target.value)}>
              <option value=''>All retrieved media types</option>
              {[...new Set(posts.map((post) => post.mediaType).filter(Boolean))].map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </SelectField>
          </div>
          <Button
            size='default'
            variant='glass'
            className='w-fit'
            disabled={Boolean(busy) || !visible.length}
            onClick={() => {
              setSelected((ids) => [...new Set([...ids, ...visible.map((post) => post.id)])].slice(0, MAX_SELECTED_POSTS));
              setConfirmed(false);
            }}
          >
            Select visible posts (up to 50)
          </Button>
          {!visible.length && <StateMessage kind='empty' layout='inline' title={posts.length ? 'No matching captions in the loaded results.' : 'No eligible captions in the retrieved pages.'} description={posts.length ? undefined : 'This is not a claim about your entire history.'} />}
          <ul className='grid gap-3 sm:grid-cols-2'>
            {visible.map((post) => (
              <li key={post.id} className='rafii-glass flex min-w-0 flex-col gap-3 rounded-[var(--rafii-radius-card)] p-4'>
                {post.thumbnailUrl && <Image src={post.thumbnailUrl} alt='Post preview' width={480} height={320} unoptimized loading='lazy' referrerPolicy='no-referrer' className='max-h-44 w-full rounded-[var(--rafii-radius-control)] object-contain' />}
                <div className='flex items-start gap-2'>
                  <Checkbox
                    className='mt-0.5'
                    aria-label={`Choose post ${post.id}`}
                    checked={selected.includes(post.id)}
                    disabled={Boolean(busy)}
                    onCheckedChange={(checked) => {
                      setSelected((ids) => (checked === true ? [...new Set([...ids, post.id])].slice(0, MAX_SELECTED_POSTS) : ids.filter((id) => id !== post.id)));
                      setConfirmed(false);
                    }}
                  />
                  <p className='text-foreground max-h-48 overflow-y-auto text-sm break-words whitespace-pre-wrap'>{post.text}</p>
                </div>
                <SelectField
                  label='Writing classification'
                  aria-label={`Classify post ${post.id}`}
                  value={labels[post.id] ?? ''}
                  disabled={Boolean(busy)}
                  onChange={(event) => {
                    setLabels((current) => ({ ...current, [post.id]: event.target.value }));
                    setConfirmed(false);
                  }}
                >
                  <option value=''>Unclassified</option>
                  <option value='representative'>Representative</option>
                  <option value='sponsored'>Sponsored</option>
                  <option value='outdated'>Outdated</option>
                  <option value='ai_generated'>AI-generated</option>
                  <option value='guest'>Guest writing</option>
                </SelectField>
                <Button
                  size='default'
                  variant='quiet'
                  className='w-fit'
                  disabled={Boolean(busy) || !selected.includes(post.id)}
                  onClick={() => {
                    setSelected((ids) => ids.filter((id) => id !== post.id));
                    setConfirmed(false);
                  }}
                >
                  Exclude from selection
                </Button>
                <div className='text-muted-foreground flex flex-wrap gap-2 text-xs'>
                  <span>{post.publishedAt || 'Date unavailable'}</span>
                  {post.permalink && (
                    <a href={post.permalink} target='_blank' rel='noopener noreferrer' className='rafii-focus text-foreground rounded-sm underline underline-offset-4'>
                      View original
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <label htmlFor='owned-post-authorship-consent' className='text-foreground flex items-start gap-2 text-xs leading-relaxed'>
            <Checkbox id='owned-post-authorship-consent' className='mt-0.5' checked={confirmed} disabled={Boolean(busy) || selected.length === 0} onCheckedChange={(checked) => setConfirmed(checked === true)} aria-label='Confirm selected captions are my own writing' />
            I wrote the selected captions and consent to retaining them as private samples. Guest writing, quoted third-party text and posts that do not represent my voice should be excluded. This does not grant AI use.
          </label>
          <div className='flex flex-wrap gap-2'>
            <Button size='control' variant='action' disabled={Boolean(busy) || !selected.length || !confirmed || Boolean(blocker)} onClick={() => void retain()}>
              {busy === 'importing' ? (
                <>
                  <Icons.spinner className='motion-safe:animate-spin' /> Retaining…
                </>
              ) : (
                `Retain ${selected.length} selected posts`
              )}
            </Button>
            <Button
              size='control'
              variant='quiet'
              disabled={Boolean(busy) || !selected.length}
              onClick={() => {
                setSelected([]);
                setConfirmed(false);
              }}
            >
              Clear selection
            </Button>
            <Button size='control' variant='glass' disabled={Boolean(busy) || !page.nextCursor || pages.length >= MAX_PREVIEW_PAGES || Boolean(blocker)} onClick={() => void load(page.nextCursor ?? undefined)}>
              Load more posts
            </Button>
          </div>
          <p className='text-muted-foreground text-xs leading-relaxed'>
            {selected.length} selected across {pages.length} loaded pages. Each preview is bounded to 4 pages (up to 100 records); retain at most 50 samples at once. Reaching that bound is not complete history. Preview receipts expire after ten minutes; reload expired
            selections. Sponsored, outdated and AI-generated classifications are shown, not silently treated as representative.
          </p>
        </div>
      )}
    </Band>
  );
}
