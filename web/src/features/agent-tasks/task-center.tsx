'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import PageContainer from '@/components/layout/page-container';
import { Button } from '@/components/ui/button';
import { StateMessage } from '@/components/rafii/state-message';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { usePreferences } from '@/lib/preferences';
import { ApiError } from '@/lib/api/client';
import { createTaskApi, taskRequestKey, forgetTaskRequest, readPendingTask, savePendingTask, clearPendingTask, runTaskRequest, type TaskRequest, type TaskDetail, type TaskView, type TaskResponse, type TaskState, type TaskApproval } from '@/lib/agent-runtime/tasks';
import { changedResourceHref, isOpen, language, receiptVerified, safeTaskHref, stateLabel, summaryLines, text, type CopyKey, type Language } from './model';

type Pending = { title: TaskRequest['kind']; note: CopyKey; key: string; identity: string; taskId: string; version?: number; approval?: TaskApproval; uncertain: boolean; request: TaskRequest };
function actionNote(kind: TaskRequest['kind']): CopyKey { return kind === 'cancel' ? 'cancelNote' : kind === 'undo' ? 'undoNote' : ['approve', 'reject'].includes(kind) ? 'reviewNote' : 'continueNote'; }
const panel = 'rounded-xl border border-border bg-card p-4 sm:p-5';

