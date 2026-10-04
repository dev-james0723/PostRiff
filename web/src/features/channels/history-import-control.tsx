'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { StateMessage } from '@/components/rafii';
import { useIsMobile } from '@/hooks/use-mobile';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { ChannelView, ProviderView } from '@/lib/api/types';
import { historyImportActive, historyImportAllowed, historyImportError, historyImportKey, historyImportPoll, historyImportSupported, historyImportWaiting } from '@/lib/channels/history-import';
import { historyImportCopy, importCopyValues } from '@/lib/channels/history-import-copy';
import { disconnectedByCustomer } from '@/lib/channels/state';
import { usePreferences } from '@/lib/preferences';
import { formatDateTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { CONTROL_44, SHEET_ELEVATED } from './rafii-materials';

/** GET discovers the server gate. POST is never retried automatically or sent before explicit review. */
export function HistoryImportControl({ channel, provider, canManage }: { channel: ChannelView; provider?: ProviderView; canManage: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const { locale } = usePreferences();
  const { copy, lang, fallback } = historyImportCopy(locale);
  const client = useQueryClient();
  const isMobile = useIsMobile();
  const [open, setOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [reconciling, setReconciling] = useState(false);
  const supported = historyImportSupported(channel.platform);
  const disconnected = disconnectedByCustomer(channel);
  const status = useQuery({
    queryKey: historyImportKey(workspaceId, channel.id),
    queryFn: () => api.historyImportStatus(workspaceId, channel.id),
    enabled: supported && !disconnected,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => open && !query.state.error && historyImportPoll(query.state.data) ? 5_000 : false,
    refetchIntervalInBackground: false
  });
  const request = useMutation({
    mutationFn: () => api.requestHistoryImport(workspaceId, channel.id, { confirmed: true }),
    retry: false,
    onSuccess: (data) => {
      client.setQueryData(historyImportKey(workspaceId, channel.id), data);
      setReviewing(false);
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    },
    onError: async () => {
      // A lost POST response can still have queued a run. Reconcile with GET before offering a new request.
      setReconciling(true);
      const reconciled = await status.refetch();
      setReconciling(Boolean(reconciled.error));
    }
  });
  useEffect(() => {
    if (!open) { setConfirmed(false); setReviewing(false); }
  }, [open]);
  useEffect(() => {
    if (status.data?.status === 'done') void client.invalidateQueries({ queryKey: keys.analytics(workspaceId) });
  }, [status.data?.status, status.data?.metricReads.done, client, workspaceId]);

  // No candidate control is advertised while production is OFF; a server outage has a reviewable error state.
  if (!supported || disconnected || status.isPending || (status.error instanceof ApiError && historyImportError(status.error) === 'disabled')) return null;
  const data = status.data;
  const active = historyImportActive(data);
  const allowed = historyImportAllowed(channel, canManage, data);
  const error = request.error ?? status.error;
  const errorKind = error ? historyImportError(error instanceof ApiError ? error : {}) : null;
  const showReview = Boolean(data && (data.status === 'none' || reviewing));
  const waiting = historyImportWaiting(data);
  const failedReads = (data?.metricReads.unavailable ?? 0) + (data?.metricReads.dead ?? 0);
  const blockedError = errorKind && ['disabled', 'purging', 'analyticsRequired', 'throttled', 'sessionExpired', 'permission', 'disconnected'].includes(errorKind);

  function changeOpen(next: boolean) {
    setConfirmed(false);
    setReviewing(false);
    request.reset();
    setOpen(next);
  }
  async function refresh() {
    setConfirmed(false);
    const result = await status.refetch();
    if (!result.error) { setReconciling(false); request.reset(); }
  }
  return (
    <>
      <Button variant='quiet' className={CONTROL_44} onClick={() => changeOpen(true)} lang={lang}>{copy.open}</Button>
      <Sheet open={open} onOpenChange={changeOpen}>
        <SheetContent side={isMobile ? 'bottom' : 'right'} showCloseButton={false} className={cn(SHEET_ELEVATED, 'data-[side=bottom]:max-h-[92dvh] data-[side=right]:sm:max-w-lg')} lang={lang} dir='ltr'>
          <SheetHeader className='gap-2 px-5 pt-5 pr-14 pb-4'>
            <SheetTitle>{copy.title}</SheetTitle>
            <SheetDescription>{channel.platform} · {channel.account}</SheetDescription>
          </SheetHeader>
          <div className='flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 pb-4' data-testid='history-import-review'>
            {fallback && <p className='text-muted-foreground text-xs'>{copy.fallback}</p>}
            {status.isFetching && <p role='status' className='text-muted-foreground text-sm'>{copy.loading}</p>}
            {errorKind && <StateMessage kind='error' layout='inline' title={copy[errorKind]} />}
            {data?.purgePending ? <StateMessage kind='loading' layout='inline' title={copy.purging} /> : data && (
              <div role='status' aria-live='polite' className='rafii-quiet rounded-lg p-3 text-sm'>
                <p className='font-medium'>{copy[data.status]}</p>
                {data.importId && <p className='text-muted-foreground mt-1'>{importCopyValues(copy.posts, { posts: data.posts ?? 0, pages: data.pages ?? 0 }, locale)}</p>}
                {data.status === 'running' && data.failure && <><p className='mt-1'>{copy.retrying}</p>{data.retryAt && <p>{importCopyValues(copy.retryAt, { time: formatDateTime(data.retryAt) }, locale)}</p>}</>}
                {data.failure === 'incomplete_paging' && <p className='mt-1'>{copy.incomplete}</p>}
                {data.importId && <p className='text-muted-foreground mt-1'>{importCopyValues(copy.reads, { done: data.metricReads.done ?? 0, waiting }, locale)}</p>}
                {failedReads > 0 && <p>{importCopyValues(copy.readFailures, { unavailable: failedReads }, locale)}</p>}
              </div>
            )}
            {!canManage && <p className='text-muted-foreground text-sm'>{copy.noManage}</p>}
            {channel.capabilities.analytics?.level !== 'Direct' && <div className='flex flex-col gap-2 text-sm'><p>{copy.analyticsRequired}</p>{canManage && provider && <Link href={`/app/channels?connect=${encodeURIComponent(provider.id)}&capability=analytics`} className='rafii-focus underline'>{copy.reconnect}</Link>}</div>}
            {!allowed && canManage && channel.capabilities.analytics?.level === 'Direct' && !active && !data?.purgePending && <p className='text-muted-foreground text-sm'>{copy.disconnected}</p>}
            {showReview && <section className='flex flex-col gap-3 text-sm' aria-label={copy.review}>
              <p>{copy.bounds}</p><p>{copy.metadata}</p><p>{copy.metrics}</p><p>{copy.purge}</p>
              <label className='flex min-h-11 items-start gap-3'><input type='checkbox' aria-label={copy.confirm} className='mt-1 size-4 shrink-0' checked={confirmed} disabled={!allowed || request.isPending || reconciling || Boolean(blockedError) || Boolean(status.error) || status.isFetching} onChange={(event) => setConfirmed(event.target.checked)} /><span>{copy.confirm}</span></label>
              <Button variant='action' size='control' disabled={!confirmed || !allowed || request.isPending || reconciling || Boolean(blockedError) || Boolean(status.error) || status.isFetching} onClick={() => { setConfirmed(false); request.mutate(); }}>{request.isPending ? copy.pending : copy.request}</Button>
            </section>}
            {data && !showReview && !active && !data.purgePending && allowed && <Button variant='glass' size='control' onClick={() => { setConfirmed(false); request.reset(); setReviewing(true); }}>{copy.repeat}</Button>}
          </div>
          <SheetFooter className='flex-row flex-wrap justify-end gap-2 px-5 pb-[max(1rem,env(safe-area-inset-bottom))]'>
            <Button variant='glass' size='control' disabled={status.isFetching || request.isPending} onClick={() => void refresh()}>{copy.refresh}</Button>
            <Button variant='quiet' size='control' onClick={() => changeOpen(false)}>{copy.close}</Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
    </>
  );
}