export function TaskCenter() {
  const { user } = useAuth();
  const { workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const boundary = `${access.role}:${[...access.permissions].sort().join(',')}`;
  // Remount local selection, confirmation and announcements on either security boundary.
  return <TaskCenterWorkspace key={`${user?.id}:${workspaceId}:${boundary}`} boundary={boundary} />;
}

function TaskCenterWorkspace({ boundary }: { boundary: string }) {
  const { user, getToken } = useAuth();
  const { workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const { locale, timeZone } = usePreferences();
  const lang = language(locale);
  const t = (key: CopyKey) => text(key, lang);
  const api = useMemo(() => createTaskApi(getToken), [getToken]);
  const client = useQueryClient();
  const queryPrefix = ['agent-tasks', user?.id, workspaceId, boundary];
  const [view, setView] = useState<TaskView>('open');
  const [scope, setScope] = useState<'mine' | 'workspace'>('mine');
  const owner = checkAccess(access, { permission: 'owner' });
  const effectiveScope = owner ? scope : 'mine';
  const requestScope = `${user?.id}:${workspaceId}`;
  const [recovered] = useState(() => readPendingTask(requestScope));
  const [selected, setSelected] = useState<string | null>(recovered?.request.taskId ?? null);
  const [pending, setPending] = useState<Pending | null>(() => recovered ? { ...recovered, taskId: recovered.request.taskId,
    title: recovered.request.kind, note: actionNote(recovered.request.kind), version: recovered.request.version, uncertain: true } : null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [actionError, setActionError] = useState('');
  const lock = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const confirmation = useRef<HTMLHeadingElement>(null);
  const enabled = Boolean(user?.id && workspaceId);
  const list = useInfiniteQuery({
    queryKey: [...queryPrefix, 'list', view, effectiveScope],
    queryFn: ({ pageParam, signal }) => api.list(workspaceId, view, effectiveScope, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
    enabled, retry: false, refetchIntervalInBackground: false,
    refetchInterval: (q) => q.state.error || q.state.data?.pages[0]?.engine === 'disabled' ? false : 5000
  });
  const detail = useQuery({
    queryKey: [...queryPrefix, 'detail', selected],
    queryFn: ({ signal }) => api.detail(workspaceId, selected!, signal),
    enabled: enabled && Boolean(selected), retry: false, refetchIntervalInBackground: false,
    refetchInterval: (q) => !q.state.error && isOpen(q.state.data?.engine?.state) ? 4000 : false
  });
  // Never render a stale payload after the server has denied a refreshed read.
  const task = !detail.error && detail.data?.engine && 'taskId' in detail.data.engine ? detail.data.engine as TaskDetail : null;
  const items = !list.error ? [...new Map((list.data?.pages.flatMap((p) => p.items) ?? []).map((item) => [item.taskId, item])).values()] : [];
  const unavailable = list.error instanceof ApiError && list.error.status === 404 || list.data?.pages[0]?.engine === 'disabled';
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('task');
    if (!recovered && id && /^[a-zA-Z0-9-]{1,100}$/.test(id)) setSelected(id);
  }, []);
  useEffect(() => { if (selected && task) heading.current?.focus(); }, [selected, Boolean(task)]);
  useEffect(() => { if (pending) confirmation.current?.focus(); }, [pending]);
  useEffect(() => { setPending((value) => value?.taskId === selected ? value : null); setActionError(''); }, [selected]);
  const format = (value?: string | null) => {
    if (!value || !Number.isFinite(Date.parse(value))) return '';
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(new Date(value));
  };
  function ask(request: TaskRequest, approval?: TaskApproval) {
    if (!task || lock.current || pending?.uncertain) return;
    const identity = [user?.id, workspaceId, task.taskId, request.kind, task.version, approval?.approvalId, approval?.digest, request.step?.stepKey, request.step?.generation, request.step?.undo?.compensationId].join(':');
    setActionError(''); setNotice(''); setPending({ title: request.kind, note: actionNote(request.kind), request, key: taskRequestKey(identity), identity, taskId: task.taskId,
      version: task.version, approval: approval ? structuredClone(approval) : undefined, uncertain: false });
  }
  const blocked = busy || pending?.uncertain === true;
  const currentApproval = pending?.request.approval && task?.approvals?.find((a) => a.approvalId === pending.request.approval!.approvalId);
  const confirmationApproval = pending?.approval ?? (currentApproval?.digest === pending?.request.approval?.digest ? currentApproval : undefined);
  const pendingCurrent = !pending || pending.uncertain || (task?.version === pending.version && (!pending.approval ||
    Boolean(currentApproval?.can.decide && currentApproval.state === 'pending' && !currentApproval.requiresStepUp &&
      currentApproval.digest === pending.approval.digest && Date.parse(currentApproval.expiresAt) > Date.now())));
  async function submit() {
    if (!pending || !task || pending.taskId !== task.taskId || lock.current || !pendingCurrent) return;
    lock.current = true; setBusy(true); setActionError('');
    try {
      savePendingTask(requestScope, { request: pending.request, key: pending.key, identity: pending.identity });
      await runTaskRequest(api, workspaceId, pending.request, pending.key);
      forgetTaskRequest(pending.identity);
      clearPendingTask(requestScope);
      setPending(null); setNotice(t('submitted'));
      await client.invalidateQueries({ queryKey: queryPrefix });
    } catch (error) {
      // Keep the same request and idempotency key when a response is lost.
      setActionError(error instanceof Error ? error.message : t('unavailable'));
      const uncertain = !(error instanceof ApiError && error.status >= 400 && error.status < 500 && ![408, 429].includes(error.status));
      if (!uncertain) clearPendingTask(requestScope);
      setPending((value) => value ? { ...value, uncertain } : value);
      await client.invalidateQueries({ queryKey: queryPrefix });
    } finally { lock.current = false; setBusy(false); }
  }
  const href = safeTaskHref(task?.href);
  return <PageContainer pageTitle={t('title')} pageDescription={t('subtitle')} pageHeaderAction={
    <Button variant='quiet' disabled={list.isFetching || busy} onClick={() => void client.invalidateQueries({ queryKey: queryPrefix })}>{t('reload')}</Button>
  }>
    <div className='flex flex-wrap items-center justify-between gap-3'>
      <div className='flex flex-wrap gap-1' role='group' aria-label={t('title')}>
        {(['open', 'needs_me', 'recent'] as const).map((value) => <Button key={value} variant={view === value ? 'default' : 'quiet'} aria-pressed={view === value}
          onClick={() => setView(value)}>{t(value)}</Button>)}
      </div>
      {owner && <label className='text-sm'><span className='sr-only'>{t('workspace')}</span><select disabled={blocked} className='rounded-lg border border-border bg-background p-2' value={effectiveScope}
        onChange={(event) => { setScope(event.target.value as 'mine' | 'workspace'); setSelected(null); }}>{(['mine', 'workspace'] as const).map((value) => <option key={value} value={value}>{t(value)}</option>)}</select></label>}
    </div>
    <p className='sr-only' role='status' aria-live='polite'>{notice}</p>
    {unavailable ? <StateMessage kind='empty' title={t('unavailable')} /> : list.error ? <StateMessage kind='error' title={list.error.message} /> :
      <div className='grid min-w-0 gap-5 lg:grid-cols-[minmax(240px,0.8fr)_minmax(0,2fr)]'>
        <section aria-label={t('title')} className='min-w-0'>
          {list.isPending ? <p role='status'>{t('loading')}</p> : items.length === 0 ? <StateMessage kind='empty' title={t('empty')} /> :
            <ul className='space-y-2'>{items.map((item) => <li key={item.taskId}><button type='button' aria-current={selected === item.taskId ? 'true' : undefined}
              className={`w-full rounded-xl border p-4 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring ${selected === item.taskId ? 'border-primary bg-primary/5' : 'border-border bg-card hover:bg-muted/50'}`}
              onClick={() => { if (!blocked) setSelected(item.taskId); }} disabled={blocked}>
              <span className='block break-words font-medium'>{item.title}</span><span className='mt-2 block text-sm text-muted-foreground'>{stateLabel(item.state, lang)}{item.progress ? ` · ${item.progress.completed}/${item.progress.total}` : ''}</span>
              {item.partial && <span className='mt-1 block text-xs text-muted-foreground'>{t('partial')}</span>}
              <time className='mt-2 block text-xs text-muted-foreground' dateTime={item.updatedAt}>{format(item.updatedAt)}</time>
            </button></li>)}</ul>}
          {list.hasNextPage && <Button className='mt-3' variant='quiet' disabled={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>{t('more')}</Button>}
        </section>
        <section className='min-w-0 space-y-4' aria-label={t('evidence')}>
          {!selected ? <StateMessage kind='empty' title={t('select')} /> : detail.error ? <StateMessage kind='error' title={detail.error.message} /> : !task ?
            <StateMessage kind='empty' title={detail.isPending ? t('loading') : t('access')} /> : <>
            <div className={panel}>
              <h2 ref={heading} tabIndex={-1} className='break-words text-xl font-semibold outline-none'>{task.title}</h2>
              <p className='mt-2 text-sm text-muted-foreground'>{stateLabel(task.state, lang)}{task.progress ? ` · ${task.progress.completed}/${task.progress.total} ${t('completedSteps')}` : ''}</p>
              {task.partial && <p className='mt-3 text-sm'>{t('partial')}</p>}
              {task.spend && <p className='mt-2 text-sm text-muted-foreground'>{new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 4 }).format(task.spend.spentUsdMicro / 1000000)}{task.spend.unknown ? ` · ${t('unknownCost')}` : ''}</p>}
              <div className='mt-4 flex flex-wrap items-center gap-2'>
                {href && <Link className='text-sm underline underline-offset-4' href={href}>{t('conversation')}</Link>}
                {task.can?.continue && <Button disabled={blocked} variant='quiet' onClick={() => ask({ kind: 'continue', taskId: task.taskId, version: task.version })}>{t('continue')}</Button>}
                {task.can?.cancel && <Button disabled={blocked} variant='quiet' onClick={() => ask({ kind: 'cancel', taskId: task.taskId, version: task.version })}>{t('cancel')}</Button>}
              </div>
            </div>
            {pending && <div className={`${panel} border-primary/40`} role='region' aria-label={t(pending.title)}>
              <h3 ref={confirmation} tabIndex={-1} className='font-medium outline-none'>{t(pending.title)}</h3><p className='mt-2 text-sm'>{t(pending.note)}</p>
              {confirmationApproval && <dl className='mt-3 space-y-3'>{summaryLines(confirmationApproval.summary).lines.map((line, i) => <div key={i}><dt className='text-xs text-muted-foreground'>{line.label}</dt><dd className='mt-1 whitespace-pre-wrap break-words text-sm'>{line.value}</dd></div>)}</dl>}
              {!pendingCurrent && <p role='status' className='mt-2 text-sm'>{t('changed')}</p>}
              {pending.uncertain && <p role='status' className='mt-2 text-sm'>{t('uncertain')}</p>}
              {actionError && <p role='alert' className='mt-2 text-sm text-destructive'>{actionError}</p>}
              <div className='mt-4 flex gap-2'><Button disabled={busy || !pendingCurrent} onClick={() => void submit()}>{t('confirm')}</Button><Button variant='quiet' disabled={blocked} onClick={() => setPending(null)}>{t('back')}</Button></div>
            </div>}
            {Boolean(task.approvals?.length) && <section className={panel}><h3 className='font-medium'>{t('approvals')}</h3><div className='mt-4 space-y-5'>
              {task.approvals!.map((approval) => {
                const summary = summaryLines(approval.summary); const expired = !Number.isFinite(Date.parse(approval.expiresAt)) || Date.parse(approval.expiresAt) <= Date.now();
                const canDecide = approval.can.decide && approval.state === 'pending' && !expired && !approval.requiresStepUp;
                return <article key={approval.approvalId} className='rounded-lg border border-border p-4'><h4 className='font-medium'>{approval.kind.replaceAll('_', ' ')}</h4>
                  <dl className='mt-3 space-y-3'>{summary.lines.map((line, i) => <div key={i}><dt className='text-xs text-muted-foreground'>{line.label}</dt><dd className='mt-1 whitespace-pre-wrap break-words text-sm'>{line.value}</dd></div>)}</dl>
                  {!summary.complete && <p className='mt-3 text-sm'>{t('incomplete')}</p>}
                  <p className='mt-3 text-xs text-muted-foreground'>{expired ? t('expired') : format(approval.expiresAt)}</p>
                  {approval.requiresStepUp && <p className='mt-2 text-sm'>{t('stepUp')}</p>}
                  {canDecide && <div className='mt-4 flex flex-wrap gap-2'><Button disabled={blocked || !summary.complete} onClick={() => ask({ kind: 'approve', taskId: task.taskId, version: task.version, approval: { approvalId: approval.approvalId, digest: approval.digest }, timeZone }, approval)}>{t('approve')}</Button>
                    <Button disabled={blocked} variant='quiet' onClick={() => ask({ kind: 'reject', taskId: task.taskId, version: task.version, approval: { approvalId: approval.approvalId, digest: approval.digest }, timeZone }, approval)}>{t('reject')}</Button></div>}
                </article>;
              })}
            </div></section>}
            {Boolean(task.steps?.length) && <section className={panel}><h3 className='font-medium'>{t('steps')}</h3><ol className='mt-4 divide-y divide-border'>
              {task.steps!.map((step) => <li className='py-4 first:pt-0 last:pb-0' key={step.stepKey}>
                <div className='flex flex-wrap justify-between gap-2'><span className='font-medium'>{step.label}</span><span className='text-sm text-muted-foreground'>{stateLabel(step.state, lang)}</span></div>
                {step.reason && <p className='mt-2 whitespace-pre-wrap break-words text-sm'>{step.reason}</p>}
                {step.delegate && <p className='mt-2 text-sm text-muted-foreground'>{step.delegate.type.replaceAll('_', ' ')} · {step.delegate.state}</p>}
                {step.nextAttemptAt && <time className='mt-2 block text-xs text-muted-foreground'>{format(step.nextAttemptAt)}</time>}
                <div className='mt-3 flex flex-wrap items-center gap-2'>
                  {safeTaskHref(step.delegate?.href) && <Link className='text-sm underline underline-offset-4' href={safeTaskHref(step.delegate?.href)!}>{t('result')}</Link>}
                  {step.can.retry && <Button variant='quiet' disabled={blocked} onClick={() => ask({ kind: 'retry', taskId: task.taskId, version: task.version, step: { stepKey: step.stepKey, generation: step.generation, undo: null } })}>{t('retry')}</Button>}
                  {step.can.undo && step.undo && Date.parse(step.undo.undoUntil) > Date.now() && <Button variant='quiet' disabled={blocked} onClick={() => ask({ kind: 'undo', taskId: task.taskId, version: task.version, step: { stepKey: step.stepKey, generation: step.generation, undo: step.undo } })}>{t('undo')}</Button>}
                </div>
              </li>)}
            </ol></section>}
            <section className={panel}><h3 className='font-medium'>{t('evidence')}</h3>{!task.receipts?.length ? <p className='mt-3 text-sm text-muted-foreground'>{t('noEvidence')}</p> :
              <ul className='mt-4 space-y-4'>{task.receipts.map((receipt) => <li key={receipt.effectKey} className='rounded-lg border border-border p-3'>
                <p className='text-sm font-medium'>{receiptVerified(receipt) ? t('verified') : t('unverified')} · {receipt.outcome}</p>
                <time className='mt-1 block text-xs text-muted-foreground'>{format(receipt.at)}</time>
                {receipt.providerReceipt && <p className='mt-2 text-sm'>{receipt.providerReceipt.kind} · {receipt.providerReceipt.state}</p>}
                <ul className='mt-2 text-sm'>{receipt.checks.map((check, i) => <li key={i}>{check.ok ? '✓' : '×'} {check.name}</li>)}</ul>
                <ul className='mt-2 space-y-1 text-sm'>{receipt.changedRefs.map((ref, i) => <li className='break-words' key={`${ref.type}:${ref.id}:${i}`}>
                  {ref.change.replaceAll('_', ' ')} · {ref.id}{' '}
                  {changedResourceHref(ref) && <Link className='underline underline-offset-4' href={changedResourceHref(ref)!}>{t('result')}</Link>}
                </li>)}</ul>
                {receipt.cannotRecall.map((note, i) => <p key={i} className='mt-2 text-sm'>{note}</p>)}
              </li>)}</ul>}
            </section>
            {task.steps && detail.data && <TaskHistory key={task.taskId} api={api} workspaceId={workspaceId} taskId={task.taskId} userId={user?.id}
              initial={detail.data} active={isOpen(task.state)} lang={lang} format={format} boundary={boundary} />}
          </>}
        </section>
      </div>}
  </PageContainer>;
}

function TaskHistory({ api, workspaceId, taskId, userId, initial, active, lang, format, boundary }: {
  api: ReturnType<typeof createTaskApi>; workspaceId: string; taskId: string; userId?: string; initial: TaskResponse;
  active: boolean; lang: Language; format: (value?: string | null) => string; boundary: string;
}) {
  const history = useInfiniteQuery({
    queryKey: ['agent-tasks', userId, workspaceId, boundary, 'history', taskId],
    queryFn: ({ pageParam, signal }) => api.detail(workspaceId, taskId, signal, pageParam),
    initialPageParam: 0, initialData: { pages: [initial], pageParams: [0] },
    getNextPageParam: (last, _pages, previous) => last.events.length === 500 && last.cursor > previous ? last.cursor : undefined,
    retry: false, refetchIntervalInBackground: false,
    refetchInterval: (q) => active && !q.state.error ? 10000 : false
  });
  const events = [...new Map(history.data.pages.flatMap((page) => page.events).map((event) => [event.id, event])).values()];
  return <section className={panel}><h3 className='font-medium'>{text('history', lang)}</h3>
    {history.error ? <p role='alert' className='mt-3 text-sm'>{history.error.message}</p> : events.length === 0 ?
      <p className='mt-3 text-sm text-muted-foreground'>{text('noHistory', lang)}</p> : <ol className='mt-3 space-y-3'>{events.map((event) => <li key={event.id} className='border-l-2 border-border pl-3'>
        <p className='text-sm'>{event.label || (event.stage || event.type).replaceAll('_', ' ').replaceAll('.', ' ')}{event.state ? ` · ${stateLabel(event.state as TaskState, lang)}` : ''}</p>
        {Number.isFinite(event.at) && <time className='text-xs text-muted-foreground' dateTime={new Date(event.at * 1000).toISOString()}>{format(new Date(event.at * 1000).toISOString())}</time>}
      </li>)}</ol>}
    {history.hasNextPage && !history.error && <Button className='mt-3' variant='quiet' disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>{text('more', lang)}</Button>}
  </section>;
}
